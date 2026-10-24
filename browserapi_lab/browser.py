"""Abertura e fechamento do navegador (Marco 2).

Decisões desta camada:

* **uma** instância de navegador e, inicialmente, **uma** aba quente (briefing);
* perfil exclusivo via :mod:`browserapi_lab.session` + lock;
* fechamento limpo sempre (``__exit__``) para não corromper o perfil;
* medição de RSS da árvore do navegador por leitura de ``/proc`` (sem dependências);
* screenshots e traces **desligados** por padrão (só diagnóstico explícito).

O Playwright é importado tardiamente: o núcleo do laboratório continua
funcionando (e testável) sem navegador instalado — ver ADR-002.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .session import ProfileLock, ensure_profile

DEFAULT_ARGS: Tuple[str, ...] = (
    "--disable-dev-shm-usage",   # containers com /dev/shm pequeno (Codespaces, CI)
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
)

DEFAULT_VIEWPORT: Dict[str, int] = {"width": 1280, "height": 900}


@dataclass
class BrowserConfig:
    """Configuração de abertura do navegador."""

    profile: str = "default"
    profiles_root: str | Path = "profiles"
    channel: Optional[str] = None          # None = chromium gerenciado; "chrome" = sistema
    headless: bool = True
    slow_mo_ms: int = 0
    timeout_ms: int = 30_000
    viewport: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_VIEWPORT))
    extra_args: Tuple[str, ...] = ()
    locale: str = "pt-BR"
    screenshot_on_error: bool = False

    @property
    def profile_dir(self) -> Path:
        return ensure_profile(self.profile, self.profiles_root)


def chromium_available(channel: Optional[str] = None) -> bool:
    """O navegador pedido existe neste ambiente? (usado para pular testes)."""
    try:
        from playwright.sync_api import sync_playwright  # import tardio
    except Exception:
        return False
    try:
        with sync_playwright() as pw:
            browser_type = getattr(pw, "chromium")
            path = browser_type.executable_path
            if channel:
                # canal do sistema: só confirmamos que o binário existe
                return shutil.which(channel) is not None or channel in ("chrome", "chromium")
            return bool(path) and os.path.exists(path)
    except Exception:
        return False


def browser_environment_error() -> Optional[str]:
    """Motivo legível pelo qual não há navegador (ou ``None`` se houver)."""
    try:
        import playwright  # noqa: F401
    except Exception:
        return "playwright não instalado"
    import tempfile

    from .doctor import build_report

    report = build_report(results_path=tempfile.gettempdir())
    if not report.browser_ready:
        if report.missing_required_libs:
            return (
                "faltam bibliotecas de runtime do Chromium: "
                + ", ".join(report.missing_required_libs[:4])
                + ("..." if len(report.missing_required_libs) > 4 else "")
            )
        if not report.playwright_browsers and not report.system_browsers:
            return "nenhum navegador baixado (execute: python -m playwright install chromium)"
    return None


class BrowserSession:
    """Contexto persistente do Chromium com lock de perfil e aba reutilizável."""

    def __init__(self, config: Optional[BrowserConfig] = None) -> None:
        self.config = config or BrowserConfig()
        self._lock = ProfileLock(self.config.profile_dir)
        self._pw: Any = None
        self._context: Any = None
        self._started_at: Optional[float] = None
        self._cold_start_ms: Optional[float] = None

    # ---------------------------------------------------------------- ciclo
    def start(self) -> "BrowserSession":
        if self._context is not None:
            return self
        from playwright.sync_api import sync_playwright  # import tardio

        started = time.perf_counter()
        self._lock.acquire()
        try:
            self._pw = sync_playwright().start()
            launch_kwargs: Dict[str, Any] = dict(
                user_data_dir=str(self.config.profile_dir),
                headless=self.config.headless,
                slow_mo=self.config.slow_mo_ms or 0,
                args=list(DEFAULT_ARGS) + list(self.config.extra_args),
                viewport=self.config.viewport,
                locale=self.config.locale,
            )
            if self.config.channel:
                launch_kwargs["channel"] = self.config.channel
            browser_type = getattr(self._pw, "chromium")
            self._context = browser_type.launch_persistent_context(**launch_kwargs)
            self._context.set_default_timeout(self.config.timeout_ms)
        except BaseException:
            self.close()
            raise
        self._started_at = time.perf_counter()
        self._cold_start_ms = (self._started_at - started) * 1000.0
        return self

    @property
    def context(self) -> Any:
        if self._context is None:
            raise RuntimeError("sessão não iniciada; chame start()")
        return self._context

    @property
    def cold_start_ms(self) -> Optional[float]:
        return self._cold_start_ms

    def page(self, url: Optional[str] = None) -> Any:
        """Aba quente: reaproveita a primeira aba existente (briefing: aba única)."""
        ctx = self.context
        pages = ctx.pages
        page = pages[0] if pages else ctx.new_page()
        if url and page.url != url:
            page.goto(url, wait_until="domcontentloaded")
        return page

    def new_page(self, url: Optional[str] = None) -> Any:
        page = self.context.new_page()
        if url:
            page.goto(url, wait_until="domcontentloaded")
        return page

    def close(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            try:
                if self._pw is not None:
                    try:
                        self._pw.stop()
                    finally:
                        self._pw = None
            finally:
                self._lock.release()

    def __enter__(self) -> "BrowserSession":
        return self.start()

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


def rss_kb(pid: int) -> Optional[int]:
    """RSS de um processo via ``/proc`` (KB), ou ``None`` se indisponível."""
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def tree_rss_kb(root_pid: int) -> Optional[int]:
    """RSS aproximado da árvore de processos a partir de ``root_pid``.

    Soma ``VmRSS`` do processo raiz e de todos os descendentes encontrados em
    ``/proc/*/stat`` (campo ``ppid``). Aproximado por construção: threads
    compartilham memória — a métrica serve para **comparar** estratégias, não
    para contabilidade absoluta.
    """
    children: Dict[int, List[int]] = {}
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/stat", "r", encoding="utf-8") as handle:
                    data = handle.read()
                ppid = int(data.rpartition(")")[2].split()[1])
                children.setdefault(ppid, []).append(int(entry))
            except (OSError, ValueError, IndexError):
                continue
    except OSError:
        return None

    total = 0
    seen = set()
    stack = [root_pid]
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        value = rss_kb(pid)
        if value:
            total += value
        stack.extend(children.get(pid, []))
    return total or None


def browser_tree_rss_kb(session: BrowserSession) -> Optional[int]:
    """RSS aproximado da árvore do navegador associada a esta sessão."""
    if session._context is None:
        return None
    pids: List[int] = []
    try:
        # processos filhos diretos do Python que pertencem ao navegador
        import subprocess

        out = subprocess.run(
            ["pgrep", "-P", str(os.getpid())], capture_output=True, text=True, timeout=5
        ).stdout
        pids = [int(line) for line in out.split() if line.isdigit()]
    except (OSError, subprocess.SubprocessError, ValueError):
        pids = []
    total = 0
    for pid in pids:
        value = tree_rss_kb(pid)
        if value:
            total += value
    return total or None
