"""Testes de sessão (Marco 2) que **não** precisam de navegador.

Cobrem: sanitização de perfis, lock (mesmo processo e entre processos) e
sanitização de estado exportado (ADR-009).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from browserapi_lab.session import (
    MARKER_KEY,
    ProfileBusyError,
    ProfileLock,
    assert_no_private_values,
    ensure_profile,
    is_sensitive_key,
    profile_path,
    read_lock_info,
    sanitize_storage_state,
    supports_indexeddb_export,
)

ROOT = str(Path(__file__).resolve().parent.parent)


class TestProfilePath(unittest.TestCase):
    def test_padrao(self):
        self.assertEqual(profile_path("default", "/tmp/p"), Path("/tmp/p/default"))

    def test_nome_com_espaco_e_sanitizado(self):
        self.assertEqual(profile_path("meu perfil", "/tmp/p"), Path("/tmp/p/meuperfil"))

    def test_nao_escapa_do_root(self):
        alvo = profile_path("../escape", "/tmp/p")
        self.assertTrue(str(alvo).startswith("/tmp/p/"))
        self.assertNotIn("..", str(alvo))

    def test_nome_vazio_ou_ponto(self):
        self.assertEqual(profile_path("...", "/tmp/p"), Path("/tmp/p/default"))

    def test_ensure_profile_cria_diretorio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = ensure_profile("novo", Path(tmp))
            self.assertTrue(path.is_dir())


class TestProfileLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = Path(self.tmp.name) / "perfil"

    def tearDown(self):
        self.tmp.cleanup()

    def test_adquire_e_libera(self):
        lock = ProfileLock(self.profile)
        lock.acquire()
        self.assertTrue(lock.lock_path.exists())
        info = read_lock_info(lock.lock_path)
        self.assertEqual(info["pid"], os.getpid())
        lock.release()
        # reliberar é seguro (idempotente)
        lock.release()

    def test_segundo_lock_no_mesmo_perfil_falha(self):
        primeiro = ProfileLock(self.profile)
        primeiro.acquire()
        try:
            segundo = ProfileLock(self.profile)
            with self.assertRaises(ProfileBusyError) as ctx:
                segundo.acquire()
            self.assertIn("perfil em uso", str(ctx.exception))
            self.assertIn(str(os.getpid()), str(ctx.exception))
        finally:
            primeiro.release()

    def test_readquire_apos_liberar(self):
        primeiro = ProfileLock(self.profile)
        primeiro.acquire()
        primeiro.release()
        segundo = ProfileLock(self.profile)
        segundo.acquire()
        segundo.release()

    def test_lock_entre_processos(self):
        """O lock real é entre processos: é o cenário que corrompe perfil."""
        primeiro = ProfileLock(self.profile)
        primeiro.acquire()
        try:
            codigo = (
                "import sys; sys.path.insert(0, %r)\n"
                "from browserapi_lab.session import ProfileLock, ProfileBusyError\n"
                "lock = ProfileLock(%r)\n"
                "try:\n"
                "    lock.acquire()\n"
                "except ProfileBusyError as exc:\n"
                "    print('BUSY'); sys.exit(0)\n"
                "print('LIVRE'); sys.exit(1)\n" % (ROOT, str(self.profile))
            )
            proc = subprocess.run(
                [sys.executable, "-c", codigo], capture_output=True, text=True, timeout=60
            )
            self.assertEqual(proc.stdout.strip(), "BUSY", proc.stderr)
            self.assertEqual(proc.returncode, 0)
        finally:
            primeiro.release()

    def test_context_manager(self):
        with ProfileLock(self.profile) as lock:
            self.assertIsNotNone(lock.handle)
        self.assertIsNone(lock.handle)


class TestSanitizacao(unittest.TestCase):
    def test_remove_valores_de_cookies(self):
        bruto = {
            "cookies": [
                {"name": "sessionid", "value": "abc123super secreto", "domain": ".exemplo.com"},
                {"name": "tema", "value": "escuro", "domain": ".exemplo.com"},
            ],
            "origins": [
                {
                    "origin": "https://exemplo.com",
                    "localStorage": [
                        {"name": "auth_token", "value": "Bearer zzz"},
                        {"name": "ultimo_modelo", "value": "gemini"},
                    ],
                    "indexedDB": [{"name": "chat-db"}],
                }
            ],
        }
        limpo = sanitize_storage_state(bruto)
        serializado = json.dumps(limpo, ensure_ascii=False)
        for segredo in ("abc123super secreto", "Bearer zzz", "escuro", "gemini"):
            self.assertNotIn(segredo, serializado)

        self.assertEqual(limpo["cookie_count"], 2)
        self.assertEqual(limpo["cookie_domains"][".exemplo.com"]["count"], 2)
        self.assertIn("sessionid", limpo["cookie_domains"][".exemplo.com"]["sensitive_names"])
        origem = limpo["origins"][0]
        self.assertEqual(origem["local_storage_keys"], ["auth_token", "ultimo_modelo"])
        self.assertEqual(origem["local_storage_sensitive"], ["auth_token"])
        self.assertEqual(origem["indexed_db_databases"], ["chat-db"])

    def test_estado_vazio(self):
        limpo = sanitize_storage_state({})
        self.assertEqual(limpo["cookie_count"], 0)
        self.assertEqual(limpo["origins"], [])

    def test_detecta_chaves_sensiveis(self):
        for chave in ("auth_token", "Authorization", "session_id", "apiKey", "senha"):
            self.assertTrue(is_sensitive_key(chave), chave)
        for chave in ("tema", "ultimo_modelo", "layout"):
            self.assertFalse(is_sensitive_key(chave), chave)

    def test_assert_no_private_values(self):
        with self.assertRaises(ValueError):
            assert_no_private_values({"authorization": "Bearer 123"})
        with self.assertRaises(ValueError):
            assert_no_private_values({"nested": [{"token": "abc"}]})
        assert_no_private_values({"authorization": None})
        assert_no_private_values({"token_count": 3})  # nome sensível, mas é contagem

    def test_marcador_constante(self):
        self.assertEqual(MARKER_KEY, "browserapi-lab.marker")


class TestApiDoPlaywright(unittest.TestCase):
    def test_suporta_exportacao_indexeddb_quando_instalado(self):
        """Não assumimos a API: verificamos a assinatura instalada (briefing)."""
        try:
            import playwright  # noqa: F401
        except Exception:
            self.skipTest("playwright não instalado neste interpretador")
        self.assertTrue(supports_indexeddb_export())

    def test_sem_playwright_nao_quebra(self):
        # A função deve devolver False em vez de estourar quando não há playwright.
        self.assertIsInstance(supports_indexeddb_export(), bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
