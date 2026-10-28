"""Estratégias de envio (Marco 4).

Regra do briefing: **uma tentativa só é sucesso se houver evidência observável**
— aqui, o surgimento de uma nova mensagem do usuário com o texto esperado.

Estratégias comparadas:

* ``fill``              — ``locator.fill()`` (textarea/input);
* ``type``              — teclado real do Playwright (pressiona tecla por tecla);
* ``type_contenteditable`` — digitação em ``contenteditable``;
* ``click_send``        — clique real no botão Enviar;
* ``press_enter``       — Enter como alternativa (ou Ctrl+Enter, conforme o controle);
* ``js_set``            — último recurso: define o valor e dispara ``input``.

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
    "type",
    "type_contenteditable",
    "click_send",
    "press_enter",
    "js_set",
)


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "text_chars": len(self.text),
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

    Sem (1), (2) ou (3) o resultado é não confirmado. Texto divergente com o campo
    ainda preenchido continua sendo ambiguidade, não sucesso.
    """
    before_count = before.get("count", 0) or 0
    after_count = after.get("count", 0) or 0
    last = normalize_text(after.get("last"))
    wanted = normalize_text(expected)
    # Nonce (request_id) só existe se a mensagem foi publicada: é a evidência
    # mais forte que temos, e independe de o site reformatar o resto do texto.
    if nonce and after_count > before_count and nonce in last:
        return True, "nonce do pedido visível no balão novo (envio confirmado)"
    new_node = after_count > before_count
    previous = normalize_text(before.get("last"))
    same_node_changed = (not new_node and bool(previous) and bool(last) and previous != last)
    matches = bool(wanted) and bool(last) and (last == wanted or wanted in last)
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

def read_composer(locator: Any) -> Optional[str]:
    try:
        return locator.evaluate("el => el.isContentEditable ? el.textContent : el.value")
    except Exception:
        return None


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


def _fill(locator: Any, kind: str, text: str, strategy: str, delay_ms: int) -> None:
    if strategy == "fill":
        if kind == "contenteditable":
            # fill() funciona em contenteditable, mas não exercita o teclado:
            # mantemos como estratégia distinta abaixo.
            locator.fill(text)
        else:
            locator.fill(text)
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
    strategies: Sequence[str] = ("fill", "type", "type_contenteditable", "js_set"),
    activation: Sequence[str] = ("click_send", "press_enter"),
    delay_ms: int = 0,
    verify_timeout_ms: float = 5_000.0,
    settle_poll_ms: float = 50.0,
    user_selector: Optional[str] = None,
    before_activate: Any = None,
    nonce: Optional[str] = None,
) -> SendResult:
    """Tenta enviar ``text`` combinando preenchimento e ativação até haver evidência.

    Cada tentativa é independente: limpa o composer, preenche, ativa e verifica.
    Se nenhuma combinação produzir evidência, o resultado é falha **com as
    tentativas registradas** — nunca um falso sucesso.
    """
    started = time.perf_counter()
    locator = locator_for(page, composer)
    kind = control_kind(composer)
    before = user_message_state(page, user_selector)
    attempts: List[SendAttempt] = []

    for fill_strategy in strategies:
        if kind != "contenteditable" and fill_strategy == "type_contenteditable":
            continue
        if kind == "contenteditable" and fill_strategy == "fill":
            continue
        for activation_strategy in activation:
            attempt = SendAttempt(strategy=f"{fill_strategy}+{activation_strategy}", success=False)
            activated = False
            try:
                _clear(locator, kind)
                t0 = time.perf_counter()
                _fill(locator, kind, text, fill_strategy, delay_ms)
                attempt.fill_ms = (time.perf_counter() - t0) * 1000.0

                filled_value = read_composer(locator)
                t1 = time.perf_counter()
                if before_activate is not None:
                    before_activate()
                # Daqui em diante qualquer falha é ambígua: nunca reenviar.
                activated = True
                _activate(page, locator, send_button, kind, activation_strategy)
                attempt.send_ms = (time.perf_counter() - t1) * 1000.0

                t2 = time.perf_counter()
                ok, evidence, layer = _wait_evidence(page, before, text, verify_timeout_ms, settle_poll_ms,
                                                     user_selector, composer_getter=lambda: read_composer(locator),
                                                     filled=filled_value, nonce=nonce)
                attempt.verify_ms = (time.perf_counter() - t2) * 1000.0
                attempt.evidence = evidence
                attempt.layer = layer
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
                                  total_ms=(time.perf_counter() - started) * 1000.0)

    return SendResult(
        success=False,
        text=text,
        attempts=attempts,
        error="nenhuma estratégia produziu evidência de envio",
        total_ms=(time.perf_counter() - started) * 1000.0,
    )


def _wait_evidence(page: Any, before: Dict[str, Any], text: str,
                   timeout_ms: float, poll_ms: float, user_selector: Optional[str] = None,
                   composer_getter: Any = None, filled: Optional[str] = None,
                   nonce: Optional[str] = None) -> Tuple[bool, str, str]:
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
            return True, reason, layer
        last_reason = reason
        page.wait_for_timeout(poll_ms)
    return False, last_reason, layer
