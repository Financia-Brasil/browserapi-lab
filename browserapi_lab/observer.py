"""Observação de streaming e detecção de término (Marco 5).

Mecanismo principal: ``MutationObserver`` instalado **dentro da página** pelo
probe (ADR-010). O Python apenas lê o resumo periodicamente e **decide**.

Três políticas comparáveis (nenhum sinal isolado é universal — briefing):

* ``stability_only`` — só estabilidade do conteúdo;
* ``ui_signals``     — só sinais de UI (Stop/Copy/``aria-busy``);
* ``hybrid``         — estabilidade **e** ausência de sinal de "ocupado",
                       com aceitação antecipada quando há confirmação de UI.

A decisão é uma função pura (:func:`decide`) sobre um estado explícito, o que
permite testar pausa artificial, resposta vazia, timeout e Copy prematuro sem
navegador.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .discovery import load_probe_js

POLICIES = ("stability_only", "ui_signals", "hybrid")


@dataclass
class WatchConfig:
    """Janelas e limites da detecção de término."""

    policy: str = "hybrid"
    stability_window_ms: float = 1_200.0
    min_text_len: int = 1
    timeout_ms: float = 60_000.0
    poll_interval_ms: float = 100.0
    early_accept_factor: float = 0.35   # fração da janela aceita com sinal de UI forte
    max_consecutive_errors: int = 3
    # Uma única leitura estável pode ser uma pausa do modelo, não o fim. Exigir
    # N amostras estáveis seguidas ("três leituras iguais") reduz o falso
    # término sem alongar a espera além de N × poll_interval.
    min_stable_samples: int = 1
    # Depois de decidir que terminou, espera mais este tempo e relê. Se o texto
    # voltar a crescer (ou o botão Stop reaparecer), a espera continua: é o
    # seguro contra entregar resposta pela metade numa pausa do modelo.
    confirm_window_ms: float = 0.0


@dataclass
class StreamState:
    """Estado lido da página (resumo do MutationObserver)."""

    mutation_count: int = 0
    first_token_ms: Optional[float] = None
    last_mutation_ms: Optional[float] = None
    since_last_mutation_ms: Optional[float] = None
    since_installed_ms: float = 0.0
    text_len: int = 0
    text_tail: str = ""
    stable_samples: int = 0   # contado pelo laço; a página não sabe disso
    events: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_summary(cls, summary: Dict[str, Any]) -> "StreamState":
        return cls(
            mutation_count=int(summary.get("mutation_count") or 0),
            first_token_ms=summary.get("first_token_ms"),
            last_mutation_ms=summary.get("last_mutation_ms"),
            since_last_mutation_ms=summary.get("since_last_mutation_ms"),
            since_installed_ms=float(summary.get("since_installed_ms") or 0.0),
            text_len=int(summary.get("text_len") or 0),
            text_tail=str(summary.get("text_tail") or ""),
            events=list(summary.get("events") or []),
        )


@dataclass
class UiSignals:
    aria_busy: Optional[str] = None
    stop_visible: bool = False
    copy_visible: bool = False
    pending_indicators: int = 0
    captcha: bool = False
    rate_limit: bool = False
    login_required: bool = False
    error: bool = False

    @classmethod
    def from_probe(cls, payload: Dict[str, Any]) -> "UiSignals":
        flags = payload.get("text_flags") or {}
        return cls(
            aria_busy=payload.get("aria_busy"),
            stop_visible=bool(payload.get("stop_visible")),
            copy_visible=bool(payload.get("copy_visible")),
            pending_indicators=int(payload.get("pending_indicators") or 0),
            captcha=bool(flags.get("captcha")),
            rate_limit=bool(flags.get("rate_limit")),
            login_required=bool(flags.get("login_required")),
            error=bool(flags.get("error")),
        )

    @property
    def blocking(self) -> Optional[str]:
        if self.captcha:
            return "captcha"
        if self.login_required:
            return "login_required"
        if self.rate_limit:
            return "rate_limit"
        if self.error:
            return "error"
        return None


@dataclass
class Decision:
    done: bool
    reason: str = ""
    status: str = "running"   # running | success | timeout | blocked

    def __bool__(self) -> bool:
        return self.done


def decide(state: StreamState, ui: Optional[UiSignals], config: WatchConfig) -> Decision:
    """Decide se o streaming terminou — função pura, sem efeito colateral.

    Ordem das regras:

    1. bloqueios explícitos (CAPTCHA, login, rate limit, erro) encerram;
    2. timeout absoluto encerra com status ``timeout``;
    3. sem conteúdo algum, nunca se encerra (protege contra falso positivo);
    4. política específica.
    """
    if ui is not None:
        bloqueio = ui.blocking
        if bloqueio:
            return Decision(True, f"sinal de bloqueio: {bloqueio}", "blocked")

    if state.since_installed_ms >= config.timeout_ms:
        return Decision(True, "timeout absoluto", "timeout")

    if state.text_len < config.min_text_len:
        return Decision(False, "sem conteúdo ainda", "running")

    if ui is not None and ui.stop_visible:
        return Decision(False, "botão Stop visível (ainda gerando)", "running")

    estavel = (
        state.since_last_mutation_ms is not None
        and state.since_last_mutation_ms >= config.stability_window_ms
    )

    pendencias = max(1, int(config.min_stable_samples))
    # ``stable_samples == 0`` com o padrão de 1 amostra = chamada direta de
    # teste/uso antigo, sem contagem: não inventa exigência nova.
    amostras_ok = pendencias <= 1 or int(state.stable_samples) >= pendencias

    if config.policy == "stability_only":
        if estavel and amostras_ok:
            return Decision(True, f"estável há {state.since_last_mutation_ms:.0f} ms", "success")
        if estavel:
            return Decision(False, f"estável, aguardando {pendencias} leitura(s)", "running")
        return Decision(False, "ainda instável", "running")

    if config.policy == "ui_signals":
        if ui is None:
            return Decision(False, "sem sinais de UI disponíveis", "running")
        parou = ui.aria_busy == "false" and not ui.stop_visible
        if parou and (ui.copy_visible or ui.pending_indicators == 0):
            return Decision(True, "sinais de UI indicam fim", "success")
        return Decision(False, "sinais de UI ainda indicam atividade", "running")

    if config.policy == "hybrid":
        if ui is not None and (ui.aria_busy == "true" or ui.pending_indicators > 0):
            return Decision(False, "UI ocupada", "running")
        if ui is None:
            ui = UiSignals()
        janela_curta = max(200.0, config.stability_window_ms * config.early_accept_factor)
        estavel_curto = (
            state.since_last_mutation_ms is not None
            and state.since_last_mutation_ms >= janela_curta
        )
        confirmacao_ui = (
            not ui.stop_visible
            and (ui.aria_busy == "false" or ui.copy_visible or ui.pending_indicators == 0)
        )
        if estavel and not ui.stop_visible and amostras_ok:
            return Decision(True, f"estável + sem Stop ({state.since_last_mutation_ms:.0f} ms)", "success")
        if estavel and not ui.stop_visible:
            return Decision(False, f"estável, aguardando {pendencias} leitura(s)", "running")
        if estavel_curto and confirmacao_ui and ui.aria_busy == "false" and ui.copy_visible:
            return Decision(
                True,
                f"estável há {state.since_last_mutation_ms:.0f} ms + Copy visível + aria-busy=false",
                "success",
            )
        return Decision(False, "sem estabilidade suficiente ou UI ainda ocupada", "running")

    raise ValueError(f"política desconhecida: {config.policy}")


@dataclass
class Observation:
    """Resultado de uma espera de streaming."""

    status: str = "running"
    reason: str = ""
    policy: str = "hybrid"
    ttft_ms: Optional[float] = None
    stream_ms: Optional[float] = None
    settle_overhead_ms: Optional[float] = None
    total_ms: float = 0.0
    mutation_count: int = 0
    text_len: int = 0
    polls: int = 0
    timeline: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "policy": self.policy,
            "ttft_ms": self.ttft_ms,
            "stream_ms": self.stream_ms,
            "settle_overhead_ms": self.settle_overhead_ms,
            "total_ms": round(self.total_ms, 2),
            "mutation_count": self.mutation_count,
            "text_len": self.text_len,
            "polls": self.polls,
            "timeline": self.timeline[-40:],
        }


# --------------------------------------------------------------------------
# Integração com a página
# --------------------------------------------------------------------------

def install(page: Any, root_selector: str = "#conversation",
            message_selector: Optional[str] = ".message",
            assistant_selector: Optional[str] = None,
            probe_path: Any = None, message_count_baseline: Optional[int] = None) -> None:
    """Instala o observador na página (probe injetado automaticamente)."""
    page.evaluate(load_probe_js() if probe_path is None else probe_path)
    page.evaluate(
        """(opts) => window.__bal.installWatcher(opts)""",
        {
            "rootSelector": root_selector,
            "messageSelector": message_selector,
            "assistantSelector": assistant_selector,
            "messageCountBaseline": message_count_baseline,
        },
    )


def mark_sent(page: Any) -> None:
    page.evaluate("() => window.__bal.markSent()")


def read_state(page: Any) -> StreamState:
    return StreamState.from_summary(page.evaluate("() => window.__bal.streamSummary()"))


def read_ui(page: Any, root_selector: str = "#conversation") -> UiSignals:
    payload = page.evaluate("(sel) => window.__bal.uiSignals({rootSelector: sel})", root_selector)
    return UiSignals.from_probe(payload)


def reset(page: Any) -> None:
    page.evaluate("() => window.__bal.resetWatcher()")


def wait_for_completion(
    page: Any,
    config: Optional[WatchConfig] = None,
    root_selector: str = "#conversation",
    on_poll: Any = None,
) -> Observation:
    """Espera o fim do streaming lendo o MutationObserver periodicamente.

    O poll é apenas a cadência de decisão: quem detecta as mutações é o
    observador dentro da página (ADR-010).
    """
    config = config or WatchConfig()
    if config.policy not in POLICIES:
        raise ValueError(f"política inválida: {config.policy}")

    started = time.perf_counter()
    observacao = Observation(policy=config.policy)
    erros = 0
    stable_samples = 0
    previous_text_len = None

    while True:
        try:
            state = read_state(page)
            ui = read_ui(page, root_selector)
            erros = 0
        except Exception as exc:  # página recarregando/navegando
            erros += 1
            if erros >= config.max_consecutive_errors:
                observacao.status = "failure"
                observacao.reason = f"falha ao ler a página: {type(exc).__name__}: {exc}"
                return observacao
            page.wait_for_timeout(config.poll_interval_ms)
            continue

        observacao.polls += 1
        observacao.mutation_count = state.mutation_count
        observacao.text_len = state.text_len

        # Amostras estáveis: janela de silêncio cumprida e texto do mesmo
        # tamanho da leitura anterior. Qualquer mutação zera a contagem.
        silencioso = (state.since_last_mutation_ms is not None
                      and state.since_last_mutation_ms >= config.stability_window_ms)
        if silencioso and state.text_len == previous_text_len:
            stable_samples += 1
        else:
            stable_samples = 0
        previous_text_len = state.text_len
        state.stable_samples = stable_samples

        decisao = decide(state, ui, config)
        if len(observacao.timeline) >= 400:
            del observacao.timeline[0]
        observacao.timeline.append(
            {
                "t_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "since_last_mutation_ms": state.since_last_mutation_ms,
                "text_len": state.text_len,
                "stop": ui.stop_visible,
                "copy": ui.copy_visible,
                "aria_busy": ui.aria_busy,
                "decision": decisao.reason,
            }
        )
        if on_poll is not None:
            on_poll(state, ui, decisao)

        if decisao.done:
            if (decisao.status == "success" and config.confirm_window_ms > 0
                    and state.since_installed_ms + config.confirm_window_ms < config.timeout_ms):
                # Relê depois de uma pausa curta: pausa do modelo não é o fim.
                page.wait_for_timeout(config.confirm_window_ms)
                try:
                    again = read_state(page)
                    again_ui = read_ui(page, root_selector)
                except Exception:
                    again, again_ui = None, None
                grew = again is not None and again.text_len > state.text_len
                resumed = bool(again_ui is not None and (again_ui.stop_visible or again_ui.aria_busy == "true"))
                if grew or resumed:
                    observacao.timeline.append({
                        "t_ms": round((time.perf_counter() - started) * 1000.0, 1),
                        "since_last_mutation_ms": getattr(again, "since_last_mutation_ms", None),
                        "text_len": getattr(again, "text_len", None),
                        "stop": getattr(again_ui, "stop_visible", None),
                        "copy": getattr(again_ui, "copy_visible", None),
                        "aria_busy": getattr(again_ui, "aria_busy", None),
                        "decision": "texto voltou a crescer (ou Stop reapareceu): continuar",
                    })
                    stable_samples = 0
                    previous_text_len = None
                    page.wait_for_timeout(config.poll_interval_ms)
                    continue
            observacao.status = decisao.status
            observacao.reason = decisao.reason
            break

        if (time.perf_counter() - started) * 1000.0 > config.timeout_ms * 1.5:
            observacao.status = "failure"
            observacao.reason = "timeout externo do laço de observação"
            break

        page.wait_for_timeout(config.poll_interval_ms)

    final = read_state(page)
    observacao.total_ms = (time.perf_counter() - started) * 1000.0
    observacao.ttft_ms = final.first_token_ms
    if final.first_token_ms is not None and final.last_mutation_ms is not None:
        observacao.stream_ms = round(final.last_mutation_ms - final.first_token_ms, 1)
        observacao.settle_overhead_ms = round(
            max(0.0, final.since_installed_ms - final.last_mutation_ms), 1
        )
    observacao.mutation_count = final.mutation_count
    observacao.text_len = final.text_len
    return observacao
