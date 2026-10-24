"""Integração ponta a ponta: descoberta -> envio -> streaming -> extração."""
import unittest
from _harness import BrowserTestCase
from browserapi_lab.discovery import collect, rank_candidates
from browserapi_lab.sender import send_message
from browserapi_lab.observer import install, mark_sent, wait_for_completion, WatchConfig
from browserapi_lab.extractor import extract, dom_fingerprint


class TestPipeline(BrowserTestCase):
    def run_chat(self, query=''):
        self.page.goto(self.server.url(query='?delay=1' + query), wait_until='load')
        composer = rank_candidates(collect(self.page, 'composer')['candidates'], 'composer')[0]
        button = rank_candidates(collect(self.page, 'send_button')['candidates'], 'send_button')[0]
        install(self.page, message_selector='[data-role="assistant"] .body')
        mark_sent(self.page)
        result = send_message(self.page, composer, button, 'Teste público sintético', verify_timeout_ms=1000)
        self.assertTrue(result.success, result.to_dict())
        observed = wait_for_completion(self.page, WatchConfig(stability_window_ms=600, timeout_ms=15000))
        self.assertEqual(observed.status, 'success', observed.to_dict())
        self.assertEqual(self.page.evaluate('FakeChat.state().status'), 'done', 'término prematuro')
        selector = '[data-role="assistant"]:last-child .body'
        before = dom_fingerprint(self.page, selector)
        output = extract(self.page, selector)
        self.assertEqual(before, dom_fingerprint(self.page, selector))
        for piece in ('```python', '### Passos', '| Estratégia | Custo |', '[documentação]'):
            self.assertIn(piece, output['markdown'])
        self.assertNotIn('texto oculto', output['markdown'])
        self.assertNotIn('Copiar', output['markdown'])

    def test_dez_execucoes_consecutivas(self):
        for iteration in range(10):
            with self.subTest(iteration=iteration + 1):
                self.run_chat()

    def test_pausa_longa(self):
        self.run_chat('&mode=pause')

    def test_input(self):
        self.run_chat('&composer=input')

    def test_contenteditable(self):
        self.run_chat('&composer=contenteditable')

    def test_shadow(self):
        self.run_chat('&shadow=1')

    def test_iframe(self):
        self.run_chat('&iframe=1')
