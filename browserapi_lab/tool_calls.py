"""Chamada de ferramentas sem função nativa: protocolo de texto + leitura tolerante.

Por que existe (relato do uso real): uma CLI de agente chamou a API local e
recebeu *“Parâmetro não suportado; tools/temperature/limites nativos não são
simulados”*. O chat do navegador não expõe `tools` como a API do provedor, mas
isso não impede um agente de funcionar: o modelo recebe a lista de ferramentas e
um formato de resposta, e o que ele escrever é interpretado aqui.

Contrato honesto, em três regras:

1. **nada é inventado** — se o texto não contém uma chamada válida, a resposta
   é texto comum e o agente decide o que fazer;
2. **o nome precisa existir** na lista enviada pelo cliente; nome desconhecido
   não vira chamada (evita executar o que ninguém declarou);
3. **os argumentos precisam ser um objeto JSON** — string com JSON é aceita,
   porque modelos alternam entre as duas formas.

A emulação é declarada na resposta (`browserapi.tools: 'emulated'`) e na
documentação. Ela não transforma o chat em uma API com função nativa.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MAX_DESCRIPTION = 600
MAX_SCHEMA = 1200
MAX_TOOLS = 64
MAX_CALLS = 16
# Orçamento do bloco de ferramentas dentro do prompt. O primeiro pedido de uma
# CLI real medido em laboratório traz ~30 mil caracteres só em esquemas; isso não
# cabe no campo de um chat web junto com o resto (ver docs/CONTEXT_WINDOWS.md).
DEFAULT_TOOL_BUDGET = 9_000


@dataclass
class Parsed:
    """Resposta do modelo já separada em texto e chamadas."""

    text: str = ''
    calls: List[Dict[str, Any]] = field(default_factory=list)
    # JSON de ferramenta aberto e não fechado: a resposta foi cortada no meio.
    # Quem chama pode pedir continuação em vez de entregar texto pela metade.
    incomplete: bool = False

    @property
    def used_tool(self) -> bool:
        return bool(self.calls)


def _short(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def schema_of(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Aceita os dois dialetos: ``input_schema`` (Anthropic) e ``parameters``."""
    for key in ('input_schema', 'parameters', 'inputSchema', 'schema'):
        value = tool.get(key)
        if isinstance(value, dict):
            return value
    function = tool.get('function')
    if isinstance(function, dict) and isinstance(function.get('parameters'), dict):
        return function['parameters']
    return {'type': 'object', 'properties': {}}


def name_of(tool: Dict[str, Any]) -> str:
    if isinstance(tool.get('name'), str) and tool['name'].strip():
        return tool['name'].strip()
    function = tool.get('function')
    if isinstance(function, dict) and isinstance(function.get('name'), str):
        return function['name'].strip()
    return ''


def description_of(tool: Dict[str, Any]) -> str:
    if isinstance(tool.get('description'), str):
        return tool['description']
    function = tool.get('function')
    if isinstance(function, dict) and isinstance(function.get('description'), str):
        return function['description']
    return ''


def normalize_tools(tools: Any) -> List[Dict[str, Any]]:
    """Lista canônica ``[{name, description, schema}]``, sem duplicatas."""
    if tools is None:
        return []
    if not isinstance(tools, list):
        raise ValueError('tools deve ser uma lista')
    result: List[Dict[str, Any]] = []
    seen = set()
    for tool in tools[:MAX_TOOLS]:
        if not isinstance(tool, dict):
            raise ValueError('cada ferramenta precisa ser um objeto')
        # Em Claude Code e no protocolo antigo da OpenAI aparece {"type":"custom"}.
        if tool.get('type') in ('custom',) and not name_of(tool):
            continue
        name = name_of(tool)
        if not name or name in seen:
            continue
        seen.add(name)
        result.append({'name': name, 'description': description_of(tool), 'schema': schema_of(tool)})
    return result


def signature_of(schema: Dict[str, Any], limit: int = 240) -> str:
    """Assinatura curta: ``cmd:string, timeout:number?`` — sem validações fundas."""
    properties = schema.get('properties') if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        return ''
    required = schema.get('required') if isinstance(schema.get('required'), list) else []
    parts: List[str] = []
    for name, spec in list(properties.items())[:24]:
        kind = ''
        if isinstance(spec, dict):
            raw = spec.get('type')
            if isinstance(raw, list):
                raw = '|'.join(str(item) for item in raw)
            kind = str(raw or '')
            if not kind and isinstance(spec.get('properties'), dict):
                kind = 'object'
            if not kind:
                enum = spec.get('enum')
                kind = 'texto' if isinstance(enum, list) else 'any'
        optional = '' if name in required else '?'
        parts.append(f'{name}:{kind}{optional}')
    text = ', '.join(parts)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def protocol_prompt(tools: Sequence[Dict[str, Any]], tool_choice: Any = None, *,
                    budget: int = DEFAULT_TOOL_BUDGET) -> str:
    """Instrução de ferramentas para o chat que só entende texto.

    Passa por um orçamento de caracteres: descrição e assinatura de cada
    ferramenta, com a descrição encurtada quando o conjunto não cabe. Se ainda
    assim estourar, o bloco é cortado com marcador visível — o modelo sabe que
    recebeu menos, e a resposta declara ``tools: 'emulated'``.
    """
    if not tools:
        return ''
    choice = tool_choice
    forced = ''
    if isinstance(choice, dict):
        required = choice.get('name') or (choice.get('function') or {}).get('name')
        if required:
            forced = f' Neste turno, chame obrigatoriamente "{required}" se precisar de dados.'
    elif choice == 'any' or choice == 'required':
        forced = ' Neste turno, chame ao menos uma ferramenta.'
    header = '\n'.join([
        'FERRAMENTAS DISPONÍVEIS (protocolo local, sem função nativa):',
        'Quando precisar de uma ferramenta, responda SOMENTE com um objeto JSON, sem texto em volta:',
        '{"tool_calls":[{"name":"<nome>","arguments":{...}}]}',
        'Use apenas nomes desta lista. Se não precisar de ferramenta, responda em texto normal.'
        + forced,
        '',
    ])
    for description_limit in (MAX_DESCRIPTION, 300, 160, 80, 0):
        lines = [header]
        for tool in tools:
            line = f'- {tool["name"]}'
            if description_limit and tool.get('description'):
                line += ': ' + _short(tool['description'], description_limit)
            signature = signature_of(tool.get('schema') or {})
            if signature:
                line += f' ({signature})'
            lines.append(line)
        text = '\n'.join(lines)
        if len(text) <= budget:
            return text
    return text[:budget - 40] + '\n[lista de ferramentas cortada pelo orçamento local]'


def protocol_reminder(tools: Sequence[Dict[str, Any]], tool_choice: Any = None) -> str:
    """Lembrete curto para os turnos seguintes (o protocolo inteiro já foi enviado).

    Sem isso a conversa do site pode “esquecer” o formato no meio de uma sessão.
    """
    if not tools:
        return ''
    names = ', '.join(tool['name'] for tool in tools[:24])
    forced = ''
    if isinstance(tool_choice, dict):
        required = tool_choice.get('name') or (tool_choice.get('function') or {}).get('name')
        if required:
            forced = f' Use "{required}".'
    elif tool_choice in ('any', 'required'):
        forced = ' Chame ao menos uma.'
    return ('[lembrete] Ferramentas: ' + names + '. Para chamar, responda só com '
            '{"tool_calls":[{"name":"<nome>","arguments":{...}}]}.' + forced)


def _as_calls(value: Any, names: Sequence[str]) -> List[Tuple[str, Dict[str, Any]]]:
    if isinstance(value, dict) and isinstance(value.get('tool_calls'), list):
        items: Iterable[Any] = value['tool_calls']
    elif isinstance(value, dict) and isinstance(value.get('calls'), list):
        items = value['calls']
    elif isinstance(value, dict) and (value.get('name') or value.get('tool')):
        items = [value]
    elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        items = value
    else:
        return []
    lowered = {name.lower(): name for name in names}
    found: List[Tuple[str, Dict[str, Any]]] = []
    for item in list(items)[:MAX_CALLS]:
        if not isinstance(item, dict):
            return []
        function = item.get('function') if isinstance(item.get('function'), dict) else {}
        raw_name = item.get('name') or item.get('tool') or function.get('name')
        arguments = item.get('arguments', item.get('input', item.get('parameters', item.get('args'))))
        if arguments is None:
            arguments = function.get('arguments')
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except ValueError:
                return []
        if arguments is None:
            arguments = {}
        if not isinstance(raw_name, str) or not isinstance(arguments, dict):
            return []
        name = raw_name if raw_name in names else lowered.get(raw_name.lower(), '')
        # Nome fora da lista não vira chamada: quem executa é o cliente, e ele
        # só conhece as ferramentas que declarou.
        if not name:
            return []
        found.append((name, arguments))
    return found


def _spans(text: str) -> List[Tuple[int, int, Any]]:
    """Blocos JSON no texto, na ordem em que aparecem (fence primeiro)."""
    spans: List[Tuple[int, int, Any]] = []
    for match in re.finditer(r'```(?:json|JSON)?\s*\n?(.*?)```', text, re.S):
        body = match.group(1).strip()
        if not body.startswith(('{', '[')):
            continue
        try:
            value = json.loads(body)
        except ValueError:
            continue
        spans.append((match.start(), match.end(), value))
    if spans:
        return spans
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        start = text.find('{', index)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
        except ValueError:
            index = start + 1
            continue
        spans.append((start, start + end, value))
        index = start + end
    return spans


def parse(text: Any, tools: Sequence[Dict[str, Any]]) -> Parsed:
    """Separa ``text`` em resposta e chamadas válidas.

    Sem ferramentas declaradas, devolve o texto intacto: nada é interpretado por
    conta própria quando o cliente não pediu ferramentas.
    """
    body = text if isinstance(text, str) else ''
    names = [tool['name'] for tool in tools]
    if not names or not body.strip():
        return Parsed(text=body.strip())
    calls: List[Dict[str, Any]] = []
    consumed: List[Tuple[int, int]] = []
    for start, end, value in _spans(body):
        found = _as_calls(value, names)
        if not found:
            continue
        calls.extend({'id': _call_id(index), 'name': name, 'input': arguments}
                     for index, (name, arguments) in enumerate(found, start=len(calls)))
        consumed.append((start, end))
        if len(calls) >= MAX_CALLS:
            break
    if not calls:
        return Parsed(text=body.strip(), incomplete=_looks_cut(body, names))
    remaining = body
    for start, end in reversed(consumed):
        remaining = remaining[:start] + remaining[end:]
    remaining = re.sub(r'\n{3,}', '\n\n', remaining).strip()
    return Parsed(text=remaining, calls=calls[:MAX_CALLS])


def _looks_cut(text: str, names: Sequence[str]) -> bool:
    """A resposta parece uma chamada de ferramenta interrompida?

    Só é chamado quando nenhuma chamada válida foi encontrada. Cerca de código
    aberta, ``tool_calls`` citado sem JSON válido e chaves desbalanceadas são os
    três sinais observados em resposta cortada no meio.
    """
    if not text.strip():
        return False
    if text.count('```') % 2 == 1:
        return True
    lowered = text.lower()
    if '"tool_calls"' not in lowered and "'tool_calls'" not in lowered:
        if not any(name.lower() in lowered for name in names[:24]):
            return False
    if text.count('{') > text.count('}'):
        return True
    return False


def _call_id(index: int) -> str:
    import secrets
    return 'toolu_' + secrets.token_hex(8) + f'{index:02d}'


def transcript_line(kind: str, name: str, payload: Any, is_error: bool = False) -> str:
    """Linha de histórico para turnos de ferramenta que o cliente devolveu.

    O chat do navegador não tem canal de ferramenta: o pedido e o resultado
    entram como texto, para o modelo não perder o fio da conversa.
    """
    if kind == 'call':
        rendered = _short(payload if isinstance(payload, str)
                          else json.dumps(payload or {}, ensure_ascii=False), MAX_SCHEMA)
        return f'[chamada de ferramenta {name}: {rendered}]'
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    prefix = '[erro da ferramenta' if is_error else '[resultado da ferramenta'
    return f'{prefix} {name}]\n{_short(body, 8000)}'
