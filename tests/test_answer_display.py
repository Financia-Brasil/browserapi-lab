"""Resposta do chat: só um turno validado é exibido, e o canal de exibição é opcional.

O recibo continua sem pergunta/resposta. Aqui verificamos o contrato que o painel
usa: ``check(record=...)`` é chamado apenas para mensagem realmente enviada e
resposta nova validada, e uma falha ao exibir nunca vira sucesso/erro de envio.
"""

from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from browserapi_lab.chat import ChatResult
from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.setup import check


class FakePage:
    url = 'https://example.com/app'


def fake_session():
    page = FakePage()

    class Session:
        def page(self, _url=None):
            return page

    @contextmanager
    def factory(_config):
        yield Session()

    return factory


class TestAnswerDisplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name) / 'config')
        self.store.save(ChatConfig('chat', 'https://example.com/app', composer='#c', send='#s',
                                   user='.u', assistant='.a'))
        self.tells = []
        self.recorded = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, result, *, message='Pergunta', answer='s', record=None, show_answer=False):
        def fake_exchange(*_args, **kwargs):
            # O exchange real não envia sem autorização; o dublê respeita isso.
            return result if kwargs.get('authorized') else ChatResult('not_authorized')
        with patch('browserapi_lab.setup.exchange', side_effect=fake_exchange) as exchange:
            receipt = check(self.store, 'chat', message=message, ask=lambda _: answer,
                            tell=self.tells.append, session_factory=fake_session(),
                            record=record or (lambda *args: self.recorded.append(args)),
                            show_answer=show_answer)
            exchange.assert_called_once()
        return receipt

    def test_turno_validado_e_exibido_uma_vez_sem_entrar_no_recibo(self):
        result = ChatResult('success', True, answer='resposta nova', timings={'total_ms': 432.1})
        receipt = self.run_check(result)
        self.assertEqual(len(self.recorded), 1)
        name, question, answer, shown_receipt = self.recorded[0]
        self.assertEqual((name, question, answer), ('chat', 'Pergunta', 'resposta nova'))
        self.assertEqual(shown_receipt['timings']['total_ms'], 432.1)
        self.assertNotIn('resposta nova', str(receipt))
        self.assertNotIn('Pergunta', str(receipt))
        self.assertFalse(any('resposta nova' in text for text in self.tells),
                         'a GUI não repete a resposta no log de operação')

    def test_resposta_antiga_ou_nao_confirmada_nao_e_exibida(self):
        for status in ('timeout', 'send_unconfirmed', 'ambiguous_output', 'contract_invalid',
                       'draft_present', 'not_authorized', 'login_required'):
            with self.subTest(status=status):
                self.recorded.clear()
                self.run_check(ChatResult(status, False, answer='resposta velha'))
                self.assertEqual(self.recorded, [])

    def test_sem_resposta_textual_nao_exibe_turno_incompleto(self):
        for answer in (None, '', '   ', 123):
            with self.subTest(answer=answer):
                self.recorded.clear()
                self.run_check(ChatResult('success', True, answer=answer))
                self.assertEqual(self.recorded, [])

    def test_verificacao_sem_mensagem_da_pessoa_nunca_aparece_na_conversa(self):
        self.run_check(ChatResult('success', True, answer='browserapi-ok'), message=None)
        self.assertEqual(self.recorded, [])

    def test_negacao_nao_envia_nem_exibe(self):
        self.run_check(ChatResult('success', True, answer='não deveria existir'), answer='n')
        self.assertEqual(self.recorded, [])

    def test_falha_ao_exibir_nao_transforma_envio_em_erro(self):
        def broken(*_args):
            raise RuntimeError('memória indisponível')
        result = ChatResult('success', True, answer='resposta nova', timings={'total_ms': 10})
        receipt = self.run_check(result, record=broken)
        self.assertTrue(receipt['compatible_in_this_run'])
        self.assertEqual(receipt['status'], 'success')
        self.assertTrue(any('não conseguiu mostrá-la' in text for text in self.tells))
        self.assertNotIn('memória indisponível', ' '.join(self.tells))

    def test_cli_continua_imprimindo_a_resposta(self):
        self.run_check(ChatResult('success', True, answer='linha da resposta'), show_answer=True)
        self.assertIn('linha da resposta', self.tells)


if __name__ == '__main__':
    unittest.main()
