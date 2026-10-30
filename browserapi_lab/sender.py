"""Estratégias de envio (Marco 4).

Regra do briefing: **uma tentativa só é sucesso se houver evidência observável**
— aqui, o surgimento de uma nova mensagem do usuário com o texto esperado.

Estratégias comparadas:

* ``fill``              — ``locator.fill()`` (textarea/input), instantâneo;
* ``paste``             — ``keyboard.insert_text()``: um único evento de entrada,
  como colar — é o caminho padrão de editores ricos (ProseMirror, Lexical,
  Slate) e o que evita digitar caractere por caractere;
* ``paste_event``       — ``ClipboardEvent('paste')`` com ``DataTransfer``;
* ``exec_insert``       — ``document.execCommand('insertText')``;
* ``type``              — teclado real, **tecla por tecla**: lento e propenso a
  perder caracteres em textos grandes, por isso fica por último;
* ``type_contenteditable`` — o mesmo, para ``contenteditable``;
* ``click_send``        — clique real no botão Enviar;
* ``press_enter``       — Enter como alternativa (ou Ctrl+Enter, conforme o controle);
* ``js_set``            — define o valor e dispara ``input`` (sites teimosos).

Regra de ouro: **só se ativa o envio quando o campo contém o texto inteiro**.
Texto parcial no campo é o que produzia "mensagem enviada pela metade" — o site
recebia um pedaço e o programa achava que tinha dado certo.

O Playwright é importado tardiamente; os tempos e o resultado são puros dados.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .discovery import ScoredCandidate
from .validation import composer_evidence

ALL_STRATEGIES: Tuple[str, ...] = (
    "fill",
    "paste",
    "paste_event",
    "exec_insert",
    "type",
    "type_contenteditable",
    "click_send",
    "press_enter",
    "js_set",
)

# Caminho rápido para cada tipo de campo. Colar primeiro, digitar por último.
STRATEGIES_BY_KIND: Dict[str, Tuple[str, ...]] = {
    "textarea": ("fill", "paste", "exec_insert", "js_set", "type"),
    "input": ("fill", "paste", "exec_insert", "js_set", "type"),
    "contenteditable": ("paste", "paste_event", "exec_insert", "fill", "js_set",
                        "type_contenteditable"),
}

# Digitar tecla por tecla é O(n) idas ao navegador: 20 mil caracteres viram
# dezenas de segundos e o editor perde pedaços. Acima deste tamanho, digitação
# não é tentada — melhor falhar dizendo quanto entrou do que mandar pela metade.
MAX_TYPE_CHARS = 4_000


@dataclass
class SendAttempt:
    strategy: str
    success: bool
    fill_ms: float = 0.0
    send_ms: float = 0.0
    verify_ms: float = 0.0
    evidence: str = ""
    error: Optional[str] = None
    composer_confirmed: bool = False
    layer: str = ""
    expected_chars: int = 0
    filled_chars: int = 0
    truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "success": self.success,
            "fill_ms": round(self.fill_ms, 2),
            "send_ms": round(self.send_ms, 2),
            "verify_ms": round(self.verify_ms, 2),
            "evidence": self.evidence,
            "composer_confirmed": self.composer_confirmed,
            "layer": self.layer,
            "expected_chars": self.expected_chars,
            "filled_chars": self.filled_chars,
            "truncated": self.truncated,
            "error": self.error,
        }


@dataclass
class SendResult:
    success: bool
    text: str
    attempts: List[SendAttempt] = field(default_factory=list)
    strategy: Optional[str] = None
    fill_ms: float = 0.0
    send_ms: float = 0.0
    total_ms: float = 0.0
    error: Optional[str] = None
    expected_chars: int = 0
    filled_chars: int = 0
    truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "text_chars": len(self.text),
            "expected_chars": self.expected_chars,
            "filled_chars": self.filled_chars,
            "truncated": self.truncated,
            "strategy": self.strategy,
            "fill_ms": round(self.fill_ms, 2),
            "send_ms": round(self.send_ms, 2),
            "total_ms": round(self.total_ms, 2),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "error": self.error,
        }


# --------------------------------------------------------------------------
# Localizadores
# --------------------------------------------------------------------------

def locator_for(page: Any, candidate: ScoredCandidate | Dict[str, Any]) -> Any:
    """Constrói um Locator do Playwright a partir de um candidato pontuado.

    * ``frame_path`` — iframes são atravessados com ``frame_locator`` encadeado;
    * open Shadow DOM — o engine de CSS do Playwright already atravessa;
      por isso basta o seletor.
    """
    selector = candidate.selector if isinstance(candidate, ScoredCandidate) else candidate["selector"]
    frame_path = candidate.frame_path if isinstance(candidate, ScoredCandidate) else (candidate.get("frame_path") or [])
    target: Any = page
    for frame_selector in frame_path:
        target = target.frame_locator(frame_selector)
    return target.locator(selector)


def control_kind(candidate: ScoredCandidate | Dict[str, Any]) -> str:
    """``textarea`` | ``input`` | ``contenteditable`` — escolhe a estratégia base."""
    data = candidate.candidate if isinstance(candidate, ScoredCandidate) else candidate
    if str(data.get("contenteditable")).lower() in ("true", ""):
        return "contenteditable"
    tag = str(data.get("tag") or "").lower()
    if tag == "textarea":
        return "textarea"
    if tag == "input":
        return "input"
    return "contenteditable"


# --------------------------------------------------------------------------
# Evidência
# --------------------------------------------------------------------------

LEGACY_COUNT_USER_MESSAGES = """(args) => {
  const nodes = document.querySelectorAll(args.selector || '[data-role="user"], .message[data-role="user"]');
  let ultimo = null;
  if (nodes.length) {
    const body = nodes[nodes.length - 1].querySelector('.body') || nodes[nodes.length - 1];
    ultimo = (body.innerText !== undefined && body.innerText !== null) ? body.innerText : body.textContent;
  }
  return { count: nodes.length, last: ultimo ? String(ultimo).trim() : null };
}"""


def user_message_state(page: Any, selector: Optional[str] = None) -> Dict[str, Any]:
    """Quantas mensagens do usuário existem e qual é a última.

    Lê pelo ``capture`` (camadas: papel declarado → estado do React → layout) e
    usa o seletor apontado como dica. Era aqui que um seletor que casava com a
    pergunta *e* com a resposta produzia "envio não confirmado" com a mensagem
    na tela: a contagem subia dois, o texto comparado era o da resposta.
    """
    from . import capture
    capture.ensure(page)
    state = capture.user_state(page, selector or "")
    if state["count"] or not selector:
        return {"count": state["count"], "last": state["last"], "layer": state["layer"]}
    # Página sem marcador nenhum e sem layout reconhecível: último recurso, o
    # seletor apontado, para não trocar "sem confirmação" por "sem envio".
    try:
        legacy = page.evaluate(LEGACY_COUNT_USER_MESSAGES, {"selector": selector})
    except Exception:
        return {"count": 0, "last": None, "layer": "none"}
    if not isinstance(legacy, dict):
        return {"count": 0, "last": None, "layer": "none"}
    return {"count": legacy.get("count") or 0, "last": legacy.get("last"),
            "layer": "configured-legacy" if legacy.get("count") else "none"}


def normalize_text(value: Any) -> str:
    """Compara o que a pessoa vê, não os bytes exatos do site.

    Chats re-renderizam a mensagem (NBSP, espaços zero-width, quebras de linha
    colapsadas, normalização Unicode). Comparar o texto cru produzia falso
    "envio sem confirmação" em sites reais.
    """
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value)
    for invisible in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"):
        value = value.replace(invisible, "")
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def evidence_of_send(before: Dict[str, Any], after: Dict[str, Any], expected: str,
                     composer_cleared: Optional[bool] = None,
                     nonce: Optional[str] = None) -> Tuple[bool, str]:
    """Confirmação por evidência observada; nunca por otimismo.

    Aceita, nesta ordem:

    1. mensagem nova com o **texto normalizado** esperado (igual ou contido);
    2. mesmo nó reutilizado cujo texto mudou para o esperado (lista virtualizada);
    3. mensagem nova **e** campo de digitação esvaziado — o site consumiu o
       rascunho e publicou um balão novo, mesmo que tenha reescrito o texto.

    A regra (3) ganhou uma exceção: se o balão publicado é um **prefixo** curto do
    que mandamos, é mensagem cortada — não confirmação. Antes, o site publicar
    metade do texto contava como sucesso, e o agente recebia uma resposta sobre
    um pedaço de prompt.

    Sem (1), (2) ou (3) o resultado é não confirmado. Texto divergente com o campo
    ainda preenchido continua sendo ambiguidade, não sucesso.
    """
    before_count = before.get("count", 0) or 0
    after_count = after.get("count", 0) or 0
    last = normalize_text(after.get("last"))
    wanted = normalize_text(expected)
    new_node = after_count > before_count
    previous = normalize_text(before.get("last"))
    same_node_changed = (not new_node and bool(previous) and bool(last) and previous != last)
    matches = bool(wanted) and bool(last) and (last == wanted or wanted in last)
    # Nonce (request_id) só existe se a mensagem foi publicada: é a evidência
    # mais forte que temos, e independe de o site reformatar o resto do texto.
    # A frase diz as duas coisas — quem lê o recibo vê se o texto também bateu,
    # em vez de concluir que a comparação por texto foi abandonada.
    if nonce and new_node and nonce in last:
        detail = " e o texto também confere" if matches else " (o site reescreveu o texto)"
        return True, "nonce do pedido visível no balão novo (envio confirmado)" + detail
    # Antes da regra "campo esvaziado": texto que é só um PEDAÇO do que mandamos
    # é a mensagem incompleta do relato, não um site que reescreveu o texto.
    cut, shown, wanted = looks_truncated(expected, str(after.get("last") or ""))
    if new_node and cut:
        return False, (f"mensagem publicada parece CORTADA: {shown} de {wanted} "
                       "caracteres apareceram no site")
    if matches:
        if new_node:
            return True, "nova mensagem do usuário com o texto esperado"
        if same_node_changed:
            return True, "mensagem do usuário atualizada no mesmo nó (texto esperado)"
        return False, "texto esperado já existia antes do envio; sem mensagem nova"
    if new_node:
        if composer_cleared:
            return True, "nova mensagem do usuário e campo esvaziado (site reescreveu o texto)"
        return False, "mensagem nova, mas texto divergente"
    if composer_cleared:
        return False, "campo esvaziado, mas nenhuma mensagem nova observada"
    return False, "nenhuma nova mensagem do usuário"


# --------------------------------------------------------------------------
# Preenchimento e ativação
# --------------------------------------------------------------------------

# Leitura do campo sem contar o que NÃO é rascunho.
#
# Editores ricos deixam lixo no campo vazio: ProseMirror/Quill põem
# ``<p><br></p>``, outros põem um nó de placeholder com texto. Ler
# ``innerText``/``textContent`` cru devolvia ``"\n"`` (ou o texto do
# placeholder) — e o programa concluía "Há um rascunho no campo" com o campo
# vazio, parando antes de enviar. Percorrer a árvore ignorando placeholders,
# ``<br>`` e nós escondidos resolve, e ainda preserva as quebras de linha.
COMPOSER_TEXT_JS = """(el) => {
  if (!el) return null;
  if (!el.isContentEditable) return el.value ?? '';
  const skipped = (node) => {
    if (node.nodeType !== 1) return false;
    if (node.getAttribute('aria-hidden') === 'true') return true;
    if (node.hasAttribute('data-placeholder')) return true;
    const cls = node.classList;
    return !!(cls && (cls.contains('placeholder') || cls.contains('is-empty') ||
                      cls.contains('ProseMirror-trailingBreak')));
  };
  const block = /^(P|DIV|LI|PRE|BLOCKQUOTE)$/;
  let out = '';
  const walk = (node) => {
    if (node.nodeType === 3) { out += node.nodeValue; return; }
    if (node.nodeType !== 1) return;
    const tag = node.tagName;
    if (tag === 'BR') { out += '\n'; return; }
    if (tag === 'SCRIPT' || tag === 'STYLE' || skipped(node)) return;
    const isBlock = block.test(tag);
    if (isBlock && out && !out.endsWith('\n')) out += '\n';
    for (const child of node.childNodes) walk(child);
  };
  for (const child of el.childNodes) walk(child);
  return out;
}"""


def read_composer(locator: Any) -> Optional[str]:
    """Texto que está no campo agora — sem placeholder e sem nós invisíveis.

    ``None`` significa "não consegui ler" (página trocando, seletor errado), o
    que é diferente de campo vazio. Quem decide se há rascunho usa
    :func:`composer_has_text`, que normaliza.
    """
    try:
        value = locator.evaluate(COMPOSER_TEXT_JS)
    except Exception:
        return None
    return value if isinstance(value, str) else None


def composer_has_text(locator: Any) -> bool:
    """Há texto de verdade no campo?

    Campo de editor rico "vazio" costuma conter ``<p><br></p>`` ou um nó de
    placeholder; isso NÃO é rascunho. Era esta a causa do falso "Há um rascunho
    no campo" que travava o envio logo depois do mapeamento.
    """
    current = read_composer(locator)
    return bool(normalize_text(current or ''))


def composer_matches(locator: Any, text: str) -> Tuple[bool, int]:
    """O campo tem **o texto inteiro**? Devolve (igual, caracteres presentes).

    Comparação normalizada (espaços/NBSP/invisíveis), porque o editor reescreve
    o que colou. O que não se tolera é **faltar** texto: era assim que a mensagem
    ia incompleta para o site.
    """
    current = read_composer(locator)
    if current is None:
        return False, 0
    wanted = normalize_text(text)
    got = normalize_text(current)
    if not wanted:
        return False, len(got)
    if got == wanted:
        return True, len(got)
    # Sites que embrulham o texto (ex.: acrescentam uma quebra no fim) são
    # aceitos; texto A MAIS de verdade (limpeza que falhou) não, para não
    # enviar a mensagem duplicada.
    if wanted in got and len(got) - len(wanted) <= 8:
        return True, len(got)
    return False, len(got)


def _select_all(locator: Any, page: Any, kind: str) -> None:
    modifier = "Meta" if _is_mac(page) else "Control"
    try:
        locator.click()
    except Exception:
        pass
    try:
        page.keyboard.press(f"{modifier}+a")
    except Exception:
        pass


def _clear(locator: Any, kind: str) -> None:
    try:
        if kind == "contenteditable":
            locator.click()
            locator.page.keyboard.press("Control+A")
            locator.page.keyboard.press("Delete")
        else:
            locator.fill("")
    except Exception:
        pass  # limpeza é best-effort: o que importa é a evidência depois


PASTE_EVENT_JS = """(el, text) => {
  el.focus();
  const data = new DataTransfer();
  data.setData('text/plain', text);
  const event = new ClipboardEvent('paste', {clipboardData: data, bubbles: true,
                                             cancelable: true, composed: true});
  el.dispatchEvent(event);
}"""

EXEC_INSERT_JS = """(el, text) => {
  el.focus();
  if (el.isContentEditable) {
    document.execCommand('insertText', false, text);
    return;
  }
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? el.value.length;
  if (typeof el.setRangeText === 'function') {
    el.setRangeText(text, start, end, 'end');
  } else {
    el.value = el.value.slice(0, start) + text + el.value.slice(end);
  }
  el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText',
                                            data: text}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
}"""


def _fill(locator: Any, kind: str, text: str, strategy: str, delay_ms: int,
          page: Any = None) -> None:
    """Coloca ``text`` no campo do jeito mais rápido que o site aceitar."""
    page = page if page is not None else getattr(locator, "page", None)
    if strategy == "fill":
        if kind == "contenteditable":
            # fill() funciona em contenteditable, mas não exercita o teclado:
            # mantemos como estratégia distinta abaixo.
            locator.fill(text)
        else:
            locator.fill(text)
    elif strategy == "paste":
        # Um único Input.insertText — o mesmo evento que um Ctrl+V produz. Não há
        # tecla por tecla: 20 mil caracteres entram numa chamada.
        _select_all(locator, page, kind)
        page.keyboard.insert_text(text)
    elif strategy == "paste_event":
        _select_all(locator, page, kind)
        locator.evaluate(PASTE_EVENT_JS, text)
    elif strategy == "exec_insert":
        _select_all(locator, page, kind)
        locator.evaluate(EXEC_INSERT_JS, text)
    elif strategy == "type":
        locator.click()
        locator.press_sequentially(text, delay=delay_ms)
    elif strategy == "type_contenteditable":
        locator.click()
        locator.press_sequentially(text, delay=delay_ms)
    elif strategy == "js_set":
        locator.evaluate(
            """(el, value) => {
              if (el.tagName === 'DIV' || el.getAttribute('contenteditable') === 'true') {
                el.textContent = value;
              } else {
                el.value = value;
              }
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            text,
        )
    else:
        raise ValueError(f"estratégia de preenchimento desconhecida: {strategy}")


def _activate(page: Any, locator: Any, send_button: Optional[ScoredCandidate],
              kind: str, strategy: str) -> None:
    """Dispara o envio: botão real ou Enter — nunca os dois ao mesmo tempo."""
    if strategy == "press_enter":
        if kind == "textarea":
            # em textarea, Enter costuma quebrar linha: Shift+Enter não envia,
            # Ctrl/Cmd+Enter é a alternativa comum em chats
            modifier = "Control" if not _is_mac(page) else "Meta"
            locator.press(f"{modifier}+Enter")
        else:
            locator.press("Enter")
        return
    if send_button is None:
        raise RuntimeError("sem botão de envio descoberto para a estratégia de clique")
    locator_for(page, send_button).click()


def _is_mac(page: Any) -> bool:
    try:
        return "Mac" in page.evaluate("() => navigator.platform || ''")
    except Exception:
        return False


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------

class SendControlUnavailable(RuntimeError):
    """Controle não está pronto após preencher; nenhuma ativação foi feita."""


class VoiceControlUnavailable(SendControlUnavailable):
    """Não ativar um controle explicitamente identificado como gravação/voz."""


def is_voice_control(locator):
    from pathlib import Path
    return locator.evaluate((Path(__file__).parent / 'assets' / 'voice_control.js').read_text())


def control_fingerprint(locator):
    import hashlib
    import json
    state = locator.evaluate(r"""el => {
        const attributes = node => ['aria-label','title','data-testid','data-icon','d','href'].map(key => [key, (node.getAttribute(key) || '').slice(0,4096)]);
        return {attributes: attributes(el), text:(el.textContent || '').replace(/\s+/g,' ').trim().slice(0,256),
            icons:[...el.querySelectorAll('svg path,svg use,svg title,mat-icon,[data-icon]')].slice(0,24).map(node => ({tag:node.tagName, attributes:attributes(node), text:(node.textContent || '').slice(0,128)}))};
    }""")
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def is_recorded_voice(locator, config):
    return bool(config.voice and config.voice_signature
                and locator.evaluate('(el, selector) => el.matches(selector)', config.voice)
                and control_fingerprint(locator) == config.voice_signature)


def send_message(
    page: Any,
    composer: ScoredCandidate,
    send_button: Optional[ScoredCandidate],
    text: str,
    strategies: Optional[Sequence[str]] = None,
    activation: Sequence[str] = ("click_send", "press_enter"),
    delay_ms: int = 0,
    verify_timeout_ms: float = 5_000.0,
    settle_poll_ms: float = 50.0,
    user_selector: Optional[str] = None,
    before_activate: Any = None,
    nonce: Optional[str] = None,
    composer_timeout_ms: float = 1_200.0,
    max_type_chars: int = MAX_TYPE_CHARS,
) -> SendResult:
    """Tenta enviar ``text`` combinando preenchimento e ativação até haver evidência.

    Cada tentativa é independente: limpa o campo, coloca o texto, **confere que
    entrou inteiro** e só então ativa. Texto parcial nunca é enviado: se o campo
    não aceitar tudo, a tentativa é descartada sem clicar em Enviar, e a próxima
    estratégia é testada. Sem nenhuma que caiba, o resultado é
    ``composer_incomplete`` — nunca um falso sucesso nem uma mensagem pela metade.
    """
    started = time.perf_counter()
    locator = locator_for(page, composer)
    kind = control_kind(composer)
    strategies = tuple(strategies or STRATEGIES_BY_KIND.get(kind, ("fill", "paste")))
    before = user_message_state(page, user_selector)
    attempts: List[SendAttempt] = []
    incompletes: List[SendAttempt] = []
    expected_chars = len(text)

    for fill_strategy in strategies:
        if kind != "contenteditable" and fill_strategy == "type_contenteditable":
            continue
        if kind == "contenteditable" and fill_strategy == "fill":
            continue
        if fill_strategy in ("type", "type_contenteditable") and len(text) > max_type_chars:
            # Tecla por tecla em texto grande: lento e perde pedaços.
            continue
        for activation_strategy in activation:
            attempt = SendAttempt(strategy=f"{fill_strategy}+{activation_strategy}", success=False,
                                  expected_chars=expected_chars)
            activated = False
            try:
                _clear(locator, kind)
                t0 = time.perf_counter()
                _fill(locator, kind, text, fill_strategy, delay_ms, page=page)
                attempt.fill_ms = (time.perf_counter() - t0) * 1000.0
                # O editor às vezes aplica o texto de forma assíncrona.
                full, present = _wait_composer(locator, text, composer_timeout_ms)
                attempt.filled_chars = present
                if not full:
                    attempt.error = "ComposerIncomplete"
                    attempt.evidence = (f"o campo recebeu {present} de {expected_chars} "
                                        f"caracteres com {fill_strategy}; envio cancelado")
                    attempts.append(attempt)
                    incompletes.append(attempt)
                    # Nada clicado: pode tentar outra forma de colar sem duplicar.
                    break
                filled_value = read_composer(locator)
                t1 = time.perf_counter()
                if before_activate is not None:
                    before_activate()
                # Daqui em diante qualquer falha é ambígua: nunca reenviar.
                activated = True
                _activate(page, locator, send_button, kind, activation_strategy)
                attempt.send_ms = (time.perf_counter() - t1) * 1000.0

                t2 = time.perf_counter()
                ok, evidence, layer, truncated = _wait_evidence(
                    page, before, text, verify_timeout_ms, settle_poll_ms,
                    user_selector, composer_getter=lambda: read_composer(locator),
                    filled=filled_value, nonce=nonce)
                attempt.verify_ms = (time.perf_counter() - t2) * 1000.0
                attempt.evidence = evidence
                attempt.layer = layer
                attempt.truncated = truncated
                attempt.composer_confirmed = composer_evidence(
                    text, filled_value or "", read_composer(locator), ok).confirmed
                if ok:
                    attempt.success = True
                    attempts.append(attempt)
                    return SendResult(
                        success=True,
                        text=text,
                        attempts=attempts,
                        strategy=attempt.strategy,
                        fill_ms=attempt.fill_ms,
                        send_ms=attempt.send_ms,
                        total_ms=(time.perf_counter() - started) * 1000.0,
                    )
            except EOFError:
                raise
            except Exception as exc:
                attempt.error = type(exc).__name__
                attempt.evidence = "exceção durante a tentativa"
            attempts.append(attempt)
            if activated:
                # Ausência de confirmação NÃO prova que o site recusou o envio.
                return SendResult(False, text, attempts=attempts,
                                  error="envio sem confirmação; repetição automática bloqueada",
                                  expected_chars=expected_chars,
                                  truncated=attempt.truncated,
                                  filled_chars=attempt.filled_chars,
                                  total_ms=(time.perf_counter() - started) * 1000.0)

    if incompletes:
        best = max(incompletes, key=lambda item: item.filled_chars)
        return SendResult(
            success=False,
            text=text,
            attempts=attempts,
            error=(f"composer_incomplete: o campo não aceitou a mensagem inteira "
                   f"({best.filled_chars} de {expected_chars} caracteres)"),
            expected_chars=expected_chars,
            filled_chars=best.filled_chars,
            total_ms=(time.perf_counter() - started) * 1000.0,
        )
    return SendResult(
        success=False,
        text=text,
        attempts=attempts,
        error="nenhuma estratégia produziu evidência de envio",
        expected_chars=expected_chars,
        total_ms=(time.perf_counter() - started) * 1000.0,
    )


def _wait_composer(locator: Any, text: str, timeout_ms: float,
                   poll_ms: float = 40.0) -> Tuple[bool, int]:
    """Espera o campo refletir o texto inteiro (editores aplicam async).

    Devolve ``(completo, caracteres_presentes)``. Se não completar, quem chamou
    **não envia**: mensagem parcial no site é pior do que erro visível.
    """
    deadline = time.perf_counter() + (timeout_ms / 1000.0)
    present = 0
    while True:
        full, present = composer_matches(locator, text)
        if full:
            return True, present
        if time.perf_counter() >= deadline:
            return False, present
        try:
            locator.page.wait_for_timeout(poll_ms)
        except Exception:
            time.sleep(poll_ms / 1000.0)


def looks_truncated(sent: str, shown: str) -> Tuple[bool, int, int]:
    """O balão publicado parece **corte** do texto que mandamos?

    Compara normalizado: se o que apareceu é prefixo do esperado e falta pelo
    menos 10% (e 80 caracteres), é mensagem pela metade — não sucesso.
    """
    wanted = normalize_text(sent)
    got = normalize_text(shown)
    if not wanted or not got:
        return False, len(got), len(wanted)
    if len(got) >= len(wanted):
        return False, len(got), len(wanted)
    if wanted.startswith(got) and len(got) >= max(80, int(len(wanted) * 0.9)):
        # Quase tudo: o site encurtou por conta própria (ex.: "mostrar mais").
        return False, len(got), len(wanted)
    if wanted.startswith(got) and len(got) < len(wanted):
        return True, len(got), len(wanted)
    return False, len(got), len(wanted)


def _wait_evidence(page: Any, before: Dict[str, Any], text: str,
                   timeout_ms: float, poll_ms: float, user_selector: Optional[str] = None,
                   composer_getter: Any = None, filled: Optional[str] = None,
                   nonce: Optional[str] = None) -> Tuple[bool, str, str, bool]:
    deadline = time.perf_counter() + (timeout_ms / 1000.0)
    last_reason = "sem evidência"
    layer = ""
    while time.perf_counter() < deadline:
        after = user_message_state(page, user_selector)
        layer = str(after.get("layer") or "")
        cleared = False
        if composer_getter is not None and filled:
            try:
                current = composer_getter()
                cleared = current is not None and not current.strip()
            except Exception:
                cleared = False
        ok, reason = evidence_of_send(before, after, text, composer_cleared=cleared, nonce=nonce)
        if ok:
            return True, reason, layer, False
        cut, shown, wanted = looks_truncated(text, str(after.get("last") or ""))
        if cut and (after.get("count", 0) or 0) > (before.get("count", 0) or 0):
            return False, (f"mensagem publicada parece CORTADA: {shown} de {wanted} "
                           "caracteres apareceram no site"), layer, True
        last_reason = reason
        page.wait_for_timeout(poll_ms)
    return False, last_reason, layer, False
