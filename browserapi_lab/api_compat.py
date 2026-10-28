"""Compatibilidade de protocolos: OpenAI Chat Completions, Anthropic Messages,
OpenAI Responses e o legado Completions.

Por que existe (relato do uso real): uma CLI de agente recebeu
*“Parâmetro não suportado; tools/temperature/limites nativos não são
simulados”*. A API local existia, mas recusava o vocabulário que as CLIs falam.
Aqui cada dialeto é traduzido para o mesmo pedido interno — um chat de navegador
— e a resposta volta no formato que o cliente entende.

O que é honesto prometer:

* parâmetros que o navegador não tem (``temperature``, ``max_tokens``, ``top_p``,
  ``seed``…) são **aceitos e registrados como ignorados**, nunca fingidos. A
  resposta diz isso em ``browserapi.ignored`` e na documentação;
* ferramentas são **emuladas por protocolo de texto** (:mod:`tool_calls`);
  ``browserapi.tools`` declara ``emulated``;
* tokens não são inventados: ``usage`` traz zeros e ``browserapi.usage`` explica
  que o site não informa contagem;
* streaming repete a resposta quando ela chega, porque a página entrega o texto
  inteiro — não há SSE do provedor aqui.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import tool_calls

KINDS = ('openai-chat', 'openai-completions', 'anthropic', 'openai-responses')

# Parâmetros que o cliente manda e o navegador não tem como honrar. Aceitar e
# dizer que ignorou é melhor do que recusar a chamada: o agente continua.
IGNORED = {
    'openai-chat': (
        'temperature', 'top_p', 'top_k', 'n', 'stop', 'max_tokens', 'max_completion_tokens',
        'presence_penalty', 'frequency_penalty', 'logit_bias', 'logprobs', 'top_logprobs',
        'seed', 'response_format', 'service_tier', 'parallel_tool_calls', 'user', 'store',
        'metadata', 'modalities', 'audio', 'reasoning_effort', 'stream_options',
        'prompt_cache_key', 'safety_identifier', 'verbosity',
    ),
    'anthropic': (
        'max_tokens', 'temperature', 'top_p', 'top_k', 'stop_sequences', 'metadata',
        'thinking', 'service_tier', 'container', 'mcp_servers', 'betas', 'context_management',
    ),
    'openai-completions': (
        'temperature', 'top_p', 'n', 'stop', 'max_tokens', 'presence_penalty',
        'frequency_penalty', 'logprobs', 'seed', 'suffix', 'best_of', 'logit_bias', 'user',
    ),
    'openai-responses': (
        'temperature', 'top_p', 'max_output_tokens', 'reasoning', 'text', 'truncation',
        'parallel_tool_calls', 'store', 'include', 'prompt', 'previous_response_id',
        'metadata', 'service_tier', 'user', 'max_tool_calls', 'background', 'top_logprobs',
    ),
}

# Chaves que este módulo realmente lê, por dialeto. O resto é recusado com o
# nome do campo: aceitar qualquer coisa calada esconde erro de digitação.
ACCEPTED = {
    'openai-chat': {'model', 'messages', 'stream', 'tools', 'tool_choice',
                    'documents', 'conversation_id'},
    'openai-completions': {'model', 'prompt', 'stream', 'documents', 'conversation_id'},
    'anthropic': {'model', 'messages', 'system', 'stream', 'tools', 'tool_choice'},
    'openai-responses': {'model', 'input', 'instructions', 'messages', 'stream',
                         'tools', 'tool_choice', 'documents', 'conversation_id'},
}

USAGE_NOTE = 'O site do chat não informa tokens; a contagem fica zerada e em caracteres.'


class APIError(ValueError):
    def __init__(self, message, code='invalid_request', http=400):
        super().__init__(message)
        self.code, self.http = code, http


def _require(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise APIError('O corpo precisa ser um objeto JSON')
    return payload


def _text_of(value: Any, where: str) -> str:
    """Texto de um campo que pode ser string ou lista de blocos."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise APIError(f'{where} precisa ser texto ou lista de blocos')
    parts: List[str] = []
    for block in value:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            raise APIError(f'{where} tem bloco inválido')
        kind = block.get('type')
        if kind in (None, 'text', 'input_text', 'output_text', 'text_delta'):
            parts.append(str(block.get('text') or ''))
        elif kind == 'tool_result':
            inner = block.get('content')
            body = inner if isinstance(inner, str) else _text_of(inner, 'tool_result')
            name = str(block.get('tool_use_id') or block.get('name') or 'ferramenta')
            parts.append(tool_calls.transcript_line('result', name, body,
                                                    is_error=bool(block.get('is_error'))))
        elif kind == 'tool_use':
            parts.append(tool_calls.transcript_line('call', str(block.get('name') or ''),
                                                    block.get('input')))
        elif kind in ('thinking', 'redacted_thinking'):
            continue
        elif kind in ('image', 'image_url', 'document', 'audio', 'input_image', 'input_file'):
            parts.append('[conteúdo não textual omitido: a API local é só texto]')
        else:
            parts.append(f'[{kind}]')
    return '\n'.join(part for part in parts if part.strip())


def _openai_message(item: Any) -> Tuple[str, str]:
    if not isinstance(item, dict):
        raise APIError('messages precisa de objetos')
    role = item.get('role')
    if role == 'tool':
        name = item.get('name') or item.get('tool_call_id') or 'ferramenta'
        body = _text_of(item.get('content'), 'messages[].content')
        return 'user', tool_calls.transcript_line('result', str(name), body)
    if role == 'assistant' and isinstance(item.get('tool_calls'), list):
        lines = []
        text = _text_of(item.get('content'), 'messages[].content')
        if text.strip():
            lines.append(text)
        for call in item['tool_calls']:
            if not isinstance(call, dict):
                continue
            function = call.get('function') if isinstance(call.get('function'), dict) else {}
            lines.append(tool_calls.transcript_line(
                'call', str(function.get('name') or call.get('name') or ''),
                function.get('arguments') or call.get('arguments')))
        return 'assistant', '\n'.join(lines)
    if role not in ('system', 'developer', 'user', 'assistant'):
        raise APIError('Papel inválido em messages: use system, developer, user, assistant ou tool')
    return ('system' if role == 'developer' else role), _text_of(item.get('content'), 'messages[].content')


def _anthropic_messages(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    system = payload.get('system')
    if system:
        text = _text_of(system, 'system')
        if text.strip():
            messages.append({'role': 'system', 'content': text})
    items = payload.get('messages')
    if not isinstance(items, list) or not items:
        raise APIError('messages precisa ser uma lista não vazia')
    for item in items:
        if not isinstance(item, dict):
            raise APIError('messages precisa de objetos')
        role = item.get('role')
        if role not in ('user', 'assistant'):
            raise APIError('Papéis aceitos em messages: user e assistant')
        text = _text_of(item.get('content'), 'messages[].content')
        if not text.strip():
            continue
        messages.append({'role': role, 'content': text})
    return messages


def _responses_messages(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    instructions = payload.get('instructions')
    if isinstance(instructions, str) and instructions.strip():
        messages.append({'role': 'system', 'content': instructions})
    source = payload.get('input', payload.get('messages'))
    if isinstance(source, str):
        messages.append({'role': 'user', 'content': source})
    elif isinstance(source, list):
        for item in source:
            if isinstance(item, str):
                messages.append({'role': 'user', 'content': item})
                continue
            if not isinstance(item, dict):
                raise APIError('input precisa de objetos')
            kind = item.get('type')
            if kind == 'function_call_output':
                messages.append({'role': 'user', 'content': tool_calls.transcript_line(
                    'result', str(item.get('call_id') or 'ferramenta'),
                    _text_of(item.get('output'), 'input.output'))})
                continue
            if kind == 'function_call':
                messages.append({'role': 'assistant', 'content': tool_calls.transcript_line(
                    'call', str(item.get('name') or ''), item.get('arguments'))})
                continue
            role = item.get('role') or 'user'
            if role == 'developer':
                role = 'system'
            if role not in ('system', 'user', 'assistant'):
                raise APIError('Papel inválido em input')
            text = _text_of(item.get('content'), 'input.content')
            if text.strip():
                messages.append({'role': role, 'content': text})
    else:
        raise APIError('input precisa ser texto ou lista')
    return messages


def normalize(kind: str, payload: Any) -> Dict[str, Any]:
    """Traduz o pedido do cliente para o pedido interno (um chat, um texto)."""
    if kind not in KINDS:
        raise APIError('Protocolo desconhecido', 'unsupported_protocol', 404)
    payload = _require(payload)
    unknown = sorted(set(payload) - ACCEPTED[kind] - set(IGNORED[kind]))
    if unknown:
        raise APIError('Parâmetro não suportado: ' + ', '.join(unknown)
                       + '. Aceitos: ' + ', '.join(sorted(ACCEPTED[kind]))
                       + '. Aceitos e ignorados (sem controle no navegador): '
                       + ', '.join(sorted(IGNORED[kind])) + '.', 'unsupported_parameter')
    if kind == 'anthropic':
        messages = _anthropic_messages(payload)
    elif kind == 'openai-responses':
        messages = _responses_messages(payload)
    elif kind == 'openai-completions':
        prompt = payload.get('prompt')
        texts = prompt if isinstance(prompt, list) else [prompt]
        if not texts or not all(isinstance(text, str) for text in texts):
            raise APIError('prompt precisa ser texto ou lista de textos')
        messages = [{'role': 'user', 'content': '\n\n'.join(texts)}]
    else:
        items = payload.get('messages')
        if not isinstance(items, list) or not items:
            raise APIError('messages precisa ser uma lista não vazia')
        messages = []
        for item in items:
            role, text = _openai_message(item)
            if text.strip():
                messages.append({'role': role, 'content': text})
    if not messages:
        raise APIError('Nenhuma mensagem de texto para enviar')
    if messages[-1]['role'] != 'user':
        raise APIError('A última mensagem precisa ser do usuário')
    stream = payload.get('stream', False)
    if type(stream) is not bool:
        raise APIError('stream deve ser booleano')
    model = payload.get('model')
    if model is None:
        model = 'auto'
    if not isinstance(model, str) or not model.strip():
        raise APIError('model precisa ser texto')
    try:
        tools = tool_calls.normalize_tools(payload.get('tools'))
    except ValueError as problem:
        raise APIError(str(problem)) from None
    ignored = [key for key in IGNORED[kind] if key in payload]
    metadata = payload.get('metadata')
    if isinstance(metadata, dict):
        ignored.extend(f'metadata.{key}' for key in metadata if key in ('user_id',))
    return {
        'model': model.strip(), 'messages': messages, 'stream': stream,
        'tools': tools, 'tool_choice': payload.get('tool_choice'),
        'documents': payload.get('documents'),
        'conversation_id': payload.get('conversation_id'),
        'ignored': sorted(set(ignored)),
        'kind': kind,
    }


def prompt_messages(request: Dict[str, Any]) -> List[Dict[str, str]]:
    """Mensagens que vão ao chat, com o protocolo de ferramentas quando houver."""
    messages = [dict(item) for item in request['messages']]
    tools = request.get('tools') or []
    if not tools:
        return messages
    choice = request.get('tool_choice')
    if choice in ('none', {'type': 'none'}):
        return messages
    instruction = {'role': 'system', 'content': tool_calls.protocol_prompt(tools, choice)}
    return [instruction] + messages


def _usage(request: Dict[str, Any], answer: str) -> Dict[str, Any]:
    sent = sum(len(item['content']) for item in request['messages'])
    return {
        'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0,
        'browserapi': {'prompt_characters': sent, 'response_characters': len(answer or ''),
                       'note': USAGE_NOTE},
    }


def _meta(request: Dict[str, Any], job: Any, parsed: tool_calls.Parsed) -> Dict[str, Any]:
    meta = {
        'context': getattr(job, 'context', {}) or {},
        'attempts': getattr(job, 'attempts', []) or [],
        'streaming': 'buffered',
        'model_alias': request['model'],
        'tools': 'emulated' if request.get('tools') else 'none',
        'usage': USAGE_NOTE,
    }
    if request.get('ignored'):
        # Dizer o que foi ignorado é o oposto de fingir que funcionou.
        meta['ignored'] = request['ignored']
    if parsed.used_tool:
        meta['tool_calls'] = len(parsed.calls)
    return meta


def _call_payload(call: Dict[str, Any]) -> str:
    return json.dumps(call['input'], ensure_ascii=False, sort_keys=True)


def body(kind: str, request: Dict[str, Any], job: Any, parsed: tool_calls.Parsed) -> Dict[str, Any]:
    """Resposta não-streaming no dialeto do cliente."""
    text = parsed.text
    meta = _meta(request, job, parsed)
    model = request['model']
    if kind == 'anthropic':
        content: List[Dict[str, Any]] = []
        if text:
            content.append({'type': 'text', 'text': text})
        for call in parsed.calls:
            content.append({'type': 'tool_use', 'id': call['id'], 'name': call['name'],
                            'input': call['input']})
        if not content:
            content.append({'type': 'text', 'text': ''})
        return {'id': 'msg_' + secrets.token_hex(12), 'type': 'message', 'role': 'assistant',
                'model': model, 'content': content,
                'stop_reason': 'tool_use' if parsed.calls else 'end_turn',
                'stop_sequence': None,
                'usage': {'input_tokens': 0, 'output_tokens': 0,
                          'browserapi': {'note': USAGE_NOTE,
                                         'response_characters': len(text)}},
                'browserapi': meta}
    if kind == 'openai-responses':
        output: List[Dict[str, Any]] = []
        if text:
            output.append({'type': 'message', 'id': 'msg_' + secrets.token_hex(8),
                           'status': 'completed', 'role': 'assistant',
                           'content': [{'type': 'output_text', 'text': text, 'annotations': []}]})
        for call in parsed.calls:
            output.append({'type': 'function_call', 'id': 'fc_' + secrets.token_hex(8),
                           'call_id': call['id'], 'name': call['name'],
                           'arguments': _call_payload(call), 'status': 'completed'})
        return {'id': 'resp_' + secrets.token_hex(12), 'object': 'response',
                'created_at': int(getattr(job, 'created_at', time.time())),
                'status': 'completed', 'model': model, 'output': output,
                'usage': _usage(request, text) | {'browserapi': None},
                'browserapi': meta}
    if kind == 'openai-completions':
        return {'id': getattr(job, 'identifier', 'cmpl-' + secrets.token_hex(8)),
                'object': 'text_completion', 'created': int(getattr(job, 'created_at', time.time())),
                'model': model,
                'choices': [{'index': 0, 'text': text, 'logprobs': None,
                             'finish_reason': 'stop'}],
                'usage': _usage(request, text),
                'browserapi': meta}
    message: Dict[str, Any] = {'role': 'assistant', 'content': text or None}
    if parsed.calls:
        message['tool_calls'] = [{'id': call['id'], 'type': 'function',
                                  'function': {'name': call['name'],
                                               'arguments': _call_payload(call)}}
                                 for call in parsed.calls]
    return {'id': getattr(job, 'identifier', 'chatcmpl-' + secrets.token_hex(16)),
            'object': 'chat.completion', 'created': int(getattr(job, 'created_at', time.time())),
            'model': model,
            'choices': [{'index': 0, 'message': message,
                         'finish_reason': 'tool_calls' if parsed.calls else 'stop'}],
            'usage': _usage(request, text),
            'browserapi': meta}


def _event(name: str, data: Dict[str, Any]) -> bytes:
    return ('event: ' + name + '\ndata: ' + json.dumps(data, ensure_ascii=False) + '\n\n').encode()


def _data(data: Dict[str, Any]) -> bytes:
    return ('data: ' + json.dumps(data, ensure_ascii=False) + '\n\n').encode()


def sse(kind: str, request: Dict[str, Any], job: Any,
        parsed: tool_calls.Parsed) -> bytes:
    """Corpo SSE no dialeto do cliente.

    O texto chega de uma vez (o site entrega a resposta inteira), então o
    streaming repete a resposta em um delta — mas com a sequência de eventos
    correta, que é o que as CLIs exigem para aceitar a resposta.
    """
    text = parsed.text
    meta = _meta(request, job, parsed)
    model = request['model']
    usage = {'input_tokens': 0, 'output_tokens': 0}
    if kind == 'anthropic':
        start = {'type': 'message_start', 'message': {
            'id': 'msg_' + secrets.token_hex(12), 'type': 'message', 'role': 'assistant',
            'model': model, 'content': [], 'stop_reason': None, 'stop_sequence': None,
            'usage': usage, 'browserapi': meta}}
        chunks = [_event('message_start', start)]
        if text:
            chunks.append(_event('content_block_start', {'type': 'content_block_start', 'index': 0,
                                                         'content_block': {'type': 'text', 'text': ''}}))
            chunks.append(_event('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                                         'delta': {'type': 'text_delta', 'text': text}}))
            chunks.append(_event('content_block_stop', {'type': 'content_block_stop', 'index': 0}))
        for offset, call in enumerate(parsed.calls):
            index = offset + (1 if text else 0)
            chunks.append(_event('content_block_start', {
                'type': 'content_block_start', 'index': index,
                'content_block': {'type': 'tool_use', 'id': call['id'], 'name': call['name'], 'input': {}}}))
            chunks.append(_event('content_block_delta', {
                'type': 'content_block_delta', 'index': index,
                'delta': {'type': 'input_json_delta', 'partial_json': _call_payload(call)}}))
            chunks.append(_event('content_block_stop', {'type': 'content_block_stop', 'index': index}))
        chunks.append(_event('message_delta', {'type': 'message_delta', 'delta': {
            'stop_reason': 'tool_use' if parsed.calls else 'end_turn', 'stop_sequence': None},
            'usage': {'output_tokens': 0}}))
        chunks.append(_event('message_stop', {'type': 'message_stop'}))
        return b''.join(chunks)
    if kind == 'openai-responses':
        created = {'type': 'response.created', 'response': {
            'id': 'resp_' + secrets.token_hex(12), 'object': 'response', 'status': 'in_progress',
            'model': model, 'output': []}}
        chunks = [_event('response.created', created)]
        if text:
            chunks.append(_event('response.output_text.delta', {
                'type': 'response.output_text.delta', 'item_id': 'msg_0', 'output_index': 0,
                'content_index': 0, 'delta': text}))
        for offset, call in enumerate(parsed.calls):
            chunks.append(_event('response.output_item.added', {
                'type': 'response.output_item.added', 'output_index': offset,
                'item': {'type': 'function_call', 'id': 'fc_' + secrets.token_hex(8),
                         'call_id': call['id'], 'name': call['name'], 'arguments': ''}}))
            chunks.append(_event('response.function_call_arguments.delta', {
                'type': 'response.function_call_arguments.delta', 'item_id': call['id'],
                'output_index': offset, 'delta': _call_payload(call)}))
        final = body('openai-responses', request, job, parsed)
        final['status'] = 'completed'
        chunks.append(_event('response.completed', {'type': 'response.completed',
                                                    'response': final}))
        return b''.join(chunks)
    if kind == 'openai-completions':
        payload = {'id': getattr(job, 'identifier', 'cmpl-' + secrets.token_hex(8)),
                   'object': 'text_completion', 'created': int(getattr(job, 'created_at', time.time())),
                   'model': model, 'choices': [{'index': 0, 'text': text,
                                                'finish_reason': None}]}
        end = dict(payload, choices=[{'index': 0, 'text': '', 'finish_reason': 'stop'}])
        return _data(payload) + _data(end) + b'data: [DONE]\n\n'
    identifier = getattr(job, 'identifier', 'chatcmpl-' + secrets.token_hex(16))
    created = int(getattr(job, 'created_at', time.time()))
    delta: Dict[str, Any] = {'role': 'assistant', 'content': text or None}
    if parsed.calls:
        delta['tool_calls'] = [{'index': offset, 'id': call['id'], 'type': 'function',
                                'function': {'name': call['name'],
                                             'arguments': _call_payload(call)}}
                               for offset, call in enumerate(parsed.calls)]
    first = {'id': identifier, 'object': 'chat.completion.chunk', 'created': created,
             'model': model, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}],
             'browserapi': meta}
    end = {'id': identifier, 'object': 'chat.completion.chunk', 'created': created,
           'model': model,
           'choices': [{'index': 0, 'delta': {},
                        'finish_reason': 'tool_calls' if parsed.calls else 'stop'}]}
    return _data(first) + _data(end) + b'data: [DONE]\n\n'
