"""Regressões em Chromium real: contratos, ambiguidade e envio sem retry cego."""
import json
from _harness import BrowserTestCase
from browserapi_lab.discovery import collect, rank_candidates
from browserapi_lab.sender import send_message
from browserapi_lab.observer import install, wait_for_completion, WatchConfig
from browserapi_lab.validation import select_output


class TestResilience(BrowserTestCase):
    def setup_chat(self, query=''):
        self.page.goto(self.server.url(query='?delay=1' + query), wait_until='load')
        return (rank_candidates(collect(self.page, 'composer')['candidates'], 'composer')[0],
                rank_candidates(collect(self.page, 'send_button')['candidates'], 'send_button')[0])

    def test_fill_keyboard_js_and_enter(self):
        for kind, fill, activation in (('textarea', 'fill', 'click_send'),
                                       ('input', 'type', 'press_enter'),
                                       ('contenteditable', 'type_contenteditable', 'click_send'),
                                       ('input', 'js_set', 'click_send')):
            with self.subTest(kind=kind, fill=fill):
                composer, button = self.setup_chat('&composer=' + kind)
                result = send_message(self.page, composer, button, 'Mensagem sintética',
                                      strategies=[fill], activation=[activation], verify_timeout_ms=500)
                self.assertTrue(result.success, result.to_dict())
                self.assertTrue(result.attempts[0].composer_confirmed)

    def test_uncertain_send_never_duplicates(self):
        composer, button = self.setup_chat()
        self.page.evaluate('''() => document.querySelector('#send').addEventListener('click', () => {
          const el = document.querySelector('[data-role="user"]');
          if (el) el.setAttribute('data-role', 'unclassified');
        })''')
        result = send_message(self.page, composer, button, 'Uma única mensagem', verify_timeout_ms=100)
        self.assertFalse(result.success)
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 1)

    def test_empty_timeout_then_recover_same_page(self):
        composer, button = self.setup_chat('&mode=empty')
        install(self.page, message_selector='[data-role="assistant"] .body')
        self.assertTrue(send_message(self.page, composer, button, 'Vazia').success)
        result = wait_for_completion(self.page, WatchConfig(timeout_ms=500, poll_interval_ms=50))
        self.assertEqual(result.status, 'timeout')
        self.page.evaluate("FakeChat.config({mode:'normal'})")
        composer = rank_candidates(collect(self.page, 'composer')['candidates'], 'composer')[0]
        button = rank_candidates(collect(self.page, 'send_button')['candidates'], 'send_button')[0]
        install(self.page, message_selector='[data-role="assistant"] .body')
        self.assertTrue(send_message(self.page, composer, button, 'Recuperação').success)
        self.assertEqual(wait_for_completion(self.page, WatchConfig(stability_window_ms=600, timeout_ms=15000)).status, 'success')

    def test_contract_new_assistant_only_and_ambiguity(self):
        self.setup_chat()
        request_id = 'synthetic-current'
        text = json.dumps({'request_id': request_id, 'answer': 'ok'})
        self.page.evaluate('''text => {
            document.querySelector('#conversation').innerHTML = '';
            for (const [role, value] of [['user', text], ['assistant', 'old'], ['assistant', text]]) {
                const el = document.createElement('div');
                el.setAttribute('data-role', role); el.textContent = value;
                document.querySelector('#conversation').appendChild(el);
            }
        }''', text)
        candidates = self.page.locator('[data-role="assistant"]').all_text_contents()
        self.assertEqual(select_output(candidates[1:], request_id).status, 'selected')
        self.page.evaluate('''() => {
          const el = document.querySelector('[data-role="assistant"]:last-child');
          el.parentNode.appendChild(el.cloneNode(true));
        }''')
        candidates = self.page.locator('[data-role="assistant"]').all_text_contents()
        self.assertEqual(select_output(candidates[1:], request_id).status, 'ambiguous')

    def test_watcher_reinstall_disconnects_previous_observer(self):
        self.setup_chat()
        install(self.page, message_selector='[data-role="assistant"] .body')
        self.page.evaluate('window.oldWatcher = window.__balStream')
        install(self.page, message_selector='[data-role="assistant"] .body')
        self.page.evaluate("document.querySelector('#conversation').appendChild(document.createElement('p'))")
        self.page.wait_for_timeout(50)
        self.assertEqual(self.page.evaluate('window.oldWatcher.mutation_count'), 0)
        self.assertGreater(self.page.evaluate('window.__balStream.mutation_count'), 0)

    def test_alerts_not_options_detect_blocking(self):
        self.setup_chat()
        from browserapi_lab.observer import read_ui
        install(self.page)
        self.assertIsNone(read_ui(self.page).blocking)
        self.page.evaluate('''() => {
          const alert = document.createElement('div');
          alert.setAttribute('role', 'alert'); alert.textContent = 'Too many requests';
          document.querySelector('#conversation').appendChild(alert);
        }''')
        self.assertEqual(read_ui(self.page).blocking, 'rate_limit')

    def test_old_feedback_buttons_do_not_hide_send_candidate(self):
        self.setup_chat()
        self.page.evaluate('''() => {
          for (let i = 0; i < 150; i++) {
            const el = document.createElement('button');
            el.textContent = 'Copiar';
            document.querySelector('#conversation').appendChild(el);
          }
        }''')
        buttons = rank_candidates(collect(self.page, 'send_button')['candidates'], 'send_button')
        self.assertEqual(buttons[0].selector, '#send')
        composer = rank_candidates(collect(self.page, 'composer')['candidates'], 'composer')[0]
        self.assertTrue(send_message(self.page, composer, buttons[0], 'Conversa longa').success)
