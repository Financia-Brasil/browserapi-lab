"""Depuração configurada uma vez: porta fixa, atalho e reabertura.

Nada aqui abre navegador de verdade: o "Chrome" é um servidor HTTP local que
responde ``/json/version`` como o Chrome responde.
"""
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

from browserapi_lab import persistent_chrome as pc


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class FakeDevTools:
    """Servidor que fala o mínimo do Chrome para descoberta de porta."""

    def __init__(self, port=0, payload=None, status=200, path='/devtools/browser/abc-123'):
        self.payload = payload
        self.url_path = path
        self.status = status
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - API do http.server
                body = json.dumps(outer.payload).encode()
                self.send_response(outer.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.port = self.server.server_address[1]
        if self.payload is None:
            self.payload = {'Browser': 'Chrome/144.0',
                            'webSocketDebuggerUrl': f'ws://127.0.0.1:{self.port}{self.url_path}'}

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc_info):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class TestProbe(unittest.TestCase):
    def test_porta_do_chrome_e_reconhecida(self):
        with FakeDevTools() as fake:
            address = pc.probe(fake.port)
        self.assertEqual(address, f'ws://127.0.0.1:{fake.port}/devtools/browser/abc-123')

    def test_porta_fechada_nao_quebra_nada(self):
        self.assertIsNone(pc.probe(free_port(), timeout=0.2))

    def test_endereco_que_nao_e_loopback_e_recusado(self):
        with FakeDevTools() as fake:
            fake.payload = {'webSocketDebuggerUrl': 'ws://10.0.0.5:9222/devtools/browser/abc'}
            self.assertIsNone(pc.probe(fake.port, timeout=1))

    def test_caminho_fora_do_padrao_e_recusado(self):
        with FakeDevTools(path='/qualquer/coisa') as fake:
            self.assertIsNone(pc.probe(fake.port, timeout=1))

    def test_resposta_nao_json_ou_erro_nao_viram_endpoint(self):
        with FakeDevTools(payload={'nada': 'aqui'}) as fake:
            self.assertIsNone(pc.probe(fake.port, timeout=1))
        with FakeDevTools(status=500) as fake:
            self.assertIsNone(pc.probe(fake.port, timeout=1))

    def test_porta_invalida_nem_tenta(self):
        for value in (0, -1, 70000, '9222', None):
            self.assertIsNone(pc.probe(value))


class TestAtalho(unittest.TestCase):
    def test_atalho_abre_o_chrome_certo(self):
        script = pc.launcher_script('/usr/bin/google-chrome', '/home/u/.config/google-chrome', 9222)
        self.assertTrue(script.startswith('#!/bin/sh'))
        self.assertIn('exec /usr/bin/google-chrome', script)
        self.assertIn('--remote-debugging-port=9222', script)
        self.assertIn('--remote-debugging-address=127.0.0.1', script)
        self.assertIn('--user-data-dir=/home/u/.config/google-chrome', script)
        self.assertIn('--no-first-run', script)
        self.assertIn('"$@"', script)

    def test_caminho_com_espaco_fica_entre_aspas(self):
        script = pc.launcher_script('/opt/Meu Chrome/chrome', '/home/u/Dados do Chrome', 9333)
        self.assertIn("'/opt/Meu Chrome/chrome'", script)
        self.assertIn("'/home/u/Dados do Chrome'", script)

    def test_entrada_de_aplicativo_e_valida(self):
        entry = pc.desktop_entry(Path('/home/u/.local/bin/browserapi-chrome-debug'), 9222)
        self.assertIn('[Desktop Entry]', entry)
        self.assertIn('Type=Application', entry)
        self.assertIn('Exec=/home/u/.local/bin/browserapi-chrome-debug %U', entry)
        self.assertNotIn('%%', entry)

    def test_entrada_de_aplicativo_escapa_caminho_com_espaco(self):
        entry = pc.desktop_entry(Path('/home/u/meus apps/atalho'), 9222)
        self.assertIn('Exec="/home/u/meus apps/atalho" %U', entry)


class TestInstall(unittest.TestCase):
    def test_cria_atalhos_executaveis_e_idempotente(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = pc.install('/usr/bin/google-chrome', '/home/u/.config/google-chrome',
                               port=9222, root=root)
            self.assertTrue(first['launcher'].is_file())
            self.assertTrue(first['desktop'].is_file())
            self.assertEqual(stat.S_IMODE(os.stat(first['launcher']).st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(os.stat(first['desktop']).st_mode), 0o644)
            content = first['launcher'].read_text()
            # Rodar de novo com outra porta reescreve o mesmo atalho.
            second = pc.install('/usr/bin/google-chrome', '/home/u/.config/google-chrome',
                                port=9333, root=root)
            self.assertEqual(first['launcher'], second['launcher'])
            self.assertEqual(second['launcher'].read_text(),
                             content.replace('9222', '9333'))
            # Nada de sobra .new por aí.
            self.assertEqual(list(first['launcher'].parent.glob('*.new')), [])

    def test_porta_invalida_e_recusada(self):
        with tempfile.TemporaryDirectory() as tmp:
            for port in (80, 0, 70000, '9222'):
                with self.assertRaises(pc.PersistentChromeError):
                    pc.install('/usr/bin/google-chrome', '/tmp/x', port=port, root=Path(tmp))

    def test_sem_executavel_diz_o_que_fazer(self):
        with self.assertRaises(pc.PersistentChromeError) as caught:
            pc.install('', '/tmp/x', root=Path('/tmp'))
        self.assertIn('executável do Chrome', str(caught.exception))

    def test_nao_sobrescreve_link_simbolico(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'fora'
            target.write_text('não mexa')
            launcher_dir = root / 'bin'
            launcher_dir.mkdir()
            (launcher_dir / pc.LAUNCHER_NAME).symlink_to(target)
            with self.assertRaises(pc.PersistentChromeError):
                pc.install('/usr/bin/google-chrome', '/tmp/x', root=root)
            self.assertEqual(target.read_text(), 'não mexa')


class TestStartEEnsure(unittest.TestCase):
    def test_start_reaproveita_quem_ja_esta_na_porta(self):
        with FakeDevTools() as fake:
            address = pc.start('/usr/bin/google-chrome', '/tmp/x', port=fake.port)
            self.assertEqual(address, f'ws://127.0.0.1:{fake.port}/devtools/browser/abc-123')

    def test_start_monta_a_linha_de_comando_certa(self):
        port = free_port()
        with patch('browserapi_lab.persistent_chrome.subprocess.Popen') as popen, \
             patch('browserapi_lab.persistent_chrome.probe', side_effect=[None, None,
                                                                         'ws://127.0.0.1:1/devtools/browser/x']):
            with tempfile.TemporaryDirectory() as tmp:
                address = pc.start('/usr/bin/google-chrome', Path(tmp) / 'dados', port=port,
                                   timeout=5)
        self.assertTrue(address.endswith('/devtools/browser/x'))
        command = popen.call_args.args[0]
        self.assertEqual(command[0], '/usr/bin/google-chrome')
        self.assertIn(f'--remote-debugging-port={port}', command)
        self.assertIn('--remote-debugging-address=127.0.0.1', command)
        self.assertTrue(any(arg.startswith('--user-data-dir=') for arg in command))
        self.assertTrue(popen.call_args.kwargs['start_new_session'])

    def test_start_que_nao_abre_explica_e_nao_inventa(self):
        with patch('browserapi_lab.persistent_chrome.subprocess.Popen'), \
             patch('browserapi_lab.persistent_chrome.probe', return_value=None):
            with self.assertRaises(pc.PersistentChromeError) as caught:
                pc.start('/usr/bin/google-chrome', '/tmp/x', port=find_free_port(),
                         timeout=0.4)
        self.assertIn('não respondeu', str(caught.exception))

    def test_ensure_sem_autorizacao_nao_abre_nada(self):
        with patch('browserapi_lab.persistent_chrome.probe', return_value=None), \
             patch('browserapi_lab.persistent_chrome.start') as start, \
             patch('browserapi_lab.existing_chrome.endpoint',
                   side_effect=__import__('browserapi_lab.existing_chrome',
                                          fromlist=['ExistingChromeError']).ExistingChromeError('sem sessão')):
            with self.assertRaises(pc.PersistentChromeError) as caught:
                pc.ensure(9222, executable='/usr/bin/google-chrome', user_data_dir='/tmp/x',
                          auto_launch=False)
        start.assert_not_called()
        self.assertIn('Configurar uma vez', str(caught.exception))

    def test_ensure_com_autorizacao_abre_o_chrome(self):
        with patch('browserapi_lab.persistent_chrome.probe', return_value=None), \
             patch('browserapi_lab.persistent_chrome.start',
                   return_value='ws://127.0.0.1:9222/devtools/browser/abc') as start:
            found = pc.ensure(9222, executable='/usr/bin/google-chrome',
                              user_data_dir='/tmp/x', auto_launch=True)
        start.assert_called_once()
        self.assertEqual(found['source'], 'aberto agora na porta 9222')

    def test_ensure_usa_porta_configurada_antes_da_sessao(self):
        with FakeDevTools() as fake:
            found = pc.ensure(fake.port)
        self.assertIn('porta', found['source'])
        self.assertEqual(found['port'], fake.port)


def find_free_port():
    return free_port()
