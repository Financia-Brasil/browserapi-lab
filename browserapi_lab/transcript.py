"""Conversa exibida no painel: memória do processo, nunca disco.

Este módulo não é histórico do site, não é o RAG da API local (``context.py``)
e não entra em recibos, telemetria ou relatórios. Reiniciar o programa apaga o
conteúdo. Cada chat tem orçamento de mensagens e de caracteres; o turno mais
antigo é descartado primeiro, sempre em par (pergunta e resposta), para não
deixar metade de uma troca na tela. O turno mais novo é sempre preservado,
mesmo quando ele sozinho passa do orçamento — nesse caso o texto é cortado com
aviso visível, nunca truncado em silêncio.
"""

from __future__ import annotations

from collections import deque
import math
import re
import threading
import time

from .config import safe_name

MAX_ENTRIES = 40
MAX_CHARACTERS = 120_000
MAX_TEXT = 40_000
MARKER = '\n\n[O painel cortou o excesso deste texto. A página do chat mantém o restante.]'
STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')


def _stamp(at=None):
    if isinstance(at, str) and STAMP.fullmatch(at):
        return at
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _text(value, label):
    if not isinstance(value, str):
        raise ValueError(f'{label} inválida.')
    value = value.replace('\x00', '')
    if not value.strip():
        raise ValueError(f'{label} vazia.')
    if len(value) > MAX_TEXT:
        return value[:MAX_TEXT].rstrip() + MARKER
    return value


def _milliseconds(value):
    if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 86_400_000:
        return round(float(value), 1)
    return None


class Transcript:
    """Uma conversa em memória por nome de conexão. Sem escrita em arquivo."""

    def __init__(self, max_entries=MAX_ENTRIES, max_characters=MAX_CHARACTERS):
        if type(max_entries) is not int or not 2 <= max_entries <= 400:
            raise ValueError('Limite de mensagens inválido.')
        if type(max_characters) is not int or not 1_000 <= max_characters <= 2_000_000:
            raise ValueError('Limite de caracteres inválido.')
        self.max_entries = max_entries
        self.max_characters = max_characters
        self.entries: dict[str, deque] = {}
        self.dropped: dict[str, int] = {}
        self.revisions: dict[str, int] = {}
        self.lock = threading.RLock()

    def _queue(self, name):
        return self.entries.setdefault(name, deque())

    def _drop_turn(self, name, queue):
        # Sempre remove um par; um turno sozinho só sai se for o único.
        count = 2 if len(queue) >= 2 else 1
        for _ in range(count):
            queue.popleft()
        self.dropped[name] = self.dropped.get(name, 0) + count

    def _trim(self, name, queue):
        def characters():
            return sum(len(entry['text']) for entry in queue)
        # Preserva a última pergunta/resposta mesmo acima do orçamento.
        while len(queue) > 2 and (len(queue) > self.max_entries or characters() > self.max_characters):
            self._drop_turn(name, queue)

    def add_exchange(self, name, question, answer, *, at=None, total_ms=None):
        """Registra um turno completo de forma atômica: nunca só metade dele."""
        safe_name(name)
        question = _text(question, 'Pergunta')
        answer = _text(answer, 'Resposta')
        stamp = _stamp(at)
        elapsed = _milliseconds(total_ms)
        with self.lock:
            queue = self._queue(name)
            queue.append({'role': 'user', 'text': question, 'at': stamp, 'total_ms': None})
            queue.append({'role': 'assistant', 'text': answer, 'at': stamp, 'total_ms': elapsed})
            self._trim(name, queue)
            self.revisions[name] = self.revisions.get(name, 0) + 1
            return len(queue)

    def clear(self, name):
        """Remove só o que este painel mostrou; não altera a conversa do site."""
        safe_name(name)
        with self.lock:
            removed = len(self.entries.pop(name, ()))
            self.dropped.pop(name, None)
            self.revisions[name] = self.revisions.get(name, 0) + 1
            return removed

    def summary(self, name):
        """Resumo pequeno para o estado do painel: sem o texto da conversa."""
        safe_name(name)
        with self.lock:
            queue = self.entries.get(name, ())
            return {'turns': sum(1 for entry in queue if entry['role'] == 'user'),
                    'revision': self.revisions.get(name, 0),
                    'characters': sum(len(entry['text']) for entry in queue),
                    'dropped': self.dropped.get(name, 0),
                    'limits': {'entries': self.max_entries, 'characters': self.max_characters}}

    def snapshot(self, name):
        safe_name(name)
        with self.lock:
            queue = self.entries.get(name, ())
            return {'name': name, 'revision': self.revisions.get(name, 0),
                    'messages': [dict(entry) for entry in queue],
                    'messages_total': len(queue) + self.dropped.get(name, 0),
                    'dropped': self.dropped.get(name, 0),
                    'characters': sum(len(entry['text']) for entry in queue),
                    'limits': {'entries': self.max_entries, 'characters': self.max_characters,
                               'text': MAX_TEXT},
                    'scope': 'Somente a memória desta execução; não é histórico do site nem recibo.'}
