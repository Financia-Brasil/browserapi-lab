import unittest
from browserapi_lab.sender import evidence_of_send, control_kind, normalize_text, read_composer

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

class TestEvidenceSpeaksBothLanguages(unittest.TestCase):
    """A frase da evidência precisa dizer o que foi observado, não só "ok".

    Quando o site reescreve o texto (NBSP, zero-width, reformatação), o nonce é
    a prova e a comparação por texto legitimamente falha. O recibo registra as
    duas coisas para o diagnóstico não sugerir que o texto foi ignorado.
    """

    def test_nonce_with_rewritten_text_says_the_site_rewrote_it(self):
        ok, reason = evidence_of_send({'count': 0, 'last': None},
                                      {'count': 1, 'last': '9f2a'}, 'pedido 9f2a',
                                      nonce='9f2a')
        self.assertTrue(ok)
        self.assertIn('nonce', reason)
        self.assertIn('reescreveu', reason)

    def test_nonce_with_matching_text_says_both(self):
        ok, reason = evidence_of_send({'count': 0, 'last': None},
                                      {'count': 1, 'last': 'pedido 9f2a'}, 'pedido 9f2a',
                                      nonce='9f2a')
        self.assertTrue(ok)
        self.assertIn('nonce', reason)
        self.assertIn('texto também confere', reason)

    def test_nonce_without_a_new_message_is_not_evidence(self):
        ok, _reason = evidence_of_send({'count': 1, 'last': 'pedido 9f2a'},
                                       {'count': 1, 'last': 'pedido 9f2a'}, 'pedido 9f2a',
                                       nonce='9f2a')
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()


# ---------------------------------------------------------------------------
# Colar em vez de digitar (o relato: "escreve caractere por caractere")
# ---------------------------------------------------------------------------

from unittest.mock import patch
from browserapi_lab.discovery import ScoredCandidate
from browserapi_lab.sender import (send_message, looks_truncated, composer_matches,
                                   composer_has_text, STRATEGIES_BY_KIND, MAX_TYPE_CHARS)


class FakeKeyboard:
    """Só o que o envio usa: inserir texto (colar) e pressionar teclas."""

    def __init__(self, page):
        self.page = page

    def insert_text(self, text):
        self.page.insert(text, 'paste')

    def press(self, key):
        if key.lower().endswith('a'):
            self.page.selected = True


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    # --- o que o envio chama ------------------------------------------------
    def evaluate(self, script, arg=None):
        page = self.page
        if 'navigator.platform' in script:
            return 'Linux'
        # Escrita primeiro: os scripts de inserção também mencionam o campo.
        if 'ClipboardEvent' in script:
            page.insert(arg, 'paste_event')
            return None
        if 'execCommand' in script:
            page.insert(arg, 'exec_insert')
            return None
        if 'isContentEditable' in script:
            return page.text
        return None

    def fill(self, text):
        self.page.insert(text, 'fill')

    def click(self):
        if self.selector == '#send':
            self.page.publish()
        else:
            self.page.focused = True

    def press(self, key):
        pass

    def press_sequentially(self, text, delay=0):
        self.page.keystrokes += len(text)
        self.page.insert(text, 'type')

    def count(self):
        return 1

    def is_visible(self):
        return True

    def is_enabled(self):
        return True


class FakeComposerPage:
    """Chat de mentira com o comportamento que importa: quanto texto cada
    caminho consegue colocar no campo, e o que aparece publicado."""

    def __init__(self, kind='contenteditable', caps=None, publish_cap=None):
        self.kind = kind
        self.caps = caps or {}          # estratégia -> quantos caracteres aceita
        self.publish_cap = publish_cap  # o site publica só este tanto
        self.text = ''
        self.selected = False
        self.focused = False
        self.clicks = 0
        self.keystrokes = 0
        self.published = []
        self.keyboard = FakeKeyboard(self)

    def locator(self, selector):
        return FakeLocator(self, selector)

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script, arg=None):
        if 'navigator.platform' in script:
            return 'Linux'
        return None

    def insert(self, text, strategy):
        cap = self.caps.get(strategy)
        value = text if cap is None else text[:cap]
        self.text = value if self.selected else self.text + value
        self.selected = False

    def publish(self):
        self.clicks += 1
        value = self.text
        if self.publish_cap is not None:
            value = value[:self.publish_cap]
        self.published.append(value)
        self.text = ''


def state_of(page, before_count):
    """Estado das mensagens do usuário, no formato que o sender consome."""
    return {'count': before_count + len(page.published),
            'last': page.published[-1] if page.published else None,
            'layer': 'fake'}


class TestColaEmVezDeDigitar(unittest.TestCase):
    def run_send(self, page, text, strategies=None, **kwargs):
        before = 0
        kwargs.setdefault('composer_timeout_ms', 40)
        with patch('browserapi_lab.sender.user_message_state',
                   side_effect=lambda _page, _selector=None: state_of(page, before)):
            return send_message(page, ScoredCandidate({'tag': 'div',
                                                       'contenteditable': 'true',
                                                       'selector': '#composer'}, 0),
                                ScoredCandidate({'selector': '#send'}, 0), text,
                                strategies=strategies,
                                activation=('click_send',), user_selector='#user',
                                **kwargs)

    def test_texto_grande_entra_de_uma_vez_sem_tecla_por_tecla(self):
        page = FakeComposerPage()
        text = 'linha de prompt ' * 1_500           # ~24 mil caracteres
        result = self.run_send(page, text)
        self.assertTrue(result.success, result.error)
        self.assertEqual(page.published, [text])
        self.assertEqual(page.keystrokes, 0, 'não pode digitar tecla por tecla')
        self.assertEqual(result.strategy, 'paste+click_send')
        self.assertLess(result.fill_ms, 500, 'colar precisa ser rápido')
        self.assertEqual(result.filled_chars, result.expected_chars)

    def test_campo_que_corta_a_colagem_nao_envia_pela_metade(self):
        # Os dois caminhos de colar só aceitam 400 caracteres; o insertText
        # nativo (exec_insert) aceita tudo — é para ele que o envio deve ir.
        page = FakeComposerPage(caps={'paste': 400, 'paste_event': 400})
        text = 'pedido completo ' * 300
        result = self.run_send(page, text)
        self.assertTrue(result.success, result.error)
        self.assertEqual(page.published, [text])
        self.assertEqual(result.strategy, 'exec_insert+click_send')

    def test_quando_nenhum_caminho_aceita_tudo_nada_e_enviado(self):
        page = FakeComposerPage(caps={'paste': 50, 'paste_event': 50,
                                      'exec_insert': 50, 'fill': 50, 'js_set': 50})
        text = 'mensagem que não cabe ' * 400      # acima do limite de digitação
        result = self.run_send(page, text, composer_timeout_ms=10)
        self.assertFalse(result.success)
        self.assertIn('composer_incomplete', result.error)
        self.assertEqual(page.clicks, 0, 'sem texto inteiro, não se clica em Enviar')
        self.assertEqual(page.published, [])
        self.assertEqual(result.filled_chars, 50)

    def test_texto_grande_nunca_cai_na_digitacao_lenta(self):
        page = FakeComposerPage(caps={'paste': 0, 'paste_event': 0,
                                      'exec_insert': 0, 'fill': 0, 'js_set': 0})
        text = 'x' * (MAX_TYPE_CHARS + 1)
        result = self.run_send(page, text, composer_timeout_ms=10)
        self.assertFalse(result.success)
        self.assertEqual(page.keystrokes, 0)
        self.assertIn('composer_incomplete', result.error)

    def test_ordem_padrao_coloca_colar_na_frente_de_digitar(self):
        order = STRATEGIES_BY_KIND['contenteditable']
        self.assertEqual(order[0], 'paste')
        self.assertGreater(order.index('type_contenteditable'), order.index('exec_insert'))
        self.assertEqual(STRATEGIES_BY_KIND['textarea'][0], 'fill')

    def test_site_que_publica_metade_e_reportado_como_corte(self):
        page = FakeComposerPage(publish_cap=500)
        text = 'pedido bem grande ' * 400
        result = self.run_send(page, text)
        self.assertFalse(result.success)
        self.assertTrue(result.truncated, result.error)
        self.assertIn('CORTADA', result.attempts[-1].evidence)


class TestConferenciaDoCampo(unittest.TestCase):
    def test_quebra_a_mais_no_fim_nao_invalida(self):
        page = FakeComposerPage()
        page.text = 'texto colado\n'
        self.assertTrue(composer_matches(page.locator('#c'), 'texto colado')[0])

    def test_texto_anterior_que_nao_foi_limpo_invalida(self):
        page = FakeComposerPage()
        page.text = 'rascunho velho texto colado'
        self.assertFalse(composer_matches(page.locator('#c'), 'texto colado')[0])

    def test_texto_cortado_invalida(self):
        page = FakeComposerPage()
        page.text = 'texto'
        self.assertFalse(composer_matches(page.locator('#c'), 'texto colado')[0])


class TestCorte(unittest.TestCase):
    def test_prefixo_curto_e_corte(self):
        cut, shown, wanted = looks_truncated('a' * 1000, 'a' * 500)
        self.assertTrue(cut)
        self.assertEqual((shown, wanted), (500, 1000))

    def test_texto_quase_inteiro_nao_e_corte(self):
        self.assertFalse(looks_truncated('a' * 1000, 'a' * 960)[0])

    def test_texto_diferente_nao_e_corte(self):
        self.assertFalse(looks_truncated('a' * 1000, 'b' * 500)[0])

    def test_evidencia_nao_aceita_balão_cortado_com_campo_esvaziado(self):
        ok, motivo = evidence_of_send({'count': 1}, {'count': 2, 'last': 'a' * 400},
                                      'a' * 1000, composer_cleared=True)
        self.assertFalse(ok)
        self.assertIn('CORTADA', motivo)


class TestRascunhoFalso(unittest.TestCase):
    """O relato: "Há um rascunho no campo" com o campo vazio, logo após mapear.

    Editores ricos deixam ``<p><br></p>`` ou um nó de placeholder dentro do
    campo. Ler ``innerText`` cru devolvia ``"\\n"`` (ou o texto do placeholder),
    que é verdadeiro em Python — e o envio parava antes de digitar.
    """

    class Campo:
        def __init__(self, value):
            self.value = value

        def evaluate(self, script, arg=None):
            return self.value

    def test_campo_com_quebra_de_linha_sobrando_nao_e_rascunho(self):
        for vazio in ('\n', '   ', '\u200b', '\u00a0\n\u200b', ''):
            self.assertFalse(composer_has_text(self.Campo(vazio)), repr(vazio))

    def test_texto_de_verdade_continua_sendo_rascunho(self):
        self.assertTrue(composer_has_text(self.Campo('rascunho que a pessoa digitou')))

    def test_leitura_impossivel_nao_vira_rascunho(self):
        class Quebrado:
            def evaluate(self, script, arg=None):
                raise RuntimeError('página trocando')
        self.assertIsNone(read_composer(Quebrado()))
        self.assertFalse(composer_has_text(Quebrado()))

    def test_leitura_ignora_placeholder_e_br(self):
        # O JS de leitura é o que roda de verdade no navegador; aqui garantimos
        # que ele menciona as regras que evitam o falso rascunho.
        from browserapi_lab.sender import COMPOSER_TEXT_JS
        for marcador in ('data-placeholder', 'aria-hidden', 'is-empty', 'BR'):
            self.assertIn(marcador, COMPOSER_TEXT_JS)
