"""Painel: autenticação/origem, consentimento serializado e pacote Ubuntu."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.gui import LocalServer, Panel, prepare_runtime


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('Estado esperado não foi alcançado')


class TestPanel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name) / 'configs')
        self.panel = Panel(self.store, Path(self.tmp.name) / 'data')
        self.server = LocalServer(self.panel)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.panel.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.tmp.cleanup()

    def request(self, path='/api/state', *, method='GET', token=True, origin=None, host=None, body=None, raw=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-BrowserAPI-Token'] = self.server.token if token is True else token
        if origin:
            headers['Origin'] = origin
        if host:
            headers['Host'] = host
        data = json.dumps(body).encode() if body is not None else raw
        connection.request(method, path, data, headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_auto_update_setting_is_authenticated_and_updating_blocks_tasks(self):
        from browserapi_lab.updates import UpdateStore, Updater
        store = UpdateStore(Path(self.tmp.name)/'update-data')
        self.panel.updater = Updater(store,'0.3.0',lambda:False)
        self.assertEqual(self.request('/api/updates',method='POST',token=False,body={'enabled':False})[0],403)
        self.assertTrue(store.read().get('enabled',True))
        self.assertEqual(self.request('/api/updates',method='POST',body={'enabled':False})[0],200)
        self.assertFalse(store.read()['enabled'])
        self.assertEqual(self.request('/api/updates',method='POST',body={'enabled':'false'})[0],400)
        self.assertTrue(json.loads(self.request()[2])['updates']['managed'])
        with self.panel.lock:
            self.panel.phase='updating'
        self.assertEqual(self.request('/api/task',method='POST',body={'operation':'doctor'})[0],400)

    def test_static_is_allowlisted_and_has_security_headers(self):
        code, headers, body = self.request('/', token=False)
        self.assertEqual(code, 200)
        self.assertIn(b'panel.js', body)
        self.assertNotIn(self.server.token.encode(), body)
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(self.request('/../../etc/passwd')[0], 404)
        self.assertEqual(self.request('/panel.css', token=False)[0], 200)
        self.assertEqual(self.server.server_address[0], '127.0.0.1')

    def test_favicon_public_empty_and_runtime_versioned_assets(self):
        from browserapi_lab.version import APP_VERSION
        code, _, data = self.request('/favicon.ico', token=False)
        self.assertEqual((code,data),(204,b''))
        self.assertEqual(json.loads(self.request()[2])['version'],APP_VERSION)
        for path in ('/','/panel.js'):
            body = self.request(path, token=False)[2]
            self.assertIn(APP_VERSION.encode(),body)
            self.assertNotIn(b'__BROWSERAPI_PANEL_VERSION__',body)
        self.assertEqual(self.request('/favicon.ico', host='evil.example')[0],403)

    def test_task_400_explains_reason_without_exposing_paths(self):
        code, _, body = self.request('/api/task',method='POST',body={'operation':'point_send','name':'missing'})
        self.assertEqual(code,400)
        self.assertIn('Chat salvo não encontrado',json.loads(body)['error'])
        self.assertNotIn(self.tmp.name,body.decode())
        self.store.save(ChatConfig('saved','https://example.com'))
        code, _, body = self.request('/api/task',method='POST',body={'operation':'configure','name':'saved','provider':'gemini','browser':'chrome'})
        self.assertEqual(code,400)
        self.assertIn('Nome já salvo',json.loads(body)['error'])
        with self.panel.lock:
            self.panel.phase = 'running'
        code, _, body = self.request('/api/task',method='POST',body={'operation':'doctor'})
        self.assertEqual(code,400)
        self.assertIn('operação já está em andamento',json.loads(body)['error'])

    def test_auth_host_and_origin_rejected(self):
        self.assertEqual(self.request(token=False)[0], 403)
        self.assertEqual(self.request(token='wrong')[0], 403)
        self.assertEqual(self.request(origin='https://evil.example')[0], 403)
        self.assertEqual(self.request(host='evil.example')[0], 403)
        self.assertEqual(self.request(origin=self.server.url)[0], 200)
        self.assertEqual(self.request('/api/cancel', method='POST', token=False, body={})[0], 403)
        self.assertEqual(self.request('/api/task', method='POST', origin='null', body={'operation':'doctor'})[0], 403)

    def test_payload_limits_and_invalid_fields(self):
        self.assertEqual(self.request('/api/task', method='POST', raw=b'x' * 131073)[0], 413)
        self.assertEqual(self.request('/api/task', method='POST', raw=b'not json')[0], 400)
        self.assertEqual(self.request('/api/task', method='POST', body=[])[0], 400)
        self.assertEqual(self.request('/api/task', method='POST', body={'operation':'exec'})[0], 400)
        self.assertEqual(self.request('/api/task', method='POST', body={'operation':'configure','name':'../x'})[0], 400)
        self.assertEqual(self.request('/api/task', method='POST', body={'operation':'configure','name':'x','provider':'gemini','browser':'custom'})[0], 400)
        self.assertEqual(self.request('/api/task', method='POST', body={'operation':'configure','name':'x','provider':'custom','browser':'chromium','url':'https://user:password@example.com'})[0], 400)

    def test_metrics_finish_with_task_not_stale_receipt_or_duplicate_send(self):
        self.store.save(ChatConfig('saved','https://example.com'))
        def check_once(*args, **kwargs):
            kwargs['ask']('Autoriza? [s/N] ')
            return {'status':'success','timings':{'total_ms':123},'answer':'SECRET'}
        with patch('browserapi_lab.gui.check',side_effect=check_once) as check_call:
            self.panel.submit({'operation':'check','name':'saved'})
            until(lambda:self.panel.snapshot()['prompt'])
            self.assertEqual(self.panel.snapshot()['telemetry']['sources']['saved']['state'],'busy')
            self.panel.reply(self.panel.snapshot()['prompt']['id'],'s')
            until(lambda:self.panel.snapshot()['phase']=='done')
            state = self.panel.snapshot()['telemetry']
            self.assertEqual(state['requests'],1)
            self.assertGreater(state['history'][0]['timings']['manual_wait_ms'],0)
            check_call.assert_called_once()
        self.panel.submit({'operation':'doctor'})
        until(lambda:self.panel.snapshot()['phase']=='done')
        state = self.panel.snapshot()['telemetry']
        self.assertEqual(state['operations'],2)
        self.assertEqual(state['requests'],1)
        self.assertIsNone(state['history'][-1]['status'])
        self.assertNotIn('SECRET',json.dumps(state))
        with patch('browserapi_lab.gui.check',side_effect=RuntimeError('SECRET')):
            self.panel.submit({'operation':'check','name':'saved'})
            until(lambda:self.panel.snapshot()['phase']=='error')
        state = self.panel.snapshot()['telemetry']
        self.assertEqual(state['operation_errors'],1)
        self.assertEqual(state['requests'],1)
        self.assertEqual(state['sources']['saved']['state'],'needs_attention')
        self.assertNotIn('SECRET',json.dumps(state))

    def test_prompt_unique_reply_once_and_cancel(self):
        result = []
        worker = threading.Thread(target=lambda: result.append(self.panel.ask('Autoriza? [s/N] ')))
        worker.start()
        until(lambda: self.panel.snapshot()['prompt'])
        identifier = self.panel.snapshot()['prompt']['id']
        self.assertEqual(self.panel.snapshot()['prompt']['kind'], 'yesno')
        with self.assertRaises(ValueError):
            self.panel.reply('old', 's')
        with self.assertRaises(ValueError):
            self.panel.reply(identifier, 'yes')
        self.panel.reply(identifier, 'n')
        worker.join(2)
        self.assertEqual(result, ['n'])
        with self.assertRaises(ValueError):
            self.panel.reply(identifier, 's')
        cancelled = []
        def waiting():
            try:
                self.panel.ask('Continue')
            except EOFError:
                cancelled.append(True)
        worker = threading.Thread(target=waiting)
        worker.start()
        until(lambda: self.panel.snapshot()['prompt'])
        self.panel.cancel()
        worker.join(2)
        self.assertEqual(cancelled, [True])

    def test_prepare_runs_once_off_http_thread_and_cancels(self):
        started = threading.Event()
        finished = threading.Event()
        def installer(_path, tell, cancelled):
            self.assertNotEqual(threading.current_thread(), threading.main_thread())
            started.set()
            until(cancelled)
            finished.set()
            raise EOFError()
        self.panel.installer = installer
        self.panel.submit({'operation':'prepare'})
        self.assertTrue(started.wait(2))
        with self.assertRaises(ValueError):
            self.panel.submit({'operation':'prepare'})
        self.panel.cancel()
        self.assertTrue(finished.wait(2))
        until(lambda: self.panel.phase == 'cancelled')
        self.assertIn('não desfaz', '\n'.join(self.panel.snapshot()['messages']))

    def test_switch_existing_saved_chat_never_launches_and_requires_consent(self):
        self.store.save(ChatConfig('saved','https://example.com'))
        with patch('browserapi_lab.browser.BrowserSession.start') as launch:
            for reply, expected in (('n','dedicated'),('s','existing_chrome')):
                self.panel.submit({'operation':'use_existing','name':'saved'})
                until(lambda: self.panel.snapshot()['prompt'])
                self.panel.reply(self.panel.snapshot()['prompt']['id'],reply)
                until(lambda: self.panel.phase == 'done')
                self.assertEqual(self.store.load('saved').session_mode,expected)
            self.assertEqual(self.store.load('saved').browser,'chrome')
            launch.assert_not_called()

    def test_configure_uses_form_and_rejects_overwrite(self):
        def fake_configure(store, name, **kwargs):
            config = kwargs['initial_config']
            self.assertEqual(config.browser, 'chromium')
            self.assertEqual(config.provider, 'gemini')
            store.save(config)
            return {'compatible_in_this_run':False}
        with patch('browserapi_lab.gui.configure', side_effect=fake_configure):
            self.panel.submit({'operation':'configure','name':'chat','provider':'gemini','browser':'chromium'})
            until(lambda: self.panel.phase == 'done')
        with self.assertRaises(ValueError):
            self.panel.submit({'operation':'configure','name':'chat','provider':'gemini','browser':'chrome'})
        self.assertEqual(self.store.load('chat').browser, 'chromium')

    def test_backend_errors_are_sanitized_and_no_retry(self):
        self.store.save(ChatConfig('chat','https://example.com'))
        with patch('browserapi_lab.gui.check', side_effect=RuntimeError('SECRET password cookie')) as operation:
            self.panel.submit({'operation':'check','name':'chat'})
            until(lambda: self.panel.phase == 'error')
            self.assertEqual(operation.call_count, 1)
        self.assertNotIn('SECRET', json.dumps(self.panel.snapshot()))

    def test_install_refuses_root_and_low_disk_before_spawning(self):
        with patch('browserapi_lab.gui.os.geteuid', return_value=0), patch('browserapi_lab.gui.subprocess.Popen') as spawn:
            with self.assertRaises(RuntimeError):
                prepare_runtime(Path(self.tmp.name) / 'install', lambda _:None, lambda:False)
            spawn.assert_not_called()
        with patch('browserapi_lab.gui.os.geteuid', return_value=1000), patch('browserapi_lab.gui.shutil.disk_usage', return_value=type('Disk', (), {'free':0})()), patch('browserapi_lab.gui.subprocess.Popen') as spawn:
            with self.assertRaises(RuntimeError):
                prepare_runtime(Path(self.tmp.name) / 'install', lambda _:None, lambda:False)
            spawn.assert_not_called()


@unittest.skipUnless(shutil.which('dpkg-deb'), 'dpkg-deb não disponível')
class TestUbuntuPackage(unittest.TestCase):
    def test_build_extract_assets_and_import_outside_checkout(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'BrowserAPI-Ubuntu.deb'
            subprocess.run([sys.executable, str(root/'scripts/build_deb.py'), '--output', str(target)], check=True, capture_output=True)
            deps = subprocess.check_output(['dpkg-deb','--field',str(target),'Depends'], text=True)
            self.assertIn('python3 (>= 3.11)', deps)
            self.assertIn('python3-venv', deps)
            contents = subprocess.check_output(['dpkg-deb','--ctrl-tarfile',str(target)])
            self.assertNotIn(b'postinst', contents)
            self.assertNotIn(b'preinst', contents)
            destination = Path(tmp) / 'extract'
            subprocess.run(['dpkg-deb','--extract',str(target),str(destination)],check=True)
            share = destination / 'usr/share/browserapi-lab'
            for name in ('panel.html','panel.css','panel.js','picker.js','chat_probe.js'):
                self.assertTrue((share/'browserapi_lab/assets'/name).is_file(), name)
            desktop = (destination/'usr/share/applications/browserapi-lab.desktop').read_text()
            self.assertIn('Terminal=false', desktop)
            self.assertIn('Exec=/usr/bin/browserapi-window', desktop)
            launcher = destination/'usr/bin/browserapi-window'
            self.assertTrue(os.access(launcher, os.X_OK))
            env = dict(os.environ)
            env.pop('PYTHONPATH',None)
            process = subprocess.run([sys.executable, str(share/'open_window.py'), '--help'], cwd=tmp, env=env, text=True, capture_output=True)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertIn('Ubuntu',process.stdout)
