"""Emulação de ferramentas: protocolo de texto e leitura tolerante.

Sem função nativa no chat do navegador, o que o modelo escreveu é interpretado
aqui. As regras duras: nome precisa existir na lista e argumentos precisam ser
objeto JSON — o resto é texto e quem decide é o agente do outro lado.
"""
import json
import unittest

from browserapi_lab import tool_calls

TOOLS = [
    {'name': 'Read', 'description': 'lê um arquivo', 'schema': {'type': 'object'}},
    {'name': 'Bash', 'description': 'executa um comando', 'schema': {'type': 'object'}},
]


class TestToolProtocol(unittest.TestCase):
    def test_prompt_lists_names_and_refuses_to_invent(self):
        text = tool_calls.protocol_prompt(TOOLS)
        self.assertIn('Read', text)
        self.assertIn('Bash', text)
        self.assertIn('{"tool_calls"', text)
        self.assertEqual(tool_calls.protocol_prompt([]), '')

    def test_forced_tool_choice_is_stated(self):
        text = tool_calls.protocol_prompt(TOOLS, {'type': 'tool', 'name': 'Read'})
        self.assertIn('Read', text)
        self.assertIn('obrigatoriamente', text)

    def test_tool_schema_accepts_both_dialects(self):
        anthropic = tool_calls.normalize_tools([
            {'name': 'Read', 'description': 'x', 'input_schema': {'type': 'object'}}])
        openai = tool_calls.normalize_tools([
            {'type': 'function', 'function': {'name': 'Read', 'description': 'x',
                                              'parameters': {'type': 'object'}}}])
        self.assertEqual(anthropic[0]['name'], openai[0]['name'])
        self.assertEqual(anthropic[0]['schema'], {'type': 'object'})


class TestParsing(unittest.TestCase):
    def test_plain_text_is_not_a_tool_call(self):
        parsed = tool_calls.parse('A capital é Belém.', TOOLS)
        self.assertEqual(parsed.text, 'A capital é Belém.')
        self.assertFalse(parsed.used_tool)

    def test_json_without_tools_declared_stays_text(self):
        raw = '{"tool_calls":[{"name":"Read","arguments":{}}]}'
        self.assertEqual(tool_calls.parse(raw, []).text, raw)

    def test_fenced_single_call(self):
        parsed = tool_calls.parse('```json\n{"name":"Read","arguments":{"path":"a.txt"}}\n```', TOOLS)
        self.assertEqual(parsed.text, '')
        self.assertEqual(parsed.calls[0]['name'], 'Read')
        self.assertEqual(parsed.calls[0]['input'], {'path': 'a.txt'})
        self.assertTrue(parsed.calls[0]['id'].startswith('toolu_'))

    def test_multiple_calls_and_surrounding_text(self):
        raw = ('Vou verificar.\n'
               '{"tool_calls":[{"name":"Read","arguments":{"path":"a"}},'
               '{"name":"Bash","arguments":{"command":"ls"}}]}\n'
               'Depois disso, decido.')
        parsed = tool_calls.parse(raw, TOOLS)
        self.assertEqual([call['name'] for call in parsed.calls], ['Read', 'Bash'])
        self.assertIn('Vou verificar.', parsed.text)
        self.assertIn('Depois disso', parsed.text)
        self.assertNotIn('tool_calls', parsed.text)

    def test_arguments_as_json_string(self):
        parsed = tool_calls.parse('{"name":"Bash","arguments":"{\\"command\\":\\"ls\\"}"}', TOOLS)
        self.assertEqual(parsed.calls[0]['input'], {'command': 'ls'})

    def test_unknown_tool_never_becomes_a_call(self):
        parsed = tool_calls.parse('{"tool_calls":[{"name":"DeleteEverything","arguments":{}}]}', TOOLS)
        self.assertFalse(parsed.used_tool)
        self.assertIn('DeleteEverything', parsed.text)

    def test_broken_json_is_text(self):
        parsed = tool_calls.parse('{"tool_calls":[{"name":"Read",', TOOLS)
        self.assertFalse(parsed.used_tool)

    def test_case_insensitive_name_matches_declared_tool(self):
        parsed = tool_calls.parse('{"tool_calls":[{"name":"read","arguments":{}}]}', TOOLS)
        self.assertEqual(parsed.calls[0]['name'], 'Read')

    def test_arguments_must_be_object(self):
        parsed = tool_calls.parse('{"tool_calls":[{"name":"Read","arguments":[1,2]}]}', TOOLS)
        self.assertFalse(parsed.used_tool)

    def test_nothing_happens_with_empty_answer(self):
        parsed = tool_calls.parse('', TOOLS)
        self.assertEqual(parsed.text, '')
        self.assertFalse(parsed.used_tool)

    def test_transcript_lines_carry_call_and_result(self):
        call = tool_calls.transcript_line('call', 'Bash', {'command': 'ls'})
        result = tool_calls.transcript_line('result', 'Bash', 'a.txt')
        self.assertIn('chamada de ferramenta Bash', call)
        self.assertIn('ls', call)
        self.assertIn('resultado da ferramenta', result)
        self.assertIn('a.txt', result)
        self.assertIn('erro', tool_calls.transcript_line('result', 'Bash', 'falhou', is_error=True))


if __name__ == '__main__':
    unittest.main()
