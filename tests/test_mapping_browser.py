"""Mapeamento guiado: passos, pulo, refazer e captura do balão inteiro.

Motivação (uso real, ADR-023):

* o Gemini entregou a resposta em dois ``<span>`` dentro de um
  ``<p class="first-token">`` e o apontamento parou no primeiro pedaço;
* responder "Sim" à pergunta do microfone levava para o campo de mensagem e
  cancelar perdia o mapeamento inteiro;
* ao apontar texto, o programa destacava botões e não identificava os balões.

A fixture ``fixtures/gemini_like.html`` reproduz esse DOM. Nada aqui usa conta,
login ou site real.
"""
from pathlib import Path
import unittest

from _harness import BrowserTestCase, REPO_ROOT
from browserapi_lab.chat import exchange
from browserapi_lab.config import ChatConfig
from browserapi_lab.setup import HYPOTHESES, pick, repair_fields

GEMINI_LIKE = {
    'composer': '.ql-editor',
    'send': 'button[aria-label="Enviar mensagem"]',
    'user': 'user-query',
    'assistant': 'model-response',
    'root': '#conversation',
}


class TestGuidedMappingBrowser(BrowserTestCase):
    def open_fixture(self):
        url = self.server.url('gemini_like.html')
        self.page.goto(url, wait_until='load')
        return ChatConfig('gemini-like', url, provider='custom', timeout_ms=8000,
                          stability_ms=400, **GEMINI_LIKE)

    def run_picker(self, role, step='1 de 1', hint=''):
        script = (REPO_ROOT / 'browserapi_lab/assets/picker.js').read_text()
        self.page.evaluate(script, {'role': role, 'step': step, 'hint': hint})

    def test_pointer_on_a_span_captures_the_whole_balloon(self):
        """O defeito relatado: dois <span> na mesma resposta, um só capturado."""
        self.open_fixture()
        self.run_picker('resposta do assistente', step='5 de 5', hint='Clique em qualquer parte do balão.')
        # O usuário clica no primeiro pedaço (o <span> "Belém").
        self.page.locator('model-response .first-token span').first.click()
        self.assertTrue(self.page.locator('#__browserapi_picker').is_visible())
        preview = self.page.locator('#__browserapi_picker').inner_text()
        self.assertIn('Vai capturar', preview)
        self.assertIn('Belém', preview)
        self.assertIn('capital do Pará', preview)  # o segundo <span> também entra
        self.assertIn('Passo 5 de 5', preview)
        self.page.locator('[data-picker-confirm]').click()
        selector = self.page.evaluate('window.__balPick.selector')
        self.assertEqual(selector, 'model-response')
        texto = self.page.locator(selector).first.inner_text()
        self.assertIn('Belém é a capital do Pará.', texto)
        self.assertIn('Fica na região Norte', texto)
        self.assertNotIn('Copiar', texto)  # botões da barra de ações não são resposta

    def test_saved_fragment_selector_still_captures_the_whole_answer(self):
        """Quem já tem o seletor quebrado salvo não perde o resto da resposta."""
        config = self.open_fixture()
        config.assistant = 'p.first-token'  # seletor antigo, apontado num pedaço
        result = exchange(self.page, config, 'Qual é a capital do Pará?', authorized=True)
        self.assertEqual(result.status, 'success', result.receipt(config))
        self.assertIn('Olá!', result.answer)
        self.assertIn('Como posso ajudar você hoje?', result.answer)
        self.assertIn('Resposta sintética da fixture', result.answer)

    def test_text_candidates_are_balloons_not_buttons(self):
        self.open_fixture()
        self.run_picker('mensagem do usuário')
        marks = self.page.locator('#__browserapi_picker_marks > div')
        self.assertGreaterEqual(marks.count(), 1)
        labels = self.page.locator('#__browserapi_picker_marks button').evaluate_all(
            'items => items.map(item => item.getAttribute("aria-label"))')
        self.assertTrue(any('capital do Pará' in label for label in labels), labels)
        self.assertFalse(any('Histórico' in label or 'Upgrade' in label for label in labels), labels)
        # Clicar num botão da página (fora do balão) não vira seleção de mensagem.
        self.page.locator('header button[aria-label="Histórico"]').click()
        status = self.page.locator('#__browserapi_picker').inner_text()
        self.assertIn('botão', status.lower())
        self.assertIsNone(self.page.evaluate('window.__balPick'))
        self.page.locator('[data-picker-skip]').click()
        self.assertTrue(self.page.evaluate('window.__balPick.cancelled'))

    def test_escape_skips_a_field_and_cancel_aborts_everything(self):
        self.open_fixture()
        self.run_picker('campo de mensagem', step='1 de 5')
        self.page.keyboard.press('Escape')
        self.assertTrue(self.page.evaluate('window.__balPick.cancelled'))
        self.assertFalse(self.page.evaluate('!!window.__balPick.abort'))
        self.run_picker('campo de mensagem', step='1 de 5')
        self.page.locator('[data-picker-abort]').click()
        self.assertTrue(self.page.evaluate('window.__balPick.abort'))

    def test_skip_in_the_real_picker_returns_none_and_abort_raises(self):
        self.open_fixture()
        self.page.evaluate("""() => {
            const timer = setInterval(() => {
                const skip = document.querySelector('[data-picker-skip]');
                if (!skip) return;
                clearInterval(timer);
                skip.click();
            }, 50);
        }""")
        self.assertIsNone(pick(self.page, 'resposta do assistente', step='5 de 5'))
        self.page.evaluate("""() => {
            const timer = setInterval(() => {
                const abort = document.querySelector('[data-picker-abort]');
                if (!abort) return;
                clearInterval(timer);
                abort.click();
            }, 50);
        }""")
        with self.assertRaises(EOFError):
            pick(self.page, 'resposta do assistente', step='5 de 5')


class TestGuidedMappingUnit(unittest.TestCase):
    class Page:
        url = 'https://example.com/app'

        def evaluate(self, *_args, **_kwargs):
            return None

        def bring_to_front(self):
            pass

    def config(self):
        return ChatConfig('chat', 'https://example.com', composer='#c', send='#s',
                          user='.u', assistant='.a', root='body')

    def test_question_texts_and_order(self):
        asked = []
        answers = iter(['n', 'n', 'n', 'n'])

        def ask(text):
            asked.append(text)
            return next(answers, 'n')

        repair_fields(self.Page(), self.config(), ask=ask, tell=lambda *_: None,
                      picker=lambda *_a, **_k: None, fields=('composer', 'send', 'user', 'assistant'))
        self.assertEqual(len(asked), 4, asked)
        self.assertIn('Passo 1 de 4 · Campo de digitação', asked[0])
        self.assertIn('CAIXA DE TEXTO', asked[0])
        self.assertIn('Passo 2 de 4 · Botão Enviar', asked[1])
        self.assertIn('Passo 3 de 4 · A sua pergunta', asked[2])
        self.assertIn('A SUA PERGUNTA JÁ ENVIADA', asked[2])
        self.assertIn('não o campo de digitar', asked[2])
        self.assertIn('Passo 4 de 4 · A resposta do chat', asked[3])
        self.assertIn('A RESPOSTA DO CHAT', asked[3])

    def test_skipping_a_field_keeps_the_others_and_says_so(self):
        tells = []
        asked = []
        answers = iter(['s', 's', 'n', 'n'])

        def ask(text):
            asked.append(text)
            return next(answers, 'n')

        def picker(_page, role, **_options):
            self.assertIn(role, ('campo de mensagem', 'mensagem do usuário'))
            return None

        repair_fields(self.Page(), self.config(), ask=ask, tell=tells.append, picker=picker,
                      fields=('composer', 'user'))
        # O campo foi pulado, mas a pergunta seguinte aconteceu.
        self.assertTrue(any('Passo 2 de 2 · A sua pergunta' in text for text in asked), asked)
        self.assertTrue(any('você pulou' in line for line in tells), tells)
        self.assertTrue(any('Campos pulados' in line for line in tells), tells)

    def test_captured_field_can_be_redone_without_restarting(self):
        picks = iter(['#c-amplo', '#c-novo'])
        answers = iter(['s', 's', 's'])
        tells = []
        config = self.config()

        class PageWithLocator(self.Page):
            class Locator:
                def __init__(self):
                    self.first = self

                def count(self):
                    return 1

                def evaluate(self, *_args):
                    return 'escreva aqui'

            def locator(self, selector):
                return self.Locator()

        repair_fields(PageWithLocator(), config, ask=lambda _: next(answers, 'n'),
                      tell=tells.append, picker=lambda *_a, **_k: next(picks), fields=('composer',))
        self.assertEqual(config.composer, '#c-novo')
        self.assertTrue(any('Capturado (Campo de digitação): “escreva aqui”' in line for line in tells), tells)
        self.assertTrue(any('Mapeamento concluído' in line for line in tells), tells)

    def test_microphone_question_is_optional_and_never_jumps_to_the_composer(self):
        tells = []
        config = self.config()
        config.composer = '#intacto'
        asked = []
        answers = iter(['s'])
        repair_fields(self.Page(), config, ask=lambda text: (asked.append(text), next(answers, 'n'))[1],
                      tell=tells.append, picker=lambda *_a, **_k: None, fields=('voice',))
        self.assertTrue(any('microfone' in text.lower() for text in asked))
        self.assertTrue(any('Sim = você aponta agora' in text for text in asked), asked)
        self.assertEqual(config.composer, '#intacto')
        self.assertTrue(any('Microfone não apontado' in line for line in tells), tells)
        self.assertIn('Passo 1 de 1 · Microfone', asked[0])

    def test_cancel_mapping_stops_instead_of_silently_skipping(self):
        def picker(*_args, **_options):
            raise EOFError('Mapeamento cancelado')

        with self.assertRaises(EOFError):
            repair_fields(self.Page(), self.config(), ask=lambda _: 's', tell=lambda *_: None,
                          picker=picker, fields=('composer',))

    def test_picker_options_carry_step_and_hint(self):
        seen = []

        def picker(_page, role, **options):
            seen.append((role, options))
            return '#c'

        repair_fields(self.Page(), self.config(), ask=lambda _: 's', tell=lambda *_: None,
                      picker=picker, fields=('composer',))
        self.assertEqual(seen[0][0], 'campo de mensagem')
        self.assertEqual(seen[0][1].get('step'), '1 de 1')
        self.assertTrue(seen[0][1].get('hint'))


class TestPanelShowsTheStep(unittest.TestCase):
    def test_panel_parses_step_and_renders_progress(self):
        js = (REPO_ROOT / 'browserapi_lab/assets/panel.js').read_text()
        html = (REPO_ROOT / 'browserapi_lab/assets/panel.html').read_text()
        css = (REPO_ROOT / 'browserapi_lab/assets/panel.css').read_text()
        self.assertIn('Passo (\\d+) de (\\d+)', js)
        self.assertIn("$('step-dots')", js)
        self.assertIn('id="prompt-step"', html)
        self.assertIn('id="step-dots"', html)
        self.assertIn('.step-dots', css)


if __name__ == '__main__':
    unittest.main()
