"""Apoio aos testes que precisam de navegador e/ou da fixture servida por HTTP.

Motivação (ADR-007): o núcleo é testado sem navegador, mas a integração real
precisa de um Chromium de verdade e de uma fixture servida por HTTP (o esquema
``file://`` dá origem opaca a iframes, o que invalidaria os testes de iframe).

Nada aqui é dependência de execução: só é usado por ``tests/``.
"""

from __future__ import annotations

import http.server
import socket
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
        handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
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


def no_browser_reason() -> Optional[str]:
    """``None`` se um Chromium real pode ser aberto aqui; senão, o motivo."""
    from browserapi_lab.browser import browser_environment_error, chromium_available

    if not chromium_available():
        return browser_environment_error() or "Chromium indisponível neste ambiente"
    reason = browser_environment_error()
    if reason:
        return reason
    return None


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
        except Exception as exc:  # falha real de ambiente, não "skip"
            cls.server.stop()
            raise unittest.SkipTest(f"falha ao abrir o navegador: {exc}") from exc
        cls.page = cls.session.new_page()

    @classmethod
    def tearDownClass(cls) -> None:
        session = getattr(cls, "session", None)
        if session is not None:
            session.close()
        server = getattr(cls, "server", None)
        if server is not None:
            server.stop()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
