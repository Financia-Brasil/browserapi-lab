"""Janelas do chat de navegador: blocos de entrada, saída em blocos e retomada.

O problema real (relato): uma CLI de agente manda **~46 mil caracteres antes da
primeira pergunta** (system prompt + 12 esquemas de ferramentas). O campo de
mensagem de um chat web aceita ~25–32 mil. Mandar assim, recusar, ou fingir que
coube — as três coisas quebram o uso.

Aqui ficam as contas, todas em **caracteres**:

* ``message_chars`` — teto de um envio; maior texto vira blocos numerados;
* ``conversation_chars`` — quanto a API acredita que já entregou à conversa do
  site; passando disso, a conversa é trocada e o contexto é **retomado**;
* ``block_chars``/``max_blocks`` — teto de uma resposta e quantas continuações
  são pedidas quando ela parece cortada.

Tokens são **estimativa declarada** (``4 caracteres ≈ 1 token``). O site não
informa contagem; zero faz o agente nunca compactar, e número exato seria
invenção. Ver ``docs/CONTEXT_WINDOWS.md`` para as medidas e o porquê.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace

CHAR_PER_TOKEN = 4

DEFAULT_MESSAGE_CHARS = 20_000
DEFAULT_CONVERSATION_CHARS = 200_000
DEFAULT_BLOCK_CHARS = 8_000
DEFAULT_MAX_BLOCKS = 4
DEFAULT_MAX_PARTS = 24
DEFAULT_RESTORE_CHARS = 14_000
DEFAULT_TOOL_RESULT_CHARS = 4_000
DEFAULT_KEEP_RECENT = 6

TOOL_RESULT_MARKS = ('[resultado da ferramenta', '[erro da ferramenta')


class WindowError(ValueError):
    """Contexto que não cabe nem depois de reduzir; vira erro do dialeto."""

    def __init__(self, message, code='context_length_exceeded', http=400):
        super().__init__(message)
        self.code, self.http = code, http


def estimate_tokens(characters):
    """Estimativa declarada; nunca uma medição do provedor."""
    if not isinstance(characters, int) or characters < 0:
        return 0
    return max(1, math.ceil(characters / CHAR_PER_TOKEN)) if characters else 0


@dataclass(frozen=True)
class Limits:
    """Tetos configuráveis. Valores fora da faixa são recusados, não ajustados."""

    message_chars: int = DEFAULT_MESSAGE_CHARS
    conversation_chars: int = DEFAULT_CONVERSATION_CHARS
    block_chars: int = DEFAULT_BLOCK_CHARS
    max_blocks: int = DEFAULT_MAX_BLOCKS
    max_parts: int = DEFAULT_MAX_PARTS
    restore_chars: int = DEFAULT_RESTORE_CHARS
    tool_result_chars: int = DEFAULT_TOOL_RESULT_CHARS
    keep_recent: int = DEFAULT_KEEP_RECENT

    def __post_init__(self):
        rules = {
            'message_chars': (4_000, 30_000),
            'conversation_chars': (8_000, 1_000_000),
            'block_chars': (1_000, 40_000),
            'max_blocks': (1, 12),
            'max_parts': (1, 40),
            'restore_chars': (2_000, 60_000),
            'tool_result_chars': (500, 40_000),
            'keep_recent': (2, 40),
        }
        for name, (low, high) in rules.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} precisa ser inteiro entre {low} e {high}')
        if self.message_chars > self.conversation_chars:
            raise ValueError('message_chars não pode ser maior que conversation_chars')

    @classmethod
    def from_state(cls, state):
        """Lê o estado do painel sem confiar nele (é arquivo em disco)."""
        values = {}
        for name in ('message_chars', 'conversation_chars', 'block_chars', 'max_blocks',
                     'max_parts', 'restore_chars', 'tool_result_chars', 'keep_recent'):
            raw = (state or {}).get(name)
            if raw is None:
                continue
            if type(raw) is not int:
                raise ValueError(f'{name} precisa ser um inteiro')
            values[name] = raw
        return cls(**values)

    def as_dict(self):
        return {name: getattr(self, name) for name in (
            'message_chars', 'conversation_chars', 'block_chars', 'max_blocks',
            'max_parts', 'restore_chars', 'tool_result_chars', 'keep_recent')}


def digest(text):
    return hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()[:32]


def clip(text, limit, *, head_ratio=0.7):
    """Corta o meio, não só o fim: o começo e o fim costumam ser o que importa."""
    if len(text) <= limit:
        return text
    marker = f'\n[reduzido localmente: {len(text) - limit} caracteres omitidos]\n'
    room = max(0, limit - len(marker))
    head = int(room * head_ratio)
    tail = room - head
    return text[:head] + marker + (text[-tail:] if tail else '')


def one_line(text, limit=160):
    flat = re.sub(r'\s+', ' ', text or '').strip()
    return flat if len(flat) <= limit else flat[:limit - 1] + '…'


def split_parts(text, limit, *, max_parts=99):
    """Divide em partes que respeitam parágrafos e, se preciso, cortam na linha."""
    if limit < 200:
        raise ValueError('limite de parte pequeno demais')
    if len(text) <= limit:
        return [text]
    parts, current = [], ''
    for paragraph in text.split('\n\n'):
        block = paragraph
        while block:
            room = limit - len(current) - (2 if current else 0)
            if room <= 0:
                parts.append(current)
                current, room = '', limit
                if len(parts) >= max_parts:
                    return _overflow(parts, block, text)
            if len(block) <= room:
                current = (current + '\n\n' + block) if current else block
                block = ''
            else:
                cut = block.rfind('\n', 0, room)
                if cut < room // 3:
                    cut = block.rfind(' ', 0, room)
                if cut < room // 3:
                    cut = room
                piece, block = block[:cut], block[cut:]
                current = (current + '\n\n' + piece) if current else piece
                parts.append(current)
                current = ''
                if len(parts) >= max_parts:
                    return _overflow(parts, block, text)
    if current:
        parts.append(current)
    return parts


def _overflow(parts, rest, text):
    """Passou de ``max_parts``: sinaliza para quem chamou reduzir, não cortar."""
    return parts + ['\u0000overflow:' + str(len(text))]


def looks_overflow(parts):
    return bool(parts) and parts[-1].startswith('\u0000overflow:')


def chunk_sends(text, limits, *, what='contexto'):
    """Transforma um texto grande em envios numerados com confirmação curta."""
    room = limits.message_chars - 200
    parts = split_parts(text, room, max_parts=limits.max_parts)
    if looks_overflow(parts):
        raise WindowError(f'O {what} não cabe em {limits.max_parts} blocos de '
                          f'{limits.message_chars} caracteres')
    if len(parts) == 1:
        return parts
    total = len(parts)
    sends = []
    for index, part in enumerate(parts, start=1):
        if index < total:
            head = (f'[parte {index}/{total} — {what}]\n'
                    f'NÃO responda ao conteúdo desta parte. Escreva apenas '
                    f'"recebido {index}/{total}".\n\n')
        else:
            head = (f'[parte {index}/{total} — {what}]\n'
                    f'Agora use todo o material acima e responda ao pedido final.\n\n')
        sends.append(head + part)
    return sends


def render(messages):
    return '\n\n'.join('[' + item['role'] + ']\n' + item['content'] for item in messages)


def _is_tool_result(item):
    text = item.get('content') or ''
    return item.get('role') != 'system' and text.startswith(TOOL_RESULT_MARKS)


def reduce_tool_results(messages, limits):
    """Resultado de ferramenta antigo não precisa ir inteiro de novo para o site.

    O mais recente fica inteiro (é o que o modelo está usando agora); os antigos
    são cortados em cabeça e cauda com marcador. Não é resumo: é corte declarado.
    """
    if not messages:
        return messages, {'trimmed': 0, 'characters': 0}
    recent_start = max(0, len(messages) - limits.keep_recent)
    total = trimmed = 0
    result = []
    for index, item in enumerate(messages):
        text = item.get('content') or ''
        if index < recent_start and _is_tool_result(item) and len(text) > limits.tool_result_chars:
            cut = clip(text, limits.tool_result_chars)
            total += len(text) - len(cut)
            trimmed += 1
            result.append({'role': item['role'], 'content': cut})
        else:
            result.append(item)
    return result, {'trimmed': trimmed, 'characters': total}


def restore_messages(messages, limits):
    """Compactação determinística para uma conversa nova: nada é inventado.

    System fica inteiro (até o teto). Os turnos recentes ficam inteiros. Os
    antigos viram uma linha cada, dizendo quantos foram omitidos. O pedido atual
    nunca é cortado.
    """
    if not messages:
        return [], {'omitted': 0, 'characters': 0}
    system = [item for item in messages if item['role'] == 'system']
    convo = [item for item in messages if item['role'] != 'system']
    keep = limits.keep_recent
    old = convo[:-keep] if len(convo) > keep else []
    recent = convo[-keep:] if keep else convo
    lines = []
    for item in old:
        if item['role'] == 'user':
            lines.append('- pedido anterior: ' + one_line(item['content'], 180))
    marker = []
    if old:
        marker = [{'role': 'system', 'content':
                   f'[retomada de contexto: {len(old)} turnos anteriores não vão inteiros; '
                   'os pedidos do usuário estão resumidos em uma linha cada]\n'
                   + ('\n'.join(lines[-40:]) if lines else '(sem pedidos anteriores)')}]
    result = system + marker + recent
    # Cabe no teto? Se não, encurta o marcador e depois os antigos, nunca o fim.
    while len(render(result)) > limits.restore_chars and len(marker) and lines:
        lines = lines[1:]
        marker[0]['content'] = ('[retomada de contexto: %d turnos anteriores; pedidos antigos '
                                'omitidos para caber]\n' % len(old)) + '\n'.join(lines[-20:])
        result = system + marker + recent
    while len(render(result)) > limits.restore_chars and len(recent) > 2:
        recent = recent[1:]
        result = system + marker + recent
    if len(render(result)) > limits.restore_chars:
        # Último recurso: corta o system, nunca o pedido atual.
        budget = max(2_000, limits.restore_chars // 2)
        result = [{'role': 'system', 'content': clip(item['content'], budget)}
                  for item in system] + marker + recent
    return result, {'omitted': len(old), 'characters': len(render(result))}


@dataclass
class Delivered:
    """O que a API acredita já ter entregue à conversa do site."""

    hashes: list = field(default_factory=list)
    characters: int = 0
    conversation: str = ''
    bootstrap: bool = False
    turns: int = 0


@dataclass
class TurnPlan:
    mode: str                      # 'bootstrap' | 'delta' | 'restore'
    sends: list
    rotate: bool = False
    report: dict = field(default_factory=dict)
    hashes: list = field(default_factory=list)
    characters: int = 0            # total acreditado depois deste turno

    @property
    def characters_sent(self):
        return sum(len(send) for send in self.sends)


def _with_protocol(messages, protocol):
    if not protocol:
        return list(messages)
    items = list(messages)
    index = 0
    while index < len(items) and items[index]['role'] == 'system':
        index += 1
    return items[:index] + [{'role': 'system', 'content': protocol}] + items[index:]


def plan_turn(messages, *, delivered=None, limits=Limits(), protocol='', reminder='',
              stateless=False):
    """Decide *o que* enviar neste turno: início, delta, ou retomada.

    Não abre navegador e não envia nada: é conta pura, testável sem Chromium.
    """
    if not messages:
        raise WindowError('Nenhuma mensagem para enviar', 'invalid_request', 400)
    reductions = {}
    messages, reductions = reduce_tool_results(messages, limits)
    hashes = [digest(item['role'] + '\0' + item['content']) for item in messages]
    report = {
        'input_characters': sum(len(item['content']) for item in messages),
        'reduced_characters': reductions['characters'],
        'trimmed_tool_results': reductions['trimmed'],
        'message_limit_characters': limits.message_chars,
        'conversation_limit_characters': limits.conversation_chars,
    }
    entry = delivered if isinstance(delivered, Delivered) else None
    prefix = 0
    if entry and entry.hashes:
        for old, new in zip(entry.hashes, hashes):
            if old != new:
                break
            prefix += 1

    if entry is None or not entry.bootstrap:
        return _bootstrap(messages, hashes, report, limits, protocol, stateless)
    fresh = None
    if prefix < len(entry.hashes):
        if len(messages) == 1 and messages[0]['role'] == 'user':
            # Cliente que manda SÓ a mensagem nova em cada pedido (o caso da
            # API OpenAI quando o cliente guarda o histórico do lado dele e
            # reescreve o contexto): não houve reescrita por compactação, é o
            # próximo turno. Tratar como retomada criava conversa nova a cada
            # pergunta e esvaziava o chat.
            report['reason'] = 'history_omitted'
            fresh = messages
        else:
            # O cliente reescreveu o histórico (compactação dele).
            report['reason'] = 'history_rewritten'
            return _restore(messages, hashes, report, limits, protocol)
    if fresh is None:
        if prefix >= len(messages):
            report['reason'] = 'no_new_message'
            return _restore(messages, hashes, report, limits, protocol)
        fresh = messages[prefix:]
    text = render(fresh)
    if reminder:
        text += '\n\n' + reminder
    if entry.characters + len(text) > limits.conversation_chars:
        report['reason'] = 'conversation_full'
        return _restore(messages, hashes, report, limits, protocol)
    sends = chunk_sends(text, limits, what='mensagem') if len(text) > limits.message_chars else [text]
    update = reductions['characters'] + len(text)
    return TurnPlan('delta', sends, rotate=False,
                    report={**report, 'mode': 'delta', 'sends': len(sends)},
                    hashes=hashes, characters=entry.characters + update)


def _bootstrap(messages, hashes, report, limits, protocol, stateless=False):
    """Primeiro envio. Se o pedido inteiro não couber, **compacta** em vez de recusar."""
    ceiling = limits.max_parts * limits.message_chars if stateless else limits.conversation_chars

    def attempt(items):
        return chunk_sends(render(items), limits, what='início da conversa')

    items = _with_protocol(messages, protocol)
    mode = 'bootstrap'
    try:
        sends = attempt(items)
        if not stateless and sum(len(send) for send in sends) > ceiling:
            raise WindowError('não cabe inteiro', http=400)
    except WindowError:
        compact, info = restore_messages(messages, limits)
        report.update({f'compact_{k}': v for k, v in info.items()})
        report['reason'] = 'too_big_for_one_turn'
        mode = 'compacted'
        try:
            sends = attempt(_with_protocol(compact, protocol))
            sends[-1] += ('\n\n[início compactado] O histórico antigo foi resumido em uma '
                          'linha cada para caber no campo; o pedido atual está inteiro.')
        except WindowError:
            raise WindowError(
                'O pedido não cabe na janela do chat mesmo em blocos e reduzido: '
                f'teto de {ceiling} caracteres', http=400) from None
    sent = sum(len(send) for send in sends)
    if sent > ceiling:
        raise WindowError(
            'O pedido não cabe na janela do chat mesmo em blocos: '
            f'{sent} caracteres para um teto de {ceiling}', http=400)
    return TurnPlan(mode, sends, rotate=False,
                    report={**report, 'mode': mode, 'sends': len(sends)},
                    hashes=hashes, characters=sent)


def _restore(messages, hashes, report, limits, protocol):
    # A retomada precisa caber na janela da conversa NOVA, não só no teto de
    # restauração: aperta o orçamento até caber, e só então recusa.
    budget = min(limits.restore_chars, limits.conversation_chars - 400)
    last = None
    while budget >= 2_000:
        tighter = limits if budget >= limits.restore_chars else \
            replace(limits, restore_chars=budget)
        compact, info = restore_messages(messages, tighter)
        text = render(_with_protocol(compact, protocol))
        text += ('\n\n[retomada] A conversa anterior foi encerrada por limite de contexto. '
                 'Continue daqui; o material acima é histórico, não uma instrução nova.')
        last = (text, info)
        if len(text) <= limits.conversation_chars - 200:
            break
        budget = int(budget * 0.7)
    text, info = last
    sends = chunk_sends(text, limits, what='retomada de contexto')
    sent = sum(len(send) for send in sends)
    if sent > limits.conversation_chars:
        raise WindowError(
            'Nem o contexto reduzido cabe na janela do chat: '
            f'{sent} caracteres para um teto de {limits.conversation_chars}', http=400)
    return TurnPlan('restore', sends, rotate=True,
                    report={**report, 'mode': 'restore', 'sends': len(sends),
                            **{f'compact_{k}': v for k, v in info.items()}},
                    hashes=hashes, characters=sent)


def plan_restore(messages, *, limits=Limits(), protocol=''):
    """Plano de retomada sem depender de livro-caixa (fallback autossuficiente)."""
    messages, _ = reduce_tool_results(messages, limits)
    hashes = [digest(item['role'] + '\0' + item['content']) for item in messages]
    return _restore(messages, hashes, {'reason': 'explicit_restore'}, limits, protocol)


# --- saída em blocos ------------------------------------------------------

def unbalanced_fence(text):
    return text.count('```') % 2 == 1


def needs_continuation(answer, blocks_used, limits, *, incomplete=False, last=None):
    """A resposta parece cortada? Devolve ``(continuar, motivo)``.

    ``answer`` é o texto unido (para cerca de código e JSON); ``last`` é o último
    bloco, que é o que diz se o site parou no teto. Olhar o texto unido fazia o
    turno pedir continuação para sempre.
    """
    if incomplete:
        return True, 'incomplete_tool_call'
    if not answer:
        return False, 'empty'
    if blocks_used >= limits.max_blocks:
        return False, 'max_blocks'
    if unbalanced_fence(answer):
        return True, 'open_code_fence'
    tail = answer if last is None else (last or '')
    if len(tail) >= int(limits.block_chars * 0.9):
        return True, 'block_limit'
    return False, 'natural'


CONTINUATION_PROMPT = ('[continuação] Continue exatamente de onde parou, sem repetir o que já '
                       'foi escrito e sem introdução. Se já terminou, escreva apenas: FIM.')


def merge_blocks(blocks):
    """Une blocos removendo a sobreposição que o modelo costuma repetir."""
    result = ''
    for block in blocks:
        block = block or ''
        if not result:
            result = block
            continue
        if block.strip().startswith('FIM') and len(block.strip()) <= 5:
            continue
        overlap = 0
        for size in range(min(len(result), len(block), 2000), 0, -1):
            if result.endswith(block[:size]):
                overlap = size
                break
        result += block[overlap:]
    return result


# --- falhas antes de digitar ---------------------------------------------

TRANSIENT = {'page_unavailable': 503, 'composer_missing': 503,
             'output_invalid': 503, 'browser_unavailable': 503,
             # O campo não aceitou o texto inteiro: NADA foi clicado, então
             # repetir é seguro (e a repetição pode achar outro caminho de colar).
             'composer_incomplete': 503}
ACTIONABLE = {'not_configured', 'wrong_origin', 'draft_present', 'send_is_microphone',
              'google_login_blocked', 'captcha', 'login_required',
              # Enviou pela metade: olhar a página antes de repetir.
              'send_truncated'}


def retryable_status(status, send_state):
    """Só o que aconteceu **antes** de digitar pode ser repetido."""
    return send_state == 'not_sent' and status in TRANSIENT


def http_for_status(status, send_state):
    """Código HTTP que o agente entende: 503 é retentável, 409 não é."""
    if status == 'rate_limit':
        return 429
    if status == 'timeout':
        return 504
    if retryable_status(status, send_state):
        return 503
    if status in ACTIONABLE:
        return 409
    return 409


# --- erros no vocabulário do cliente -------------------------------------

def dialect_error(kind, characters, limits, *, note=''):
    """Traduz “não cabe” para a frase que o cliente sabe interpretar."""
    estimated = estimate_tokens(characters)
    window = limits.conversation_chars
    message = f'prompt is too long: {estimated} tokens > {estimate_tokens(window)} maximum'
    payload = {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': message}}
    if kind != 'anthropic':
        payload = {'error': {'message': 'This model\'s maximum context length is '
                             f'{estimate_tokens(window)} tokens, but the request used '
                             f'{estimated} tokens (estimativa por caracteres).',
                             'type': 'invalid_request_error', 'code': 'context_length_exceeded'}}
    payload['browserapi'] = {
        'estimated': True, 'characters': characters, 'window_characters': window,
        'note': note or 'Números estimados por caracteres (4:1); o site não informa tokens.',
    }
    return payload


def usage_block(request_characters, answer_characters, *, window=None):
    """Estimativa rotulada. Zero fazia o agente nunca compactar (ver docs)."""
    prompt = estimate_tokens(request_characters)
    completion = estimate_tokens(answer_characters)
    extra = {'source': 'estimativa por caracteres (4 caracteres ≈ 1 token)',
             'estimated': True,
             'prompt_characters': request_characters,
             'response_characters': answer_characters,
             'note': 'O site do chat não informa tokens: estes valores são estimativa.'}
    if window:
        extra['window'] = window
    return {'input_tokens': prompt, 'output_tokens': completion,
            'total_tokens': prompt + completion, 'browserapi': extra}


def window_block(plan, limits):
    return {'characters': plan.characters, 'limit_characters': limits.conversation_chars,
            'percent': round(100 * plan.characters / limits.conversation_chars, 1),
            'estimated_tokens': estimate_tokens(plan.characters),
            'mode': plan.mode, 'rotate': plan.rotate}


def describe(plan, limits):
    """Frase curta para o painel e para o relatório; sem jargão de protocolo."""
    if plan.mode == 'delta':
        return (f'Turno novo enviado em {len(plan.sends)} bloco(s); a conversa do site está em '
                f'{plan.characters} de {limits.conversation_chars} caracteres.')
    if plan.mode == 'bootstrap':
        return (f'Início da conversa enviado em {len(plan.sends)} bloco(s) '
                f'({plan.characters_sent} caracteres).')
    return (f'Conversa reiniciada por limite de contexto: {len(plan.sends)} bloco(s), '
            f'{plan.report.get("compact_omitted", 0)} turno(s) resumido(s) em uma linha.')
