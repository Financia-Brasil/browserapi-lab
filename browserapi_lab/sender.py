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

import time
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "success": self.success,
            "fill_ms": round(self.fill_ms, 2),
            "send_ms": round(self.send_ms, 2),
            "verify_ms": round(self.verify_ms, 2),
            "evidence": self.evidence,
            "composer_confirmed": self.composer_confirmed,
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

COUNT_USER_MESSAGES = """(args) => {
  const nodes = document.querySelectorAll('[data-role="user"], .message[data-role="user"]');
  let ultimo = null;
  if (nodes.length) {
    const body = nodes[nodes.length - 1].querySelector('.body') || nodes[nodes.length - 1];
    ultimo = (body.innerText !== undefined && body.innerText !== null) ? body.innerText : body.textContent;
  }
  return { count: nodes.length, last: ultimo ? String(ultimo).trim() : null };
}"""


def user_message_state(page: Any) -> Dict[str, Any]:
    return page.evaluate(COUNT_USER_MESSAGES, {})


def evidence_of_send(before: Dict[str, Any], after: Dict[str, Any], expected: str) -> Tuple[bool, str]:
    """Sucesso exige mensagem nova **com o texto esperado** (não só contagem)."""
    if after.get("count", 0) <= before.get("count", 0):
        return False, "nenhuma nova mensagem do usuário"
    last = (after.get("last") or "").strip()
    wanted = expected.strip()
    if last == wanted:
        return True, "nova mensagem do usuário com o texto esperado"
    if wanted and wanted in last:
        return True, "nova mensagem do usuário contendo o texto esperado"
    return False, "mensagem nova, mas texto divergente"


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
) -> SendResult:
    """Tenta enviar ``text`` combinando preenchimento e ativação até haver evidência.

    Cada tentativa é independente: limpa o composer, preenche, ativa e verifica.
    Se nenhuma combinação produzir evidência, o resultado é falha **com as
    tentativas registradas** — nunca um falso sucesso.
    """
    started = time.perf_counter()
    locator = locator_for(page, composer)
    kind = control_kind(composer)
    before = user_message_state(page)
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
                # Daqui em diante qualquer falha é ambígua: nunca reenviar.
                activated = True
                _activate(page, locator, send_button, kind, activation_strategy)
                attempt.send_ms = (time.perf_counter() - t1) * 1000.0

                t2 = time.perf_counter()
                ok, evidence = _wait_evidence(page, before, text, verify_timeout_ms, settle_poll_ms)
                attempt.verify_ms = (time.perf_counter() - t2) * 1000.0
                attempt.evidence = evidence
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
                   timeout_ms: float, poll_ms: float) -> Tuple[bool, str]:
    deadline = time.perf_counter() + (timeout_ms / 1000.0)
    last_reason = "sem evidência"
    while time.perf_counter() < deadline:
        after = user_message_state(page)
        ok, reason = evidence_of_send(before, after, text)
        if ok:
            return True, reason
        last_reason = reason
        page.wait_for_timeout(poll_ms)
    return False, last_reason
