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
import secrets
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
    executable_path: Optional[str] = None
    headless: bool = True
    slow_mo_ms: int = 0
    timeout_ms: int = 30_000
    viewport: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_VIEWPORT))
    extra_args: Tuple[str, ...] = ()
    locale: str = "pt-BR"
    screenshot_on_error: bool = False
    attach_existing_chrome: bool = False
    existing_installation: str = "chrome"
    existing_profile: str = ""

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
        self._lock = ProfileLock(Path(self.config.profiles_root) / '.attached-chrome') if self.config.attach_existing_chrome else ProfileLock(self.config.profile_dir)
        self._pw: Any = None
        self._context: Any = None
        self._profile_context_id: Optional[str] = None
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
            if self.config.attach_existing_chrome:
                from .existing_chrome import endpoint, ExistingChromeError, verify_profile
                from .profiles import installation_root, profile_name, open_profile
                if not self.config.existing_profile:
                    raise ExistingChromeError('Escolha um perfil na lista antes de conectar. Não assumimos que o Chrome concedeu a conta desejada.')
                directory = profile_name(self.config.existing_profile)
                proof_url = 'chrome://version/#browserapi-' + secrets.token_hex(16)
                # Pedido nativo ao processo existente, não uma cópia/novo user_data_dir.
                # O nonce distingue nossa aba de todas as abas pessoais já abertas.
                open_profile(self.config.existing_installation + ':' + directory, proof_url)
                self._attached_browser = self._pw.chromium.connect_over_cdp(endpoint() if self.config.existing_installation == "chrome" else endpoint(installation=self.config.existing_installation), timeout=60000)
                proofs = [p for c in self._attached_browser.contexts for p in c.pages if p.url == proof_url]
                if len(proofs) != 1:
                    raise ExistingChromeError('O Chrome não expôs a aba de verificação do perfil escolhido. Nenhum chat foi aberto ou preenchido. Abra o perfil desejado pelo avatar, confira Depuração remota e reconecte. Se continuar, esta versão não permite selecionar esse perfil por este modo.')
                probe = proofs[0]
                expected = installation_root(self.config.existing_installation) / directory
                self._profile_context_id = verify_profile(probe.context, expected, probe=probe)
                self._context = probe.context
                self._context.set_default_timeout(self.config.timeout_ms)
                self._cold_start_ms = (time.perf_counter() - started) * 1000
                return self
            launch_kwargs: Dict[str, Any] = dict(
                user_data_dir=str(self.config.profile_dir),
                headless=self.config.headless,
                slow_mo=self.config.slow_mo_ms or 0,
                args=list(DEFAULT_ARGS) + list(self.config.extra_args),
                viewport=self.config.viewport,
                locale=self.config.locale,
            )
            if self.config.channel and self.config.executable_path:
                raise ValueError("Escolha canal ou executável, não ambos.")
            if self.config.executable_path:
                executable = Path(self.config.executable_path).expanduser().resolve()
                if not executable.is_file() or not os.access(executable, os.X_OK):
                    raise ValueError("Executável não encontrado ou sem permissão de execução.")
                launch_kwargs["executable_path"] = str(executable)
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
        if self.config.attach_existing_chrome:
            from .config import origin
            from .existing_chrome import ExistingChromeError
            if not url:
                raise ValueError('Informe o chat escolhido antes de acessar abas pessoais.')
            from .existing_chrome import target_context_id
            if not self._profile_context_id:
                raise ExistingChromeError('O perfil desta conexão não foi verificado. Reconecte antes de acessar o chat.')
            matches = [p for p in pages if p.url.startswith(('http://', 'https://'))
                       and origin(p.url) == origin(url)
                       and target_context_id(ctx, p) == self._profile_context_id]
            if len(matches) > 1:
                raise ExistingChromeError('Mais de uma aba do chat está aberta. Deixe somente uma para conectar; nenhuma aba foi fechada pelo programa.')
            if matches:
                return matches[0]
            # Consent was obtained before attachment. Open only the requested
            # chat in this existing context; never launch another profile.
            from .config import safe_url
            safe_url(url)
            page = self.new_page()
            # Navigation failure is surfaced, never retried by creating more tabs.
            page.goto(url, wait_until='domcontentloaded')
            return page
        page = pages[0] if pages else ctx.new_page()
        if url and page.url != url:
            page.goto(url, wait_until="domcontentloaded")
        return page

    def new_page(self, url: Optional[str] = None) -> Any:
        page = self.context.new_page()
        if self.config.attach_existing_chrome:
            from .existing_chrome import target_context_id, ExistingChromeError
            try:
                if not self._profile_context_id or target_context_id(self.context, page) != self._profile_context_id:
                    raise ExistingChromeError('O Chrome mudou o perfil da nova aba. Paramos antes de navegar. Reconecte ao perfil escolhido.')
            except Exception:
                page.close()  # somente a aba vazia criada acima
                raise
        if url:
            page.goto(url, wait_until="domcontentloaded")
        return page

    def close(self) -> None:
        try:
            if self._context is not None and not self.config.attach_existing_chrome:
                self._context.close()
        finally:
            self._context = None
            self._profile_context_id = None
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
