import unittest
from browserapi_lab.sender import evidence_of_send, control_kind, normalize_text

class TestEvidence(unittest.TestCase):
    def test_no_message_is_failure(self):
        self.assertFalse(evidence_of_send({'count': 1}, {'count': 1, 'last': 'oi'}, 'oi')[0])

    def test_wrong_text_is_failure(self):
        self.assertFalse(evidence_of_send({'count': 1}, {'count': 2, 'last': 'outro'}, 'oi')[0])

    def test_new_matching_message(self):
        self.assertTrue(evidence_of_send({'count': 1}, {'count': 2, 'last': 'oi'}, 'oi')[0])

    def test_kind(self):
        self.assertEqual(control_kind({'tag': 'textarea'}), 'textarea')
        self.assertEqual(control_kind({'tag': 'input'}), 'input')
        self.assertEqual(control_kind({'tag': 'div', 'contenteditable': 'true'}), 'contenteditable')


class TestEvidenciaReal(unittest.TestCase):
    """O relato: a mensagem foi enviada e o programa disse "sem confirmação"."""

    def test_site_que_colapsa_espacos_e_nbsp_ainda_confirma(self):
        enviado = 'Responda somente com um objeto JSON.\n\nUse answer igual a browserapi-ok.'
        renderizado = 'Responda somente com um objeto JSON.\u00a0\u200b Use answer igual a browserapi-ok.'
        ok, motivo = evidence_of_send({'count': 2, 'last': 'anterior'},
                                      {'count': 3, 'last': renderizado}, enviado)
        self.assertTrue(ok, motivo)
        self.assertIn('texto esperado', motivo)

    def test_mensagem_nova_reescrita_pelo_site_confirma_com_campo_esvaziado(self):
        # Gemini, por exemplo, pode renderizar a mensagem com transformações.
        ok, motivo = evidence_of_send({'count': 2}, {'count': 3, 'last': 'Texto renderizado diferente'},
                                      'texto original', composer_cleared=True)
        self.assertTrue(ok, motivo)
        self.assertIn('campo esvaziado', motivo)

    def test_texto_divergente_com_campo_preenchido_continua_ambiguo(self):
        ok, motivo = evidence_of_send({'count': 2}, {'count': 3, 'last': 'outro'},
                                      'texto original', composer_cleared=False)
        self.assertFalse(ok, motivo)
        self.assertIn('divergente', motivo)

    def test_campo_esvaziado_sozinho_nao_confirma(self):
        ok, motivo = evidence_of_send({'count': 2, 'last': 'anterior'},
                                      {'count': 2, 'last': 'anterior'}, 'texto',
                                      composer_cleared=True)
        self.assertFalse(ok, motivo)
        self.assertIn('nenhuma mensagem nova', motivo)

    def test_lista_virtualizada_que_reutiliza_o_mesmo_no_confirma(self):
        ok, motivo = evidence_of_send({'count': 1, 'last': 'mensagem antiga'},
                                      {'count': 1, 'last': 'mensagem nova'}, 'mensagem nova')
        self.assertTrue(ok, motivo)
        self.assertIn('mesmo nó', motivo)

    def test_sem_texto_anterior_nao_inventa_reuso_de_no(self):
        self.assertFalse(evidence_of_send({'count': 1}, {'count': 1, 'last': 'oi'}, 'oi')[0])

    def test_normalizacao_nao_aproxima_textos_diferentes(self):
        self.assertNotEqual(normalize_text('Enviar agora'), normalize_text('Enviar depois'))
        self.assertEqual(normalize_text(' a\u00a0\u200b\n b '), 'a b')
