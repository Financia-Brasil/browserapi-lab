"""Experimentos de confirmação de composer e contrato de resposta.

Não substitui descoberta, prova de envio nem detecção de streaming. Um contrato
válido não prova autoria, veracidade ou término; o chamador deve fornecer apenas
mensagens novas do assistente e verificar término separadamente.
"""
from dataclasses import dataclass
import json
from typing import Optional, Sequence


@dataclass(frozen=True)
class ComposerEvidence:
    filled_correctly: bool
    cleared_after_send: bool
    new_user_message: bool

    @property
    def confirmed(self) -> bool:
        # Apagar o texto sozinho também pode ser reset/erro da interface.
        return self.filled_correctly and self.cleared_after_send and self.new_user_message


def composer_evidence(expected: str, before: str, after: Optional[str],
                      new_user_message: bool) -> ComposerEvidence:
    return ComposerEvidence(
        filled_correctly=bool(expected) and before == expected,
        cleared_after_send=after is not None and not after.strip(),
        new_user_message=new_user_message,
    )


def response_instruction(request_id: str) -> str:
    """Contrato opt-in; nunca modifica silenciosamente a mensagem do usuário."""
    return ('Responda somente com um objeto JSON, sem cercas Markdown, com exatamente '
            'as chaves request_id (string) e answer (string). '
            f'O valor de request_id deve ser {json.dumps(request_id)}. '
            'Coloque sua resposta em answer.')


def validate_response(text: str, request_id: str) -> bool:
    """Valida JSON inteiro, chaves únicas e identificador da tentativa atual."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('chave duplicada')
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=unique_pairs)
    except (ValueError, TypeError, RecursionError):
        return False
    return (isinstance(value, dict) and set(value) == {'request_id', 'answer'}
            and type(value['request_id']) is str and value['request_id'] == request_id
            and type(value['answer']) is str)


@dataclass(frozen=True)
class OutputSelection:
    status: str  # selected | no_match | ambiguous
    index: Optional[int]
    matching_indices: tuple[int, ...]


def select_output(candidates: Sequence[str], request_id: str) -> OutputSelection:
    """Não resolve ambiguidade pela ordem do DOM ou pelo tamanho do texto."""
    matches = tuple(i for i, text in enumerate(candidates)
                    if validate_response(text, request_id))
    if len(matches) == 1:
        return OutputSelection('selected', matches[0], matches)
    return OutputSelection('ambiguous' if matches else 'no_match', None, matches)
