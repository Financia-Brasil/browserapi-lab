"""Interface real + segundo Chromium visível no worker; somente site sintético."""
import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from _harness import BrowserTestCase, REPO_ROOT
from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.gui import LocalServer, Panel
from browserapi_lab.setup import HYPOTHESES


class TestGraphicalJourney(BrowserTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.temp.name) / 'config')
        self.panel = Panel(self.store, Path(self.temp.name) / 'data')
        self.http = LocalServer(self.panel)
        self.http_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.http_thread.start()

    def tearDown(self):
        self.panel.close()
        self.http.shutdown()
        self.http.server_close()
        self.http_thread.join(2)
        self.temp.cleanup()

    def open_panel(self):
        self.page.goto(self.http.entry_url)
        self.page.wait_for_function("document.querySelector('#prepared-label').textContent !== 'Verificando componentes…'")
        self.assertNotIn(self.http.token, self.page.url)

    def wait_question(self, text):
        self.page.wait_for_function("text => !document.querySelector('#prompt').hidden && document.querySelector('#question').textContent.includes(text)", arg=text)

    def wait_phase(self, phase):
        self.page.wait_for_function("text => document.querySelector('#phase').textContent === text", arg=phase, timeout=45000)

    def seed(self, mode='contract'):
        config = ChatConfig('saved', self.server.url(query='?mode='+mode+'&delay=1'), provider='fixture',
                            timeout_ms=4000, stability_ms=400, **HYPOTHESES['fixture'])
        self.store.save(config)
        return config

    def test_full_form_configure_then_health_check(self):
        # A hipótese é local à fixture, não evidência de compatibilidade com sites reais.
        with patch.dict(HYPOTHESES, {'custom':HYPOTHESES['fixture']}):
            self.open_panel()
            self.page.select_option('#browser','chromium')
            self.page.select_option('#provider','custom')
            self.page.fill('#name','graphical')
            self.page.fill('#url', self.server.url(query='?mode=contract&delay=1'))
            self.page.click('#configure')
            self.wait_question('Quando o chat')
            self.assertFalse((self.store.root/'graphical.status.json').exists())
            self.page.click('#continue')
            self.wait_question('Revisar os campos')
            self.page.click('#no')
            self.wait_question('Autoriza UMA')
            self.assertFalse((self.store.root/'graphical.status.json').exists())
            self.page.click('#yes')
            self.wait_phase('Concluído')
            self.assertIn('Funcionou neste teste',self.page.locator('#result-title').inner_text())
            receipt = self.store.status('graphical')
            self.assertTrue(receipt['compatible_in_this_run'])
            self.assertEqual(receipt['browser'],'chromium')
            self.page.get_by_role('button', name='Testar agora').click()
            self.wait_question('Faça login')
            self.page.click('#continue')
            self.wait_question('Autoriza UMA')
            self.page.click('#yes')
            self.wait_phase('Concluído')
            self.assertTrue(self.store.status('graphical')['compatible_in_this_run'])
            evidence = {'kind':'synthetic_graphical_journey','headed_worker':True,
                        'form_configure':True,'health_check':True,'consent_buttons':True,
                        'receipt':self.store.status('graphical'),
                        'scope':'Fixture local; não autentica sites externos ou instala em desktop Ubuntu real.'}
            destination = REPO_ROOT/'results/ci/gui-flow.json'
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_text(json.dumps(evidence,indent=2)+'\n')

    def test_denial_and_cancel_do_not_run_exchange(self):
        self.seed()
        self.open_panel()
        with patch('browserapi_lab.setup.exchange') as exchange:
            self.page.get_by_role('button',name='Testar agora').click()
            self.wait_question('Faça login')
            self.page.click('#cancel')
            self.wait_phase('Interrompido')
            exchange.assert_not_called()
            self.assertIsNone(self.store.status('saved'))
        self.page.get_by_role('button',name='Testar agora').click()
        self.wait_question('Faça login')
        self.page.click('#continue')
        self.wait_question('Autoriza UMA')
        self.page.click('#no')
        self.wait_phase('Concluído')
        self.assertEqual(self.store.status('saved')['status'],'not_authorized')
        self.assertFalse(self.store.status('saved')['compatible_in_this_run'])

    def test_dom_text_is_not_executable_and_repair_remedy_visible(self):
        config = self.seed()
        config.composer = '#missing'
        self.store.save(config)
        self.panel.tell('<img src=x onerror="window.secretLeaked=true">')
        self.open_panel()
        self.assertIn('<img',self.page.locator('#log').inner_text())
        self.assertEqual(self.page.locator('#log img').count(),0)
        self.assertFalse(self.page.evaluate('Boolean(window.secretLeaked)'))
        self.page.get_by_role('button',name='Testar agora').click()
        self.wait_question('Faça login')
        self.page.click('#continue')
        self.wait_question('Autoriza UMA')
        self.page.click('#yes')
        self.wait_phase('Concluído')
        self.assertEqual(self.store.status('saved')['status'],'composer_missing')
        self.assertIn('Corrigir campos',self.page.locator('#result-action').inner_text())
