"""Leitura da conversa em camadas: decisão entre apontado e camadas.

Motivação (dossiê ``pesquisa/2026-10-28-arquitetura-captura-e-ui.md``): o
mapeamento apontado à mão continua valendo quando lê a conversa de forma limpa,
mas não pode ser a única fonte — foi ele que produziu "envio não confirmado"
com a mensagem na tela. Estes testes cobrem a escolha, sem navegador.
"""
import unittest

from browserapi_lab.capture import (CAPTURE_SCRIPT, choose_reading, configured_is_clean,
                                    report, summarize, user_state)


def pair(index):
    return [{'role': 'user', 'text': f'pergunta {index}'},
            {'role': 'assistant', 'text': f'resposta {index}'}]


def items(count):
    found = []
    for index in range(1, count + 1):
        found.extend(pair(index))
    return found


class TestConfiguredReading(unittest.TestCase):
    def test_clean_when_balanced_alternating_and_without_overlap(self):
        self.assertTrue(configured_is_clean(items(3), 0))

    def test_overlap_is_never_clean(self):
        self.assertFalse(configured_is_clean(items(3), 2))

    def test_unbalanced_is_never_clean(self):
        self.assertFalse(configured_is_clean(items(3) + pair(4)[:1], 0))

    def test_out_of_order_is_never_clean(self):
        found = [{'role': 'user', 'text': 'p1'}, {'role': 'user', 'text': 'p2'},
                 {'role': 'assistant', 'text': 'r1'}, {'role': 'assistant', 'text': 'r2'}]
        self.assertFalse(configured_is_clean(found, 0))

    def test_empty_is_not_clean(self):
        self.assertFalse(configured_is_clean([], 0))


class TestChooseReading(unittest.TestCase):
    def test_clean_configured_reading_wins(self):
        chosen = choose_reading({'layered': {'layer': 'marker', 'items': items(2)},
                                 'configured': {'items': items(2), 'overlap': 0}})
        self.assertEqual(chosen['layer'], 'configured')
        self.assertFalse(chosen['fallback'])
        self.assertEqual(chosen['warnings'], [])

    def test_dirty_configured_falls_back_to_declared_role(self):
        # O defeito relatado: o seletor da resposta também pegava a pergunta.
        chosen = choose_reading({'layered': {'layer': 'marker', 'items': items(3)},
                                 'configured': {'items': items(2) + pair(3)[:1], 'overlap': 4}})
        self.assertEqual(chosen['layer'], 'marker')
        self.assertTrue(chosen['fallback'])
        self.assertEqual(len(chosen['items']), 6)
        self.assertTrue(chosen['warnings'])
        self.assertIn('papel declarado', chosen['warnings'][0])

    def test_dirty_configured_falls_back_to_framework_state(self):
        chosen = choose_reading({'layered': {'layer': 'framework', 'items': items(2)},
                                 'configured': {'items': [{'role': 'user', 'text': 'só pergunta'}], 'overlap': 0}})
        self.assertEqual(chosen['layer'], 'framework')

    def test_structure_layer_alone_does_not_override_the_mapping(self):
        # Layout é o último recurso: sozinho não pode reescrever o mapeamento,
        # porque alternância inventa papéis quando o site foge do padrão.
        chosen = choose_reading({'layered': {'layer': 'structure', 'items': items(2)},
                                 'configured': {'items': [{'role': 'user', 'text': 'só pergunta'}], 'overlap': 0}})
        self.assertEqual(chosen['layer'], 'configured')
        self.assertFalse(chosen['fallback'])

    def test_unbalanced_layered_reading_does_not_override(self):
        chosen = choose_reading({'layered': {'layer': 'marker', 'items': pair(1) + pair(2)[:1]},
                                 'configured': {'items': [{'role': 'user', 'text': 'x'}], 'overlap': 0}})
        self.assertEqual(chosen['layer'], 'configured')

    def test_unknown_payload_shape_is_tolerated(self):
        self.assertEqual(choose_reading(None)['items'], [])
        self.assertEqual(choose_reading({'layered': {'layer': 'nada'}, 'configured': None})['items'], [])


class TestReport(unittest.TestCase):
    class Page:
        def __init__(self, payload):
            self.payload = payload

        def evaluate(self, *_args, **_kwargs):
            return self.payload

    def test_legacy_report_shape_still_normalizes(self):
        found = report(self.Page({'overlap': 0, 'items': items(2)}), 'u', 'a')
        self.assertEqual(len(found['items']), 4)
        self.assertEqual(found['layer'], 'none')

    def test_layer_payload_is_resolved(self):
        found = report(self.Page({'layered': {'layer': 'marker', 'items': items(2)},
                                  'configured': {'items': [], 'overlap': 0}}), 'u', 'a')
        self.assertEqual(found['layer'], 'marker')
        self.assertEqual(summarize(found)['answers'], 2)

    def test_page_that_raises_returns_empty_report(self):
        class Broken:
            def evaluate(self, *_args, **_kwargs):
                raise RuntimeError('página fechada')

        found = report(Broken(), 'u', 'a')
        self.assertEqual(found['items'], [])
        self.assertEqual(summarize(found)['total'], 0)

    def test_no_page_is_not_an_exception(self):
        self.assertEqual(report(None)['items'], [])

    def test_text_is_collapsed_and_bounded(self):
        found = report(self.Page({'overlap': 0, 'items': [
            {'role': 'user', 'text': 'a\n\n b   c'}, {'role': 'assistant', 'text': 'r'}]}), 'u', 'a')
        self.assertEqual(found['items'][0]['text'], 'a b c')

    def test_invalid_role_is_ignored(self):
        found = report(self.Page({'overlap': 0, 'items': [
            {'role': 'system', 'text': 'x'}, {'role': 'user', 'text': 'y'}]}), 'u', 'a')
        self.assertEqual([item['role'] for item in found['items']], ['user'])


class TestUserState(unittest.TestCase):
    class Page:
        def __init__(self, value):
            self.value = value

        def evaluate(self, *_args, **_kwargs):
            return self.value

    def test_layer_is_reported(self):
        state = user_state(self.Page({'count': 2, 'last': 'pergunta', 'layer': 'marker'}), '.u')
        self.assertEqual(state, {'count': 2, 'last': 'pergunta', 'layer': 'marker'})

    def test_garbage_is_normalized_to_empty(self):
        self.assertEqual(user_state(self.Page({'count': 'x', 'last': 3}), ''), {'count': 0, 'last': None, 'layer': 'none'})
        self.assertEqual(user_state(self.Page(None), ''), {'count': 0, 'last': None, 'layer': 'none'})

    def test_script_reads_three_layers_and_never_writes(self):
        for marker in ('marker', 'framework', 'structure'):
            self.assertIn(marker, CAPTURE_SCRIPT)
        for forbidden in ('.click()', 'dispatchEvent', 'innerHTML =', 'insertAdjacentHTML'):
            self.assertNotIn(forbidden, CAPTURE_SCRIPT)


if __name__ == '__main__':
    unittest.main()
