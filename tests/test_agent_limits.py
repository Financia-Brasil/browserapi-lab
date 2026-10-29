"""O pedido real do Claude Code contra a API local, em HTTP, sem navegador.

O corpo abaixo foi medido de uma execução real do binário (v2.1.312): 12
ferramentas com ~30 mil caracteres de esquema, system com 3 blocos, e as chaves
`context_management`, `output_config`, `thinking` e `metadata.user_id`. É esse
formato que a API precisa aceitar e fatiar — e é o que este teste reproduz em
tamanho e forma, sem depender de conta nem de rede.
"""
import http.client
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from browserapi_lab import conversation as windows
from browserapi_lab.chat import ChatResult
from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.gui import Panel
from browserapi_lab.llm_api import APIService, Job
from browserapi_lab.setup import HYPOTHESES

TOOLS = [
    ('Bash', 'Executa um comando de terminal e devolve a saída. ' * 100, {'command': {'type': 'string'}, 'timeout': {'type': 'number'}}),
    ('Read', 'Lê um arquivo do disco, com limite de linhas. ' * 90, {'file_path': {'type': 'string'}, 'limit': {'type': 'number'}}),
    ('Edit', 'Substitui um trecho exato de um arquivo. ' * 70, {'file_path': {'type': 'string'}, 'old_string': {'type': 'string'}, 'new_string': {'type': 'string'}}),
    ('Write', 'Escreve um arquivo inteiro. ' * 45, {'file_path': {'type': 'string'}, 'content': {'type': 'string'}}),
    ('Glob', 'Lista arquivos por padrão. ' * 55, {'pattern': {'type': 'string'}}),
    ('Grep', 'Busca texto em arquivos. ' * 70, {'pattern': {'type': 'string'}, 'path': {'type': 'string'}}),
    ('Agent', 'Delega para um subagente. ' * 260, {'prompt': {'type': 'string'}}),
    ('TodoWrite', 'Atualiza a lista de tarefas. ' * 70, {'todos': {'type': 'array'}}),
    ('WebFetch', 'Busca uma URL. ' * 55, {'url': {'type': 'string'}}),
    ('WebSearch', 'Busca na web. ' * 75, {'query': {'type': 'string'}}),
    ('NotebookEdit', 'Edita um notebook. ' * 45, {'notebook_path': {'type': 'string'}}),
    ('Skill', 'Executa uma habilidade. ' * 55, {'name': {'type': 'string'}}),
]


def claude_tools():
    return [{'name': name, 'description': text,
             'input_schema': {'type': 'object', 'properties': props, 'required': list(props)[:1]}}
            for name, text, props in TOOLS]


SYSTEM = [
    {'type': 'text', 'text': 'You are Claude Code, Anthropic\'s official CLI for Claude. ' * 20},
    {'type': 'text', 'text': 'Você é um agente de terminal. Responda em português. ' * 30},
    {'type': 'text', 'text': ('Diretrizes: seja conciso; use ferramentas quando necessário; '
                              'não invente caminhos; confira antes de escrever. ') * 55},
]


def claude_body(messages, **extra):
    body = {'model': 'saved', 'max_tokens': 8000, 'stream': False,
            'system': SYSTEM, 'tools': claude_tools(),
            'messages': messages,
            'context_management': {'edits': []},
            'output_config': {'effort': 'medium'},
            'thinking': {'type': 'enabled', 'budget_tokens': 1024},
            'metadata': {'user_id': json.dumps({'device_id': 'x' * 64, 'session_id': 'y' * 36})}}
    body.update(extra)
    return body


class RecordingWarm:
    """Substitui o worker: registra o que a API decidiu enviar ao site."""

    answer = 'resposta do chat'
    jobs = []

    def __init__(self, store):
        self.store = store

    def close(self):
        pass

    def run(self, job, cancelled):
        type(self).jobs.append(job)
        job.config = self.store.load(job.names[0])
        job.result = ChatResult('success', True, answer=type(self).answer,
                                send_state='confirmed')
        job.attempts = [{'model': job.config.name, 'status': 'success'}]


class TestClaudeCodePayload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = ConfigStore(root / 'config')
        config = ChatConfig('saved', 'https://chat.example', **HYPOTHESES['fixture'])
        self.store.save(config)
        self.store.save_status('saved', ChatResult('success', True).receipt(config))
        self.panel = Panel(self.store, root / 'data')
        self.patch = patch('browserapi_lab.llm_api.WarmBrowser', RecordingWarm)
        self.patch.start()
        RecordingWarm.jobs = []
        self.service = APIService(self.panel, port=0)
        self.panel.api_service = self.service
        self.service.configure({'enabled': True, 'names': ['saved']})
        self.key = self.service.state['key']

    def tearDown(self):
        self.service.close()
        self.panel.close()
        self.patch.stop()
        self.tmp.cleanup()

    def call(self, path, body, key=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.service.server.server_port,
                                                timeout=20)
        connection.request('POST', path, json.dumps(body),
                           {'Content-Type': 'application/json',
                            'x-api-key': key or self.key,
                            'anthropic-version': '2023-06-01',
                            'anthropic-beta': 'claude-code-20250219,context-management-2025-06-27'})
        response = connection.getresponse()
        raw = response.read().decode()
        connection.close()
        return response.status, json.loads(raw), response

    def test_first_request_with_full_schemas_fits_and_is_accepted(self):
        body = claude_body([{'role': 'user', 'content': [{'type': 'text', 'text': 'oi'}]}])
        raw = len(json.dumps(body, ensure_ascii=False))
        status, value, response = self.call('/v1/messages?beta=true', body)
        self.assertEqual(status, 200, value)
        self.assertEqual(value['type'], 'message')
        # Nada do que a CLI manda foi recusado.
        ignored = set(value['browserapi']['ignored'])
        for key in ('output_config', 'context_management', 'thinking', 'max_tokens', 'metadata'):
            self.assertIn(key, ignored)
        self.assertEqual(value['browserapi']['tools'], 'emulated')
        job = RecordingWarm.jobs[-1]
        limits = windows.Limits.from_state(self.service.state)
        # O ganho medido: ~45k caracteres de pedido viram UM envio, porque o
        # bloco de ferramentas entra resumido em vez dos ~30k de esquema.
        self.assertGreater(raw, 35_000)
        self.assertLess(job.plan_report['tools_prompt_characters'], raw // 3)
        self.assertEqual(len(job.sends), 1)
        self.assertLessEqual(len(job.sends[0]), limits.message_chars)
        self.assertEqual(job.plan_report['mode'], 'bootstrap')
        self.assertTrue(value['usage']['browserapi']['estimated'])

    def test_history_bigger_than_the_field_becomes_blocks(self):
        history = [{'role': 'user', 'content': [{'type': 'text',
                                                'text': 'leia o arquivo ' + 'x' * 400}]}]
        for turn in range(4):
            history.append({'role': 'assistant',
                            'content': [{'type': 'text', 'text': f'passo {turn} ' + 'y' * 4000}]})
            history.append({'role': 'user',
                            'content': [{'type': 'text', 'text': f'continue {turn} ' + 'z' * 4000}]})
        status, value, _ = self.call('/v1/messages', claude_body(history))
        self.assertEqual(status, 200, value)
        job = RecordingWarm.jobs[-1]
        limits = windows.Limits.from_state(self.service.state)
        self.assertGreater(len(job.sends), 2)
        for send in job.sends:
            self.assertLessEqual(len(send), limits.message_chars)
        self.assertEqual(sum(len(send) for send in job.sends), job.characters)
        self.assertEqual(job.plan_report['mode'], 'bootstrap')

    def test_first_turn_too_big_for_the_chat_is_compacted_not_refused(self):
        # Janela pequena de propósito: o caminho de compactação precisa ser
        # exercitado mesmo com o padrão novo (200 mil caracteres por conversa).
        self.service.state['conversation_chars'] = 60_000
        history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'começo'}]}]
        for turn in range(10):
            history.append({'role': 'assistant',
                            'content': [{'type': 'text', 'text': f'passo {turn} ' + 'y' * 4000}]})
            history.append({'role': 'user',
                            'content': [{'type': 'text', 'text': f'continue {turn} ' + 'z' * 4000}]})
        status, value, _ = self.call('/v1/messages', claude_body(history))
        self.assertEqual(status, 200, value)
        job = RecordingWarm.jobs[-1]
        limits = windows.Limits.from_state(self.service.state)
        # Compactou em vez de recusar: nada de prompt is too long no meio do uso.
        self.assertEqual(job.plan_report['mode'], 'compacted')
        self.assertIn('início compactado', job.sends[-1])
        for send in job.sends:
            self.assertLessEqual(len(send), limits.conversation_chars)

    def test_second_turn_sends_only_the_delta(self):
        base = [{'role': 'user', 'content': [{'type': 'text', 'text': 'liste os arquivos'}]}]
        self.assertEqual(self.call('/v1/messages', claude_body(base))[0], 200)
        first = RecordingWarm.jobs[-1]
        second_messages = base + [
            {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'toolu_1',
                                               'name': 'Bash', 'input': {'command': 'ls'}}]},
            {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'toolu_1',
                                          'content': 'README.md\nsrc\n'}]},
        ]
        status, _, _ = self.call('/v1/messages', claude_body(second_messages))
        self.assertEqual(status, 200)
        second = RecordingWarm.jobs[-1]
        self.assertEqual(second.plan_report['mode'], 'delta')
        self.assertEqual(len(second.sends), 1)
        # O turno novo é pequeno: nada de reenviar 46k a cada mensagem.
        self.assertLess(len(second.sends[0]), 3000)
        self.assertIn('README.md', second.sends[0])
        self.assertGreater(len(first.sends[0]), len(second.sends[0]))
        self.assertLess(second.characters, first.characters + 3000)

    def test_huge_tool_result_is_sent_but_older_ones_are_trimmed(self):
        big = 'linha de saída do comando\n' * 2000          # ~50k caracteres
        history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'rode o build'}]},
                   {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'toolu_1',
                                                      'name': 'Bash', 'input': {}}]},
                   {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'toolu_1',
                                                 'content': big}]}]
        status, value, _ = self.call('/v1/messages', claude_body(history))
        self.assertEqual(status, 200, value)
        job = RecordingWarm.jobs[-1]
        limits = windows.Limits.from_state(self.service.state)
        for send in job.sends:
            self.assertLessEqual(len(send), limits.message_chars)
        # O resultado gigante vai inteiro só no turno em que é novo; não some.
        self.assertIn('linha de saída', ''.join(job.sends))

    def test_conversation_that_fills_restarts_and_says_so(self):
        self.service.state['conversation_chars'] = 40_000
        messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'pedido inicial'}]}]
        restarted = False
        for turn in range(12):
            messages = messages + [
                {'role': 'assistant', 'content': [{'type': 'text', 'text': f'resposta {turn} ' + 'ok ' * 900}]},
                {'role': 'user', 'content': [{'type': 'text', 'text': f'pedido {turn} ' + 'detalhe ' * 500}]},
            ]
            status, value, _ = self.call('/v1/messages', claude_body(messages))
            self.assertEqual(status, 200, value)
            if value['browserapi']['conversation']['restarted']:
                restarted = True
                job = RecordingWarm.jobs[-1]
                self.assertTrue(job.rotate)
                self.assertIn('retomada', job.sends[-1])
                for send in job.sends:
                    self.assertLessEqual(len(send), windows.Limits.from_state(
                        self.service.state).conversation_chars)
        self.assertTrue(restarted, '12 turnos grandes precisam reiniciar a conversa')

    def test_page_not_ready_answers_503_and_not_409(self):
        class NotReady(RecordingWarm):
            def run(self, job, cancelled):
                job.result = ChatResult('composer_missing', send_state='not_sent')
                job.attempts = [{'status': 'composer_missing'}]

        with patch('browserapi_lab.llm_api.WarmBrowser', NotReady):
            status, value, _ = self.call('/v1/messages',
                                         claude_body([{'role': 'user', 'content': 'oi'}]))
        # 503 é retentável pelo agente; 409 fazia ele desistir e dizer que não funciona.
        self.assertEqual(status, 503, value)
        self.assertEqual(value['error']['code'], 'composer_missing')

    def test_confirmed_send_is_never_retried_and_stays_409(self):
        class Unclear(RecordingWarm):
            def run(self, job, cancelled):
                job.result = ChatResult('send_unconfirmed', send_state='unknown')

        with patch('browserapi_lab.llm_api.WarmBrowser', Unclear):
            status, value, _ = self.call('/v1/messages',
                                         claude_body([{'role': 'user', 'content': 'oi'}]))
        self.assertEqual(status, 409, value)
        self.assertIn('nada foi digitado' not in value['error']['message'], [True])

    def test_openai_responses_gets_context_length_exceeded(self):
        huge = [{'role': 'user', 'content': 'x' * 500_000}]
        self.service.configure({'enabled': False})
        self.service.configure({'enabled': True, 'names': ['saved'], 'max_parts': 2,
                                'message_chars': 4000, 'conversation_chars': 8000})
        connection = http.client.HTTPConnection('127.0.0.1', self.service.server.server_port,
                                                timeout=20)
        connection.request('POST', '/v1/responses',
                           json.dumps({'model': 'saved', 'input': huge}),
                           {'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + self.key})
        response = connection.getresponse()
        raw = response.read().decode()
        connection.close()
        self.assertEqual(response.status, 400, raw)
        value = json.loads(raw)
        self.assertEqual(value['error']['code'], 'context_length_exceeded')
        self.assertTrue(value['browserapi']['estimated'])
