"""Apoio aos testes que precisam de navegador e/ou da fixture servida por HTTP.

Motivação (ADR-007): o núcleo é testado sem navegador, mas a integração real
precisa de um Chromium de verdade e de uma fixture servida por HTTP (o esquema
``file://`` dá origem opaca a iframes, o que invalidaria os testes de iframe).

Nada aqui é dependência de execução: só é usado por ``tests/``.
"""

from __future__ import annotations

import os
import http.server
import socket
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"


def fixture_path(name: str = "fake_chat.html") -> Path:
    return FIXTURES_DIR / name


def file_url(name: str = "fake_chat.html", query: str = "") -> str:
    return fixture_path(name).as_uri() + query


class FixtureServer:
    """Servidor HTTP de arquivos estáticos só para a fixture (stdlib)."""

    def __init__(self, root: Path = FIXTURES_DIR) -> None:
        handler = partial(_QuietHandler, directory=str(root))
        # porta 0 -> escolhida pelo SO; evita conflito entre execuções
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    def url(self, name: str = "fake_chat.html", query: str = "") -> str:
        return f"http://127.0.0.1:{self.port}/{name}{query}"

    def start(self) -> "FixtureServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Mesmo handler, sem poluir a saída dos testes."""

    def log_message(self, fmt: str, *args) -> None:  # noqa: D102
        pass


def no_browser_reason() -> Optional[str]:
    """``None`` se o ambiente pode abrir um navegador; senão, o motivo.

    O veredito vem do ``doctor`` (bibliotecas de runtime + navegador presente),
    que é mais confiável do que tentar resolver o executável do Playwright a
    cada classe de teste.
    """
    if os.environ.get("BROWSERAPI_SKIP_BROWSER") == "1":
        return "execução explícita apenas do núcleo Python"
    from browserapi_lab.doctor import build_report

    report = build_report(results_path=tempfile.gettempdir())
    if report.browser_ready:
        return None
    if not report.playwright_installed:
        return "playwright não instalado"
    if report.missing_required_libs:
        return (
            "faltam bibliotecas de runtime do Chromium: "
            + ", ".join(report.missing_required_libs[:4])
            + ("..." if len(report.missing_required_libs) > 4 else "")
        )
    if not report.playwright_browsers and not report.system_browsers:
        return "nenhum navegador baixado (execute: python -m playwright install chromium)"
    return "ambiente sem navegador utilizável"


class BrowserTestCase(unittest.TestCase):
    """TestCase com servidor de fixture + sessão de navegador persistente.

    Pula (com motivo explícito) quando o ambiente não tem navegador — nunca
    finge sucesso.
    """

    server: FixtureServer
    session: "object"  # browserapi_lab.browser.BrowserSession
    page: "object"

    @classmethod
    def setUpClass(cls) -> None:
        reason = no_browser_reason()
        if reason and os.environ.get("BROWSERAPI_REQUIRE_BROWSER") == "1":
            raise RuntimeError(f"CI exige navegador real: {reason}")
        if reason:
            raise unittest.SkipTest(f"navegador indisponível: {reason}")
        from browserapi_lab.browser import BrowserConfig, BrowserSession

        cls.server = FixtureServer().start()
        cls.session = BrowserSession(
            BrowserConfig(
                profile=f"test-{cls.__name__.lower()}",
                profiles_root=REPO_ROOT / "profiles",
                headless=True,
            )
        )
        try:
            cls.session.start()
        except Exception as exc:  # falha real de ambiente, não "skip" por escolha
            cls.server.stop()
            raise RuntimeError(f"falha ao abrir o navegador: {type(exc).__name__}: {exc}") from exc
        cls.page = cls.session.page()
        # Esperas do Playwright (expect incluído) mais pacientes: a máquina de
        # CI às vezes está carregada e 5 s de padrão viravam falso negativo.
        cls.page.set_default_timeout(15000)

    @classmethod
    def tearDownClass(cls) -> None:
        session = getattr(cls, "session", None)
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
        server = getattr(cls, "server", None)
        if server is not None:
            server.stop()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
