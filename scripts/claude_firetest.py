#!/usr/bin/env python3
"""Teste de fogo: o Claude Code **de verdade** contra esta API, sem conta real.

Por que existe: a suíte sintética não descobre o que o binário real faz — foi um
teste assim que mostrou que `output_config` derrubaria o primeiro pedido e que um
400 `prompt is too long` encerra a sessão em vez de ser tratado. Aqui o CLI roda
apontado para `127.0.0.1`, e quem responde do outro lado é um **chat simulado**
com os limites de um chat de verdade (campo de ~20 mil caracteres, janela de
~60 mil, página que demora a carregar e recusa o que passaria do limite).

O navegador não é aberto: o que se testa é o contrato com o CLI e as janelas de
contexto, não o Playwright (isso é o CI de navegador).

Uso:
    python scripts/claude_firetest.py                # exige o binário `claude`
    python scripts/claude_firetest.py --no-cli       # só o chat simulado
    python scripts/claude_firetest.py --claude /caminho/do/claude

Códigos de saída: 0 sucesso, 1 falha de verdade, 3 binário ausente.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from browserapi_lab import conversation as windows            # noqa: E402
from browserapi_lab.chat import ChatResult                    # noqa: E402
from browserapi_lab.config import ChatConfig, ConfigStore     # noqa: E402
from browserapi_lab.gui import Panel                          # noqa: E402
from browserapi_lab.llm_api import APIService, WarmBrowser    # noqa: E402
from browserapi_lab.setup import HYPOTHESES                   # noqa: E402


class FakePage:
    """Página mínima: o worker real só precisa de URL, prontidão e recarga."""

    def __init__(self):
        self.url = 'https://chat.example/conversa'
        self.reloads = 0

    def is_closed(self):
        return False

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, ms):
        pass

    def reload(self, *a, **kw):
        self.reloads += 1

    def goto(self, url, **kw):
        self.url = url

    def locator(self, selector):
        class _L:
            def count(self):
                return 1

            def is_visible(self):
                return True

            def is_editable(self):
                return True
        return _L()


class FakeSession:
    def __init__(self, config=None):
        self.context = type('Ctx', (), {'pages': [FakePage()]})()
        self.context.route = lambda *a, **kw: None
        self.context.new_page = lambda url=None: FakePage()
        self.page_ = FakePage()

    def start(self):
        pass

    def page(self, url=None):
        return self.page_

    def new_page(self, url=None):
        return FakePage()

    def close(self):
        pass


class SimulatedSite:
    """Chat web de mentira, com os limites do de verdade.

    Ele **recusa** o que um chat real recusaria (texto acima do campo, conversa
    acima da janela) e, na primeira requisição, simula a página ainda carregando
    — o defeito do relato (“manda antes de carregar e diz que não funciona”).
    """

    def __init__(self, limits, not_ready=0, tool=True):
        self.limits = limits
        self.remaining_not_ready = not_ready
        self.tool = tool
        self.received = []
        self.refused = []
        self.not_ready_hits = 0
        self.conversation = []

    # o worker chama isto no lugar da página de verdade
    def __call__(self, page, config, text, *, authorized=False, health_check=False,
                 cancelled=None):
        if self.remaining_not_ready > 0:
            self.remaining_not_ready -= 1
            self.not_ready_hits += 1
            return ChatResult('composer_missing', send_state='not_sent')
        if len(text) > self.limits.message_chars:
            self.refused.append({'send': len(text), 'conversation': sum(map(len, self.conversation)),
                                 'why': 'texto maior que o campo'})
            return ChatResult('send_unconfirmed', send_state='confirmed')
        if sum(map(len, self.conversation)) + len(text) > self.limits.conversation_chars:
            self.refused.append({'send': len(text),
                                 'conversation': sum(map(len, self.conversation)),
                                 'why': 'conversa passaria da janela'})
            return ChatResult('send_unconfirmed', send_state='confirmed')
        self.received.append(text)
        self.conversation.append(text)
        return ChatResult('success', True, answer=self.answer(text), send_state='confirmed')

    def answer(self, text):
        flat = text.lower()
        if '[parte ' in flat and 'não responda' in flat:
            return 'recebido'
        if '[continuação]' in flat:
            return 'continuação do texto'
        if self.tool and ('tool_result' in flat or 'resultado da ferramenta' in flat):
            return 'O comando rodou e devolveu: fire-test'
        if self.tool and ('rode o comando' in flat or 'use a ferramenta' in flat):
            return ('{"tool_calls":[{"name":"Bash","arguments":'
                    '{"command":"echo fire-test","description":"teste de fogo"}}]}')
        return 'OK do chat simulado'


class FireWarm(WarmBrowser):
    """Worker real (prontidão, blocos, repetição, continuação) com página falsa."""

    site: SimulatedSite
    last: dict = {}

    def open_page(self, config, headless, light, cancelled):
        self.session = FakeSession(config)
        self.page = self.session.page(config.url)
        self.key = ('fake', headless, light)
        return 0.0, 0.0

    def wait_ready(self, page, config, cancelled, seconds=None):
        return True, ''

    def rotate(self, config, cancelled):
        self.site.conversation = []
        return True

    def run(self, job, cancelled):
        super().run(job, cancelled)
        type(self).last = {'mode': job.plan_report.get('mode'),
                           'sends': len(job.sends), 'characters': job.characters,
                           'rotate': job.rotate, 'blocks': job.blocks,
                           'site_conversation': sum(map(len, self.site.conversation))}


def run_cli(claude, port, key, prompt, home, extra=()):
    env = dict(os.environ)
    env.update({
        'HOME': str(home),
        'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{port}',
        'ANTHROPIC_AUTH_TOKEN': key,
        'ANTHROPIC_MODEL': 'meu-agente',
        'CLAUDE_CODE_MAX_OUTPUT_TOKENS': '8000',
        'DISABLE_AUTOUPDATER': '1',
        'DISABLE_TELEMETRY': '1',
        'DISABLE_ERROR_REPORTING': '1',
    })
    command = [claude, '-p', prompt, '--output-format', 'json', *extra]
    started = time.time()
    done = subprocess.run(command, env=env, capture_output=True, text=True, timeout=300)
    payload = None
    for line in reversed((done.stdout or '').strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    return {'exit': done.returncode, 'seconds': round(time.time() - started, 2),
            'result': payload, 'stderr': (done.stderr or '')[-2000:]}


def merge(state, out):
    state['site_sends'] += len(state.setdefault('_pending', [])) if False else 0
    state['tool_round_trips'] += 1 if out.get('num_turns', 1) > 1 else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claude', default=os.environ.get('CLAUDE_BIN') or
                        shutil.which('claude') or '')
    parser.add_argument('--no-cli', action='store_true',
                        help='não roda o binário; exercita só o chat simulado')
    parser.add_argument('--output', default=str(ROOT / 'results/ci/claude-firetest.json'))
    args = parser.parse_args()

    limits = windows.Limits(message_chars=20_000, conversation_chars=60_000, block_chars=8_000)
    site = SimulatedSite(limits, not_ready=2)
    evidence = {'scope': 'synthetic_chat_real_claude_code', 'limits': limits.as_dict(),
                'claude': args.claude or None, 'steps': []}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = ConfigStore(root / 'config')
        config = ChatConfig('meu-agente', 'https://chat.example/', **HYPOTHESES['fixture'])
        store.save(config)
        store.save_status('meu-agente', ChatResult('success', True).receipt(config))
        panel = Panel(store, root / 'data')
        warm = FireWarm(store)
        warm.site = site
        panel.warm = warm
        api = APIService(panel, port=0)
        panel.api_service = api
        api.configure({'enabled': True, 'names': ['meu-agente'], 'headless': True})
        port = api.server.server_port
        key = api.state['key']
        evidence['port'] = port
        try:
            with patch('browserapi_lab.llm_api.exchange', side_effect=site):
                if args.claude and not args.no_cli:
                    steps = [
                        ('pergunta simples', 'responda apenas OK', ()),
                        ('ferramenta', 'use a ferramenta para ver o sistema', ('--allowedTools', 'Bash')),
                        ('continuação da sessão', 'e agora escreva um texto longo',
                         ('--allowedTools', 'Bash', '--continue')),
                    ]
                else:
                    steps = []
                for name, prompt, extra in steps:
                    before = len(site.received)
                    out = run_cli(args.claude, port, key, prompt, root / 'home', extra)
                    sends = site.received[before:]
                    step = {'step': name, 'exit': out['exit'], 'seconds': out['seconds'],
                            'is_error': (out['result'] or {}).get('is_error'),
                            'num_turns': (out['result'] or {}).get('num_turns'),
                            'result': ((out['result'] or {}).get('result') or '')[:200],
                            'site_sends': len(sends),
                            'largest_send': max((len(s) for s in sends), default=0),
                            'terminal_reason': (out['result'] or {}).get('terminal_reason'),
                            'plan': dict(FireWarm.last),
                            'stderr': out['stderr'][-400:] if out['exit'] else ''}
                    evidence['steps'].append(step)
                    print(f"[{name}] exit={step['exit']} turnos={step['num_turns']} "
                          f"envios={step['site_sends']} maior={step['largest_send']} "
                          f"motivo={step['terminal_reason']} plano={step['plan']} "
                          f"-> {step['result'][:80]}")
                    if out['exit'] != 0 or step['is_error']:
                        print('FALHOU: o CLI não completou o passo.')
                        evidence['ok'] = False
                        return finish(evidence, args.output, 1)
                if not steps:
                    # Sem o binário: exercita o mesmo caminho pela API HTTP.
                    import http.client
                    body = {'model': 'meu-agente', 'max_tokens': 8000,
                            'system': [{'type': 'text', 'text': 'agente de terminal ' * 400}],
                            'tools': [{'name': 'Bash', 'description': 'roda comando ' * 200,
                                       'input_schema': {'type': 'object',
                                                        'properties': {'command': {'type': 'string'}}}}],
                            'messages': [{'role': 'user', 'content': 'use a ferramenta'}],
                            'output_config': {'effort': 'medium'},
                            'thinking': {'type': 'enabled'}, 'context_management': {'edits': []}}
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=120)
                    connection.request('POST', '/v1/messages', json.dumps(body),
                                       {'Content-Type': 'application/json', 'x-api-key': key})
                    response = connection.getresponse()
                    raw = response.read().decode()
                    connection.close()
                    value = json.loads(raw)
                    evidence['steps'].append({'step': 'http_v1_messages', 'status': response.status,
                                              'stop_reason': value.get('stop_reason'),
                                              'mode': value['browserapi']['window']['mode']})
                    print(f"[http /v1/messages] status={response.status} "
                          f"stop={value.get('stop_reason')} janela={value['browserapi']['window']['mode']}")
                    if response.status != 200:
                        evidence['ok'] = False
                        return finish(evidence, args.output, 1)
            evidence.update({
                'site_sends': len(site.received),
                'site_refused': site.refused,
                'largest_send': max((len(s) for s in site.received), default=0),
                'site_conversation_characters': sum(map(len, site.conversation)),
                'not_ready_hits': site.not_ready_hits,
                'limits_respected': not site.refused,
            })
            print(f"envios ao site={len(site.received)} maior={evidence['largest_send']} "
                  f"recusas={len(site.refused)} página_lenta={site.not_ready_hits}")
            evidence['ok'] = not site.refused
            return finish(evidence, args.output, 0 if evidence['ok'] else 1)
        finally:
            api.close()
            panel.close()


def finish(evidence, path, code):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    print('ok' if code == 0 else 'FALHOU', '->', target)
    return code


if __name__ == '__main__':
    sys.exit(main())
