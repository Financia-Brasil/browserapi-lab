"""Apontamento sem navegador: contrato de ``pick`` e da conferência.

O painel pode resolver antes da checagem "abriu?" (pessoa rápida, Enter ou
automação da própria página). Isso não é falha — antes, o passo era abortado com
"O painel de seleção não abriu nesta página" e o campo ficava sem mapeamento.
"""
import unittest

from browserapi_lab.setup import StepUnavailable, pick


class FakePage:
    """Responde na ordem em que ``pick`` chama a página.

    Ordem: script de voz, script do painel, leitura de ``window.__balPick`` e
    limpeza. A checagem "o painel abriu?" passou a ser ``wait_for_function``.
    """

    def __init__(self, *, opened=False, value=None, raises=None, ready=False):
        self.opened = opened
        self.value = value
        self.raises = raises
        self.ready = ready
        self.calls = 0

    def bring_to_front(self):
        return None

    def evaluate(self, _script, *_args):
        self.calls += 1
        if self.raises:
            raise self.raises
        if self.calls >= 3:
            return self.value
        return None

    def wait_for_function(self, *_args, **kwargs):
        if not (self.ready or self.opened or self.value is not None):
            raise TimeoutError('painel não apareceu')


class TestPick(unittest.TestCase):
    def test_panel_that_closed_after_a_fast_choice_is_not_a_failure(self):
        page = FakePage(value={'selector': '#alvo'})
        self.assertEqual(pick(page, 'resposta do assistente'), '#alvo')

    def test_panel_that_never_opened_is_reported_without_waiting(self):
        page = FakePage()
        with self.assertRaises(StepUnavailable) as caught:
            pick(page, 'campo de mensagem')
        self.assertIn('Nada foi alterado', str(caught.exception))

    def test_skip_returns_none_and_abort_cancels_the_mapping(self):
        self.assertIsNone(pick(FakePage(value={'cancelled': True}), 'campo de mensagem'))
        with self.assertRaises(EOFError):
            pick(FakePage(value={'abort': True}), 'campo de mensagem')

    def test_page_that_throws_is_explained(self):
        with self.assertRaises(StepUnavailable) as caught:
            pick(FakePage(raises=RuntimeError('Target closed')), 'campo de mensagem')
        self.assertIn('Não consegui abrir o apontamento', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
