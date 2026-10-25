"""Metas de produto testadas contra chat controlado, não sites autenticados."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _harness import BrowserTestCase
from browserapi_lab.chat import exchange, preflight
from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.setup import HYPOTHESES, configure, repair_fields, status, pick


class TestChatWorkflow(BrowserTestCase):
    def prepare(self, mode='contract'):
        config = ChatConfig('test-chat', self.server.url(), provider='fixture',
                            timeout_ms=4000, stability_ms=400, **HYPOTHESES['fixture'])
        self.page.goto(config.url, wait_until='load')
        self.page.evaluate('mode => FakeChat.config({mode, delay:1})', mode)
        return config

    def test_authorized_health_contract(self):
        config = self.prepare()
        result = exchange(self.page, config, authorized=True, health_check=True)
        self.assertEqual(result.status, 'success')
        self.assertTrue(result.compatible)
        self.assertEqual(result.answer, 'browserapi-ok')
        self.assertIsNotNone(result.timings['ttft_dom_ms'])
        self.assertLess(result.timings['capture_overhead_ms'], 2500)

    def test_no_authorization_no_send(self):
        config = self.prepare()
        self.assertEqual(exchange(self.page, config, health_check=True).status, 'not_authorized')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)

    def test_draft_not_overwritten(self):
        config = self.prepare()
        self.page.locator('#composer').fill('private draft')
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'draft_present')
        self.assertEqual(self.page.locator('#composer').input_value(), 'private draft')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)

    def test_old_answer_does_not_confirm_new_response(self):
        config = self.prepare('empty')
        config.timeout_ms = 500
        self.page.locator('[data-role=assistant] .body').evaluate("el => el.textContent = 'old answer'")
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'timeout')

    def test_broken_selector_repair_then_success(self):
        config = self.prepare()
        config.composer = '#missing'
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'composer_missing')
        answers = iter(['s', 'n', 'n', 'n'])
        repair_fields(self.page, config, ask=lambda _: next(answers), tell=lambda *_: None,
                      picker=lambda *_: '#composer')
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'success')

    def test_blocked_states_and_remedies(self):
        for mode, expected in (('login', 'login_required'), ('ratelimit', 'rate_limit'), ('error', 'error')):
            with self.subTest(mode=mode):
                config = self.prepare(mode)
                result = exchange(self.page, config, authorized=True, health_check=True)
                self.assertEqual(result.status, expected)
                self.assertTrue(result.receipt(config)['action'])
                self.assertFalse(result.compatible)

    def test_wrong_origin_never_sends(self):
        config = self.prepare()
        config.url = 'https://other.example/'
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'wrong_origin')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)

    def test_ask_returns_markdown_without_health_prompt(self):
        config = self.prepare('normal')
        result = exchange(self.page, config, 'Mensagem pública', authorized=True)
        self.assertEqual(result.status, 'success')
        self.assertIn('```python', result.answer)
        self.assertEqual(self.page.evaluate('FakeChat.lastUserMessage()'), 'Mensagem pública')

    def test_configure_wizard_with_explicit_confirmation(self):
        config = self.prepare()
        session = self.session
        page = self.page
        class WizardSession:
            def page(self, url):
                page.goto(url, wait_until='load')
                page.evaluate("FakeChat.config({mode:'contract',delay:1})")
                return page
        @contextmanager
        def factory(browser):
            self.assertFalse(browser.headless, 'assistente deve abrir janela visível por padrão')
            yield WizardSession()
        answers = iter(['chromium', 'custom', config.url, '', 's', 's', 's', 's', 's', 's'])
        selectors = iter(['#composer', '#send', '[data-role="user"] .body', '[data-role="assistant"] .body'])
        with tempfile.TemporaryDirectory() as root:
            store = ConfigStore(root)
            receipt = configure(store, 'wizard', ask=lambda _: next(answers), tell=lambda *_: None,
                                session_factory=factory, picker=lambda *_: next(selectors))
            self.assertTrue(receipt['compatible_in_this_run'], receipt)
            self.assertEqual(status(store, 'wizard')['status'], 'success')
            self.assertTrue(store.load('wizard').ready)

    def test_picker_selects_composer_and_prevents_send(self):
        self.prepare()
        script = (Path(__file__).parents[1] / 'browserapi_lab/assets/picker.js').read_text()
        self.page.evaluate(script, 'campo de mensagem')
        self.page.locator('#composer').click()
        self.assertEqual(self.page.evaluate('window.__balPick.selector'), '#composer')
        self.page.locator('#composer').fill('Não enviar durante reparo')
        self.page.evaluate(script, 'botão Enviar')
        self.page.locator('#send').click()
        self.assertEqual(self.page.evaluate('window.__balPick.selector'), '#send')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)
        self.assertEqual(self.page.locator('#__browserapi_picker').count(), 0)

    def test_unrelated_page_mutations_do_not_block_completion(self):
        config = self.prepare()
        config.root = 'body'
        self.page.evaluate('''() => {
          const clock = document.createElement('div'); document.body.appendChild(clock);
          window.noiseTimer = setInterval(() => { clock.textContent = String(performance.now()); }, 25);
        }''')
        try:
            result = exchange(self.page, config, authorized=True, health_check=True)
            self.assertEqual(result.status, 'success')
        finally:
            self.page.evaluate('clearInterval(window.noiseTimer)')


    def test_repair_message_containers_by_real_pointing(self):
        config = self.prepare()
        self.page.evaluate("FakeChat.send('mensagem de amostra')")
        self.page.wait_for_function("FakeChat.state().status === 'done'")
        script = (Path(__file__).parents[1] / 'browserapi_lab/assets/picker.js').read_text()
        for role, target, key in (('mensagem do usuário', '[data-role=user] .body', 'user'),
                                  ('resposta do assistente', '[data-role=assistant]:last-child .body', 'assistant')):
            self.page.evaluate(script, role)
            self.page.locator(target).click()
            selected = self.page.evaluate('window.__balPick.selector')
            setattr(config, key, selected)
        result = exchange(self.page, config, authorized=True, health_check=True)
        self.assertEqual(result.status, 'success')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 2)



class TestCLIRealBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from _harness import no_browser_reason
        import shutil
        reason = no_browser_reason()
        if reason:
            raise unittest.SkipTest(reason)
        if not shutil.which('xvfb-run'):
            raise RuntimeError('CI precisa de xvfb-run para testar a CLI headed')

    def test_check_status_and_ask_from_real_cli(self):
        import os
        import subprocess
        import sys
        from _harness import FixtureServer, REPO_ROOT
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            html = (REPO_ROOT / 'browserapi_lab/assets/fake_chat.html').read_text()
            html = html.replace('mode: "normal",', 'mode: "contract",').replace('delay: 4,', 'delay: 1,')
            (root / 'fake_chat.html').write_text(html)
            server = FixtureServer(root).start()
            try:
                config = ChatConfig('cli-chat', server.url(), provider='fixture', timeout_ms=15000,
                                    stability_ms=400, **HYPOTHESES['fixture'])
                store = ConfigStore(root / 'settings')
                store.save(config)
                command = ['xvfb-run', '-a', sys.executable, '-m', 'browserapi_lab.cli',
                           '--config-dir', str(store.root)]
                env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
                result = subprocess.run(command + ['check', 'cli-chat'], input='\ns\n', text=True,
                                        capture_output=True, timeout=40, cwd=root, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(store.status('cli-chat')['compatible_in_this_run'])
                status_result = subprocess.run(command + ['status', 'cli-chat'], text=True,
                                               capture_output=True, timeout=10, cwd=root, env=env)
                self.assertEqual(status_result.returncode, 0, status_result.stderr)
                # Ausência de consentimento nunca envia; status anterior é substituído por recibo de não envio.
                result = subprocess.run(command + ['check', 'cli-chat'], input='\nn\n', text=True,
                                        capture_output=True, timeout=40, cwd=root, env=env)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(store.status('cli-chat')['status'], 'not_authorized')
            finally:
                server.stop()


class TestProductHealthBenchmark(BrowserTestCase):
    def test_ten_checks_same_chat_with_capture_budget(self):
        import json
        import statistics
        from _harness import REPO_ROOT
        from browserapi_lab.benchmark import percentile
        config = ChatConfig('benchmark-health', self.server.url(), provider='fixture',
                            timeout_ms=15000, stability_ms=1200, **HYPOTHESES['fixture'])
        self.page.goto(config.url, wait_until='load')
        self.page.evaluate("FakeChat.config({mode:'contract', delay:1})")
        values, totals = [], []
        for iteration in range(10):
            result = exchange(self.page, config, authorized=True, health_check=True)
            self.assertEqual(result.status, 'success', f'iteration={iteration+1}')
            values.append(result.timings['capture_overhead_ms'])
            totals.append(result.timings['total_ms'])
        summary = {'iterations': 10, 'failures': 0, 'same_conversation': True,
                   'capture_p95_ms': percentile(values), 'capture_budget_ms': 900,
                   'total_p50_ms': statistics.median(totals), 'total_p95_ms': percentile(totals),
                   'browser_version': self.session.context.browser.version,
                   'scope': 'Contrato sintético local; não mede API ou chat real.'}
        self.assertLess(summary['capture_p95_ms'], 900)
        ConfigStore.write_json(REPO_ROOT / 'results/ci/product-flow.json', summary)
