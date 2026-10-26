"""Testes de navegador e sessão (Marco 2) — exigem Chromium real.

No sandbox de desenvolvimento não há bibliotecas de runtime do Chromium, então
estes testes são pulados com motivo explícito e executados no CI (ADR-007).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from browserapi_lab.browser import (
    BrowserConfig,
    BrowserSession,
    browser_tree_rss_kb,
    chromium_available,
    tree_rss_kb,
)
from browserapi_lab.session import (ProfileBusyError, set_marker, read_marker,
                                    set_marker_indexeddb, read_marker_indexeddb, export_state)

from _harness import BrowserTestCase, FixtureServer, REPO_ROOT, file_url, no_browser_reason


class TestRss(unittest.TestCase):
    """Leitura de /proc — roda sem navegador."""

    def test_rss_do_proprio_processo(self):
        valor = tree_rss_kb(os.getpid())
        self.assertIsNotNone(valor)
        self.assertGreater(valor, 0)

    def test_pid_inexistente(self):
        self.assertIsNone(tree_rss_kb(999999))


class TestSessao(BrowserTestCase):
    def test_abre_e_fecha(self):
        self.assertIsNotNone(self.session.context)
        self.assertGreater(self.session.cold_start_ms, 0)
        paginas = self.session.context.pages
        self.assertGreaterEqual(len(paginas), 1)

    def test_aba_quente_e_reutilizada(self):
        url = self.server.url("fake_chat.html")
        primeira = self.session.page(url)
        segunda = self.session.page(url)
        self.assertIs(primeira, segunda)

    def test_persistencia_apos_fechamento(self):
        """E-SESS-1: o perfil sobrevive a fechar e reabrir."""
        url = self.server.url("fake_chat.html")
        page = self.session.page(url)
        marcador = set_marker(page, "marker-persistencia-001")
        self.assertEqual(read_marker(page), marcador)
        set_marker_indexeddb(page, marcador)
        self.assertEqual(read_marker_indexeddb(page), marcador)
        import json
        self.assertNotIn(marcador, json.dumps(export_state(self.session.context)))

        perfil = self.session.config.profile
        self.session.close()

        reaberta = BrowserSession(
            BrowserConfig(profile=perfil, profiles_root=REPO_ROOT / "profiles", headless=True)
        )
        try:
            reaberta.start()
            page2 = reaberta.page(url)
            self.assertEqual(read_marker(page2), marcador, "marcador não sobreviveu ao reinício")
            self.assertEqual(read_marker_indexeddb(page2), marcador, "IndexedDB não persistiu")
        finally:
            reaberta.close()

        # sessão da classe foi fechada no teste: recria para o tearDownClass
        type(self).session = BrowserSession(
            BrowserConfig(profile=perfil, profiles_root=REPO_ROOT / "profiles", headless=True)
        )
        self.session.start()
        type(self).page = self.session.page()

    def test_segundo_processo_e_recusado(self):
        """E-SESS-3: nunca dois processos no mesmo user_data_dir."""
        perfil = self.session.config.profile
        profiles_root = self.session.config.profiles_root
        codigo = (
            "import sys; sys.path.insert(0, %r)\n"
            "from browserapi_lab.browser import BrowserSession, BrowserConfig\n"
            "from browserapi_lab.session import ProfileBusyError\n"
            "s = BrowserSession(BrowserConfig(profile=%r, profiles_root=%r, headless=True))\n"
            "try:\n"
            "    s.start()\n"
            "except ProfileBusyError as exc:\n"
            "    print('BUSY'); sys.exit(0)\n"
            "except Exception as exc:\n"
            "    print('OTHER: %%s' %% exc); sys.exit(3)\n"
            "print('SEM-LOCK'); sys.exit(4)\n" % (str(REPO_ROOT), perfil, str(profiles_root))
        )
        proc = subprocess.run(
            [sys.executable, "-c", codigo], capture_output=True, text=True, timeout=180
        )
        self.assertEqual(proc.stdout.strip(), "BUSY", proc.stderr[-2000:])

    def test_arvore_de_processos_tem_rss(self):
        page = self.session.page(self.server.url("fake_chat.html"))
        page.wait_for_timeout(200)
        rss = browser_tree_rss_kb(self.session)
        self.assertIsNotNone(rss)
        self.assertGreater(rss, 0)


class TestDeteccaoDeAmbiente(unittest.TestCase):
    def test_chromium_available_e_boleano(self):
        self.assertIsInstance(chromium_available(), bool)

    def test_motivo_quando_indisponivel(self):
        if chromium_available():
            self.skipTest("há navegador neste ambiente")
        motivo = no_browser_reason()
        self.assertIsInstance(motivo, str)
        self.assertTrue(motivo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
