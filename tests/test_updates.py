"""Atualização com dados sintéticos, sem executar downloads da internet."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import http.client
import unittest
from unittest.mock import patch, Mock
import zipfile

from browserapi_lab.updates import UpdateStore, Updater, candidate, version
from browserapi_lab import bootstrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from build_release import bundle
from publish_release import next_version


def manifest(raw,v='0.3.1'):
    return {'schema':1,'abi':1,'version':v,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'python_min':[3,11],'playwright':'1.64.1'}


class TestUpdates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = UpdateStore(self.tmp.name)
        self.raw = bundle('0.3.1')
        self.meta = manifest(self.raw)
        self.calls = []
        def fetch(path):
            self.calls.append(path)
            if path=='/releases/latest':
                return {'tag_name':'v0.3.1','draft':False,'prerelease':False}
            if path=='/git/ref/tags/v0.3.1':
                return {'object':{'type':'commit','sha':'a'*40}}
            if path.startswith('/contents/'):
                body = json.dumps(self.meta).encode() if 'update.json' in path else self.raw
                return {'encoding':'base64','content':base64.b64encode(body).decode()}
            raise AssertionError(path)
        self.fetch = fetch

    def tearDown(self):
        self.tmp.cleanup()

    def test_release_commit_pin_hash_and_all_browser_assets(self):
        meta,sha = candidate(self.fetch)
        self.assertEqual(sha,'a'*40)
        self.assertIn('?ref='+sha,self.calls[-1])
        self.store.stage(meta,self.raw)
        target = self.store.directory('0.3.1')
        for asset in (ROOT/'browserapi_lab/assets').iterdir():
            self.assertTrue((target/'browserapi_lab/assets'/asset.name).is_file(),asset.name)
        self.assertEqual(self.store.read()['pending'],'0.3.1')
        self.assertIsNone(self.store.read().get('active'))
        env = dict(os.environ,PYTHONPATH=str(target))
        child = subprocess.run([sys.executable,'-c','from browserapi_lab.version import APP_VERSION; from browserapi_lab.gui import Panel; print(APP_VERSION)'],
                               env=env,cwd=self.tmp.name,text=True,capture_output=True,timeout=10)
        self.assertEqual(child.returncode,0,child.stderr)
        self.assertEqual(child.stdout.strip(),'0.3.1')

    def test_corrupt_bundle_and_incompatible_abi_never_activate(self):
        with self.assertRaises(ValueError):
            self.store.stage(self.meta,self.raw+b'corrupt')
        self.meta['abi']=2
        with self.assertRaises(ValueError):
            candidate(self.fetch)
        self.assertIsNone(self.store.read().get('pending'))

    def test_traversal_symlink_and_missing_assets_rejected(self):
        for name,mode in (('../evil.py',0o100644),('browserapi_lab/assets/link.js',0o120777)):
            memory = io.BytesIO()
            with zipfile.ZipFile(memory,'w') as output, zipfile.ZipFile(io.BytesIO(self.raw)) as original:
                for entry in original.infolist():
                    output.writestr(entry,original.read(entry))
                info = zipfile.ZipInfo(name)
                info.external_attr=mode<<16
                output.writestr(info,b'bad')
            raw = memory.getvalue()
            with self.assertRaises(ValueError):
                self.store.stage(manifest(raw),raw)
        self.assertIsNone(self.store.read().get('pending'))

    def test_activation_then_rollback_and_rejected_version_not_redownloaded(self):
        self.store.stage(self.meta,self.raw)
        self.assertEqual(self.store.activate(),'0.3.1')
        self.assertEqual(self.store.read()['trial'],'0.3.1')
        self.store.rollback()
        self.assertIsNone(self.store.read()['active'])
        updater = Updater(self.store,'0.3.0',Mock(),self.fetch)
        updater.check()
        self.assertIn('0.3.1',self.store.read()['rejected'])
        self.assertFalse(any('runtime.zip' in path for path in self.calls))
        self.assertIn('restaurada',updater.snapshot()['rollback_notice'])

    def test_disabled_offline_and_version_order(self):
        callback = Mock()
        updater = Updater(self.store,'0.3.0',callback,Mock(side_effect=OSError('SECRET')))
        self.store.write(enabled=False)
        updater.check()
        updater.fetch.assert_not_called()
        self.store.write(enabled=True)
        updater.check()
        self.assertEqual(updater.snapshot()['status'],'error')
        self.assertNotIn('SECRET',json.dumps(updater.snapshot()))
        callback.assert_not_called()
        self.assertGreater(version('0.10.0'),version('0.9.9'))
        self.assertEqual(next_version('0.3.0','v0.3.9'),'0.3.10')
        self.assertEqual(next_version('0.4.0','v0.3.9'),'0.4.0')
        for bad in ('../foo','v1.2.3','1.2.3-beta','01.2.3'):
            with self.assertRaises(ValueError):
                version(bad)

    def test_download_ready_is_not_live_code_swap(self):
        callback = Mock()
        updater = Updater(self.store,'0.3.0',callback,self.fetch)
        updater.check()
        self.assertEqual(updater.snapshot()['status'],'ready')
        self.assertIsNone(self.store.read().get('active'))
        callback.assert_not_called()
        count = len(self.calls)
        updater.check()
        self.assertEqual(len(self.calls),count)

    def test_supervisor_falls_back_after_new_child_cannot_start(self):
        self.store.stage(self.meta,self.raw)
        # Supervisor usa XDG_DATA_HOME/browserapi-lab, não o caminho do setUp.
        data = Path(self.tmp.name)/'browserapi-lab'
        store = UpdateStore(data)
        store.stage(self.meta,self.raw)
        dead = Mock()
        dead.wait.return_value=1
        good = Mock()
        good.wait.return_value=0
        with patch.dict(os.environ,{'XDG_DATA_HOME':self.tmp.name}), patch('browserapi_lab.bootstrap.os.geteuid',return_value=1000), patch('browserapi_lab.bootstrap.subprocess.Popen',side_effect=[dead,good]) as spawn:
            self.assertEqual(bootstrap._supervise(['--no-open']),0)
        self.assertEqual(spawn.call_count,2)
        self.assertIsNone(store.read()['active'])
        self.assertIn('0.3.1',store.read()['rejected'])

    def test_successful_confirmation_keeps_previous_for_rollback(self):
        self.store.write(active='0.3.0')
        self.store.stage(self.meta,self.raw)
        self.store.activate()
        self.store.confirm()
        self.assertEqual(self.store.read()['active'],'0.3.1')
        self.assertEqual(self.store.read()['previous'],'0.3.0')
        self.assertIsNone(self.store.read()['trial'])

    def test_disabled_setting_prevents_pending_activation_on_next_launch(self):
        self.store.stage(self.meta,self.raw)
        self.store.write(enabled=False)
        self.assertIsNone(self.store.activate())
        self.assertEqual(self.store.read()['pending'],'0.3.1')

    def test_real_server_restart_waits_for_idle_and_preserves_origin_token(self):
        from browserapi_lab import gui
        captured = []
        errors = []
        result = []
        started = threading.Event()
        class FakeUpdater:
            def __init__(self,store,current,on_ready):
                self.store,self.on_ready=store,on_ready
                captured.append(self)
            def start(self):
                started.set()
            def close(self):
                pass
            def snapshot(self):
                return {'managed':True,'enabled':True}
        original = gui.LocalServer
        servers = []
        def create(panel):
            server = original(panel)
            servers.append(server)
            return server
        def run():
            try:
                result.append(gui.main(['--no-open','--config-dir',str(Path(self.tmp.name)/'config')]))
            except BaseException as error:
                errors.append(error)
        data = Path(self.tmp.name)/'gui'
        with patch.object(gui,'DATA_DIR',data), patch.object(gui,'LocalServer',side_effect=create), patch('browserapi_lab.updates.Updater',FakeUpdater), patch.dict(os.environ,{'BROWSERAPI_SUPERVISED':'1','BROWSERAPI_MANAGED_PORT':'0'}):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(started.wait(5))
            server = servers[0]
            # Attendre une réponse HTTP prouve que serve_forever a démarré.
            connection = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            connection.request('GET','/api/state',headers={'X-BrowserAPI-Token':server.token})
            response = connection.getresponse()
            self.assertEqual(response.status,200)
            response.read()
            connection.close()
            with server.panel.lock:
                server.panel.phase='waiting'
            self.assertFalse(captured[0].on_ready())
            self.assertTrue(thread.is_alive())
            with server.panel.lock:
                server.panel.phase='done'
            self.assertTrue(captured[0].on_ready())
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertFalse(errors,errors)
        self.assertEqual(result,[75])
        handoff = json.loads((data/'relaunch.json').read_text())
        self.assertEqual(handoff,{'port':server.server_port,'token':server.token})
        self.assertFalse((data/'window.json').exists())
