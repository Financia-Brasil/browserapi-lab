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
        self._proof_page: Any = None
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
                self._start_attached(started)
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

    # -------------------------------------------------- Chrome já aberto
    @staticmethod
    def _pump(ctx: Any, milliseconds: int = 250) -> None:
        """Deixar o Playwright processar eventos sem ler ou alterar abas pessoais.

        ``time.sleep`` não atualiza ``ctx.pages`` na API síncrona; esperar um
        evento de página processa as mensagens do Chrome.
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        try:
            ctx.wait_for_event('page', timeout=milliseconds)
        except PlaywrightTimeout:
            pass

    def _start_attached(self, started: float) -> None:
        """Conectar, provar o perfil recebido e só então liberar o chat.

        O endpoint consentido identifica a instalação, não o perfil. O Playwright
        agrupa abas de todos os perfis no contexto padrão, então cada passo abaixo
        usa a identidade CDP real (browserContextId) da aba que nós pedimos.
        """
        from .existing_chrome import ExistingChromeError, ProofPage, endpoint, verify_profile
        from .profiles import installation_root, open_profile, profile_name
        installation = self.config.existing_installation
        if not self.config.existing_profile:
            raise ExistingChromeError('Escolha um perfil na lista antes de conectar. Não assumimos que o Chrome concedeu a conta desejada.')
        directory = profile_name(self.config.existing_profile)
        # Falhar aqui não deixa nenhuma aba aberta no navegador pessoal.
        address = endpoint() if installation == 'chrome' else endpoint(installation=installation)
        self._attached_browser = self._pw.chromium.connect_over_cdp(address, timeout=60000)
        contexts = self._attached_browser.contexts
        if len(contexts) != 1:
            raise ExistingChromeError('A conexão não identificou um único contexto do Chrome. Desconectamos sem fechar seu navegador.')
        ctx = contexts[0]
        # Pedido nativo ao processo existente (sem cópia nem novo user_data_dir). O Chrome só
        # aceita http(s) em pedidos de linha de comando: a aba de prova é uma página local
        # com código único no caminho, que distingue a nossa aba de todas as pessoais.
        with ProofPage() as proof:
            open_profile(installation + ':' + directory, proof.url)
            deadline = time.monotonic() + 20
            probe = None
            while probe is None:
                probe = next((p for p in list(ctx.pages) if p.url == proof.url), None)
                if probe is None:
                    if time.monotonic() >= deadline:
                        raise ExistingChromeError(
                            'O Chrome não abriu a verificação do perfil escolhido. Nenhum chat foi aberto ou preenchido. '
                            'Abra esse perfil pelo avatar do Chrome, confira a Depuração remota e reconecte. '
                            'Se continuar, esta versão do Chrome não permite escolher esse perfil por este modo.')
                    self._pump(ctx)
            # A aba de prova NÃO é fechada aqui: ela vira a aba do chat em page(). Fechar a única
            # janela de um perfil logo antes de abrir o chat derrubou o perfil no Chrome 156.
            self._profile_context_id = verify_profile(
                ctx, installation_root(installation) / directory, probe=probe, keep_probe=True)
            self._proof_page = probe
        self._context = ctx
        self._context.set_default_timeout(self.config.timeout_ms)
        self._cold_start_ms = (time.perf_counter() - started) * 1000

    def _open_chat_natively(self, ctx: Any, url: str) -> Any:
        """Abrir o chat no perfil escolhido pelo próprio Chrome, não por createTarget.

        ``Target.createTarget`` usa o perfil usado por último; o pedido nativo
        com --profile-directory usa o perfil que o usuário escolheu.
        """
        from .existing_chrome import ExistingChromeError, target_context_id
        from .profiles import open_profile
        before = list(ctx.pages)
        open_profile(self.config.existing_installation + ':' + self.config.existing_profile, url)
        identity: Dict[Any, str] = {}  # uma identidade por aba; ela nunca muda
        deadline = time.monotonic() + 20
        while True:
            mine = []
            for candidate in list(ctx.pages):
                if candidate in before or not candidate.url.startswith(('http://', 'https://')):
                    continue
                if candidate not in identity:
                    identity[candidate] = target_context_id(ctx, candidate)
                if identity[candidate] == self._profile_context_id:
                    mine.append(candidate)
            if len(mine) > 1:
                raise ExistingChromeError('O Chrome abriu mais de uma aba nova no perfil escolhido. Nenhuma foi fechada nem usada; confira o navegador e tente de novo.')
            if mine:
                break
            if time.monotonic() >= deadline:
                raise ExistingChromeError('O Chrome não abriu o chat no perfil escolhido a tempo. Nenhuma mensagem foi enviada; confira o perfil aberto e tente de novo.')
            self._pump(ctx)
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        try:
            mine[0].wait_for_load_state('domcontentloaded', timeout=self.config.timeout_ms)
        except PlaywrightTimeout:
            pass  # a verificação de origem/campos fala por si; não recarregar
        return mine[0]

    def _release_proof(self) -> None:
        """Fechar a aba de prova (nossa) quando ela não for virar a aba do chat."""
        proof, self._proof_page = self._proof_page, None
        if proof is not None:
            try:
                proof.close()
            except Exception:
                pass

    def _verified(self, page: Any) -> Any:
        """Marcar somente abas obtidas por esta sessão já verificada."""
        try:
            page._browserapi_verified_profile = self.config.existing_profile
        except Exception:
            pass
        return page

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
            from .config import origin, safe_url
            from .existing_chrome import ExistingChromeError, target_context_id
            if not url:
                raise ValueError('Informe o chat escolhido antes de acessar abas pessoais.')
            if not self._profile_context_id:
                raise ExistingChromeError('O perfil desta conexão não foi verificado. Reconecte antes de acessar o chat.')
            matches = [p for p in pages if p.url.startswith(('http://', 'https://'))
                       and origin(p.url) == origin(url)
                       and target_context_id(ctx, p) == self._profile_context_id]
            if len(matches) > 1:
                raise ExistingChromeError('Mais de uma aba do chat está aberta neste perfil. Deixe somente uma para conectar; nenhuma aba foi fechada pelo programa.')
            if matches:
                self._release_proof()  # o perfil já tem janela com o chat
                return self._verified(matches[0])
            safe_url(url)
            proof = self._proof_page
            if proof is not None and not proof.is_closed():
                # A aba de prova é nossa e já está no perfil confirmado: vira a aba do chat.
                # Se a navegação falhar ela continua registrada e close() a encerra.
                proof.goto(url, wait_until='domcontentloaded')
                self._proof_page = None
                return self._verified(proof)
            # Falha de navegação é informada, nunca repetida em outra aba/perfil.
            return self._verified(self._open_chat_natively(ctx, url))
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
            self._release_proof()
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
