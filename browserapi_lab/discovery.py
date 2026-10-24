"""Descoberta de elementos por pontuação (Marco 3).

Contrato com o probe (ADR-002): o JavaScript devolve **fatos** sobre cada
elemento; quem decide o que é o composer, o botão de envio ou uma mensagem do
assistente é este módulo — em Python puro, testável sem navegador.

Nenhum seletor de site é tratado como contrato (ADR-005): seletores conhecidos
entram como bônus de hipótese (``known_hints``), nunca como única fonte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

PROBE_PATH = Path(__file__).resolve().parent / "assets" / "chat_probe.js"

# Papéis que o laboratório sabe procurar.
ROLES = ("composer", "send_button", "stop_button", "copy_button", "assistant_message",
         "user_message", "conversation")

# Textos aceitos por papel. São dicas, não contratos: o peso é moderado e sempre
# existe pontuação suficiente vinda de sinais estruturais (tag, role, atributos).
NAME_PATTERNS: Dict[str, str] = {
    "composer": r"(message|mensagem|prompt|pergunte|ask|digite|type|write|escreva|chat|input)",
    "send_button": r"(send|enviar|submit|postar|post)",
    "stop_button": r"(stop|parar|interromper|cancel|pause)",
    "copy_button": r"(copy|copiar|clipboard)",
}

ATTR_PATTERNS: Dict[str, str] = {
    "composer": r"(composer|prompt|message|input|chat|editor|msg)",
    "send_button": r"(send|submit|enviar|post)",
    "stop_button": r"(stop|cancel|parar)",
    "copy_button": r"(copy|copiar)",
}

ROLE_NAMES: Dict[str, Dict[str, tuple]] = {
    "assistant_message": {"yes": ("assistant", "model", "ai", "bot", "gemini", "gpt", "chatgpt"),
                          "no": ("user", "human", "you", "você", "voce", "prompt")},
    "user_message": {"yes": ("user", "human", "you", "você", "voce", "prompt"),
                     "no": ("assistant", "model", "ai", "bot", "gemini", "gpt")},
}

# Pesos: positivos somam, negativos subtraem. Tudo é explícito e auditável.
WEIGHTS: Dict[str, Dict[str, float]] = {
    "composer": {
        "tag_textarea": 14.0, "tag_input": 6.0, "tag_contenteditable": 12.0,
        "role_textbox": 12.0, "editable": 18.0, "name_match": 10.0,
        "placeholder_match": 8.0, "testid_match": 8.0, "aria_label_present": 6.0,
        "large_area": 4.0, "near_conversation": 6.0,
    },
    "send_button": {
        "tag_button": 12.0, "input_submit": 8.0, "role_button": 8.0,
        "name_match": 14.0, "testid_match": 8.0, "aria_label_present": 6.0,
        "near_composer": 6.0, "disabled": -20.0,
    },
    "stop_button": {
        "tag_button": 8.0, "role_button": 6.0, "name_match": 14.0,
        "testid_match": 8.0, "aria_label_present": 5.0,
    },
    "copy_button": {
        "tag_button": 8.0, "role_button": 6.0, "name_match": 14.0,
        "testid_match": 8.0, "aria_label_present": 5.0,
    },
    "assistant_message": {
        "data_role_yes": 30.0, "data_role_no": -30.0, "class_yes": 10.0, "class_no": -10.0,
        "has_text": 6.0, "has_code": 3.0, "last_in_conversation": 6.0,
    },
    "user_message": {
        "data_role_yes": 30.0, "data_role_no": -30.0, "class_yes": 10.0, "class_no": -10.0,
        "has_text": 6.0, "last_in_conversation": 4.0,
    },
    "conversation": {
        "role_log": 10.0, "aria_live": 8.0, "id_class_match": 8.0, "many_children": 6.0,
    },
}

# Sinais comuns a todos os papéis.
COMMON_SIGNALS: Dict[str, float] = {
    "visible": 12.0,
    "hidden": -25.0,
    "unique": 8.0,
    "kind_id": 10.0,
    "kind_testid": 12.0,
    "kind_aria_label": 8.0,
    "kind_placeholder": 8.0,
    "kind_name": 6.0,
    "kind_tag": 2.0,
    "kind_path": -2.0,
    "kind_nth": -10.0,
    "short_path": 4.0,
    "long_path": -6.0,
}

PENALTIES: Dict[str, float] = {
    "dynamic_class": -15.0,
    "uses_nth": -12.0,
    "ambiguous": -6.0,          # por ocorrência extra (limitado a 3)
    "language_dependent_selector": -3.0,
    "inside_open_shadow": -1.0,
    "inside_iframe": -2.0,
    "inside_closed_shadow": -100.0,
    "known_hint": 15.0,         # bônus de hipótese (nunca decisivo)
}

SELECTOR_TEXT_KINDS = ("aria-label", "placeholder")


@dataclass
class ScoredCandidate:
    candidate: Dict[str, Any]
    score: float
    signals: Dict[str, float] = field(default_factory=dict)
    penalties: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    rank: int = 0

    @property
    def selector(self) -> str:
        return str(self.candidate.get("selector", ""))

    @property
    def inside(self) -> str:
        return str(self.candidate.get("inside", "document"))

    @property
    def frame_path(self) -> List[str]:
        return list(self.candidate.get("frame_path") or [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "selector": self.selector,
            "score": round(self.score, 2),
            "inside": self.inside,
            "frame_path": self.frame_path,
            "signals": {k: round(v, 2) for k, v in self.signals.items()},
            "penalties": {k: round(v, 2) for k, v in self.penalties.items()},
            "reasons": self.reasons,
        }


def _matches(pattern: str, *values: Optional[str]) -> bool:
    rx = re.compile(pattern, re.IGNORECASE)
    return any(value and rx.search(str(value)) for value in values)


def _area(rect: Optional[Dict[str, Any]]) -> int:
    if not rect:
        return 0
    try:
        return int(rect.get("w", 0)) * int(rect.get("h", 0))
    except (TypeError, ValueError):
        return 0


def _distance(rect_a: Optional[Dict[str, Any]], rect_b: Optional[Dict[str, Any]]) -> Optional[float]:
    if not rect_a or not rect_b:
        return None
    try:
        dx = abs(int(rect_a.get("x", 0)) - int(rect_b.get("x", 0)))
        dy = abs(int(rect_a.get("y", 0)) - int(rect_b.get("y", 0)))
        return (dx ** 2 + dy ** 2) ** 0.5
    except (TypeError, ValueError):
        return None


def score_candidate(
    candidate: Dict[str, Any],
    role: str,
    known_hints: Optional[Sequence[str]] = None,
    reference_rect: Optional[Dict[str, Any]] = None,
    is_last: bool = False,
) -> ScoredCandidate:
    """Pontua um candidato devolvido pelo probe.

    Cada ponto entra em ``signals`` (positivos) ou ``penalties`` (negativos) para
    que o ranking seja explicável — é isso que permite diagnosticar mudanças de
    DOM em sites reais.
    """
    if role not in ROLES:
        raise ValueError(f"papel desconhecido: {role!r} (válidos: {ROLES})")

    weights = dict(COMMON_SIGNALS)
    weights.update(WEIGHTS.get(role, {}))

    signals: Dict[str, float] = {}
    penalties: Dict[str, float] = {}
    reasons: List[str] = []

    def add(kind: str, name: str, weight: float, reason: str) -> None:
        bucket = signals if weight >= 0 else penalties
        bucket[name] = bucket.get(name, 0.0) + weight
        if reason:
            reasons.append(reason)

    tag = str(candidate.get("tag") or "").lower()
    role_attr = str(candidate.get("role") or "").lower()
    text = " ".join(
        str(candidate.get(field) or "")
        for field in ("accessible_name", "aria_label", "placeholder", "input_name", "id", "testid_value")
    )

    # ---- sinais estruturais por papel
    if role == "composer":
        if tag == "textarea":
            add("+", "tag_textarea", weights["tag_textarea"], "textarea")
        elif tag == "input":
            add("+", "tag_input", weights["tag_input"], "input de texto")
        elif tag in ("div", "span", "p") and str(candidate.get("contenteditable")).lower() in ("true", ""):
            add("+", "tag_contenteditable", weights["tag_contenteditable"], "contenteditable")
        if role_attr == "textbox":
            add("+", "role_textbox", weights["role_textbox"], "role=textbox")
        if candidate.get("editable"):
            add("+", "editable", weights["editable"], "editável")
        if _matches(NAME_PATTERNS["composer"], candidate.get("accessible_name"), candidate.get("aria_label")):
            add("+", "name_match", weights["name_match"], "nome acessível sugere composer")
        if _matches(NAME_PATTERNS["composer"], candidate.get("placeholder")):
            add("+", "placeholder_match", weights["placeholder_match"], "placeholder sugere composer")
        if _matches(ATTR_PATTERNS["composer"], candidate.get("id"), candidate.get("testid_value"), candidate.get("input_name")):
            add("+", "testid_match", weights["testid_match"], "id/nome sugere composer")
        if candidate.get("aria_label"):
            add("+", "aria_label_present", weights["aria_label_present"], "tem aria-label")
        if _area(candidate.get("rect")) > 40_000:
            add("+", "large_area", weights["large_area"], "área grande")
        distance = _distance(candidate.get("rect"), reference_rect)
        if distance is not None and distance < 400:
            add("+", "near_conversation", weights["near_conversation"], "perto da conversa")

    elif role in ("send_button", "stop_button", "copy_button"):
        if tag == "button":
            add("+", "tag_button", weights["tag_button"], "é <button>")
        if tag == "input" and str(candidate.get("type") or "").lower() == "submit":
            add("+", "input_submit", weights["input_submit"], "input[type=submit]")
        if role_attr == "button":
            add("+", "role_button", weights["role_button"], "role=button")
        name_value = " ".join(
            str(candidate.get(f) or "") for f in ("accessible_name", "aria_label", "text_length")
        )
        if _matches(NAME_PATTERNS[role], candidate.get("accessible_name"), candidate.get("aria_label")):
            add("+", "name_match", weights["name_match"], f"nome sugere {role}")
        if _matches(ATTR_PATTERNS[role], candidate.get("id"), candidate.get("testid_value")):
            add("+", "testid_match", weights["testid_match"], f"id/testid sugere {role}")
        if candidate.get("aria_label"):
            add("+", "aria_label_present", weights["aria_label_present"], "tem aria-label")
        if role == "send_button":
            if candidate.get("disabled"):
                add("-", "disabled", weights["disabled"], "botão desabilitado")
            distance = _distance(candidate.get("rect"), reference_rect)
            if distance is not None and distance < 300:
                add("+", "near_composer", weights["near_composer"], "perto do composer")
        del name_value

    elif role in ("assistant_message", "user_message"):
        mapping = ROLE_NAMES[role]
        data_role = str(candidate.get("data_role") or "").lower()
        classes = " ".join(candidate.get("classes") or [])
        if data_role:
            if any(token in data_role for token in mapping["yes"]):
                add("+", "data_role_yes", weights["data_role_yes"], f"data-role={data_role}")
            elif any(token in data_role for token in mapping["no"]):
                add("-", "data_role_no", weights["data_role_no"], f"data-role={data_role} (papel oposto)")
        if _matches("|".join(mapping["yes"]), classes, candidate.get("id"), candidate.get("testid_value")):
            add("+", "class_yes", weights["class_yes"], "classe/id combinam com o papel")
        if _matches("|".join(mapping["no"]), classes, candidate.get("id")):
            add("-", "class_no", weights["class_no"], "classe/id sugerem o papel oposto")
        if int(candidate.get("text_length") or 0) > 0:
            add("+", "has_text", weights["has_text"], "tem texto")
        if role == "assistant_message" and candidate.get("has_code"):
            add("+", "has_code", weights["has_code"], "contém código")
        if is_last:
            add("+", "last_in_conversation", weights["last_in_conversation"], "última mensagem")

    elif role == "conversation":
        if role_attr in ("log", "list"):
            add("+", "role_log", weights["role_log"], f"role={role_attr}")
        if candidate.get("aria_live"):
            add("+", "aria_live", weights["aria_live"], "tem aria-live")
        if _matches(r"(convers|chat|thread|messages|history)", candidate.get("id"), " ".join(candidate.get("classes") or [])):
            add("+", "id_class_match", weights["id_class_match"], "id/classe sugerem conversa")
        if int(candidate.get("child_count") or 0) >= 2:
            add("+", "many_children", weights["many_children"], "vários filhos")

    # ---- sinais comuns
    if candidate.get("visible"):
        add("+", "visible", weights["visible"], "visível")
    else:
        add("-", "hidden", weights["hidden"], "não visível")

    occurrences = int(candidate.get("occurrences") or 0)
    if occurrences == 1:
        add("+", "unique", weights["unique"], "seletor único")
    elif occurrences > 1:
        extra = min(occurrences - 1, 3)
        add("-", "ambiguous", PENALTIES["ambiguous"] * extra, f"seletor casa com {occurrences} elementos")

    kind = str(candidate.get("selector_kind") or "")
    kind_key = f"kind_{kind.replace('-', '_')}"
    if kind_key in weights:
        add("+" if weights[kind_key] >= 0 else "-", kind_key, weights[kind_key], f"seletor por {kind}")

    path_length = int(candidate.get("path_length") or 1)
    if path_length <= 2:
        add("+", "short_path", weights["short_path"], "caminho curto")
    elif path_length > 4:
        add("-", "long_path", weights["long_path"], f"caminho longo ({path_length})")

    # ---- penalidades
    if candidate.get("dynamic_class"):
        add("-", "dynamic_class", PENALTIES["dynamic_class"], "classe dinâmica")
    if candidate.get("uses_nth"):
        add("-", "uses_nth", PENALTIES["uses_nth"], "usa nth-*")
    if kind in SELECTOR_TEXT_KINDS:
        add("-", "language_dependent_selector", PENALTIES["language_dependent_selector"],
            "seletor depende de texto (idioma)")
    inside = str(candidate.get("inside") or "document")
    if inside in ("open_shadow", "iframe", "closed_shadow"):
        add("-", f"inside_{inside}", PENALTIES[f"inside_{inside}"], f"dentro de {inside}")

    if known_hints:
        selector = str(candidate.get("selector") or "")
        testid = str(candidate.get("testid_value") or "")
        for hint in known_hints:
            if hint and (hint in selector or (testid and hint in testid)):
                add("+", "known_hint", PENALTIES["known_hint"], f"hipótese conhecida: {hint}")
                break

    total = sum(signals.values()) + sum(penalties.values())
    return ScoredCandidate(candidate=candidate, score=round(total, 3), signals=signals,
                           penalties=penalties, reasons=reasons)


def rank_candidates(
    candidates: Iterable[Dict[str, Any]],
    role: str,
    known_hints: Optional[Sequence[str]] = None,
    reference_rect: Optional[Dict[str, Any]] = None,
    top: Optional[int] = None,
) -> List[ScoredCandidate]:
    """Pontua e ordena candidatos (maior primeiro), numerando o ranking."""
    lista = list(candidates)
    # o probe devolve os nós em ordem de documento: o último da lista é a
    # mensagem mais recente (só importa para papéis de mensagem)
    scored = [
        score_candidate(candidate, role, known_hints, reference_rect,
                        is_last=(index == len(lista) - 1))
        for index, candidate in enumerate(lista)
    ]
    scored.sort(key=lambda item: (item.score, -int(item.candidate.get("path_length") or 0)), reverse=True)
    for position, item in enumerate(scored, start=1):
        item.rank = position
    return scored[:top] if top else scored


def ranking_report(
    payload: Dict[str, Any],
    role: str,
    known_hints: Optional[Sequence[str]] = None,
    reference_rect: Optional[Dict[str, Any]] = None,
    top: int = 10,
) -> Dict[str, Any]:
    """Relatório serializável do ranking (formato de RESULTS_SCHEMA §5)."""
    scored = rank_candidates(payload.get("candidates") or [], role, known_hints, reference_rect, top)
    return {
        "schema_version": "1.0",
        "role": role,
        "url": payload.get("url"),
        "visited_elements": payload.get("visited_elements"),
        "notes": payload.get("notes") or [],
        "known_hints": list(known_hints or []),
        "candidate_count": len(scored),
        "candidates": [item.to_dict() for item in scored],
        "winner": scored[0].to_dict() if scored else None,
    }


def drift_report(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """Compara dois rankings: o que mudou no DOM entre execuções (E-DIAG-1)."""
    def index(report: Dict[str, Any]) -> Dict[str, float]:
        return {item["selector"]: float(item["score"]) for item in report.get("candidates") or []}

    antes, depois = index(previous), index(current)
    vencedor_antes = (previous.get("winner") or {}).get("selector")
    vencedor_depois = (current.get("winner") or {}).get("selector")

    quedas = []
    for selector, score in antes.items():
        if selector in depois and depois[selector] < score - 5:
            quedas.append({"selector": selector, "de": score, "para": depois[selector]})

    return {
        "schema_version": "1.0",
        "role": current.get("role"),
        "vanished": sorted(set(antes) - set(depois)),
        "appeared": sorted(set(depois) - set(antes)),
        "score_drops": quedas,
        "winner_changed": vencedor_antes != vencedor_depois,
        "structure_changed": (previous.get("winner") or {}).get("inside") != (current.get("winner") or {}).get("inside"),
        "winner_before": vencedor_antes,
        "winner_after": vencedor_depois,
    }


# --------------------------------------------------------------------------
# Integração com o navegador (importado tardiamente; o núcleo não depende dele)
# --------------------------------------------------------------------------

def load_probe_js(path: Path | str = PROBE_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def install_probe(page: Any, path: Path | str = PROBE_PATH) -> None:
    """Injeta o probe na página (nunca pedimos ao usuário para colar JS)."""
    page.evaluate(load_probe_js(path))


def collect(page: Any, role: str, path: Path | str = PROBE_PATH) -> Dict[str, Any]:
    install_probe(page, path)
    return page.evaluate("(role) => window.__bal.collectCandidates({role: role})", role)


def discover(
    page: Any,
    role: str,
    known_hints: Optional[Sequence[str]] = None,
    reference_rect: Optional[Dict[str, Any]] = None,
    top: int = 10,
) -> Dict[str, Any]:
    payload = collect(page, role)
    return ranking_report(payload, role, known_hints, reference_rect, top)


def locate(page: Any, role: str, known_hints: Optional[Sequence[str]] = None,
           reference_rect: Optional[Dict[str, Any]] = None) -> Optional[ScoredCandidate]:
    report = discover(page, role, known_hints, reference_rect, top=1)
    candidates = report["candidates"]
    return candidates[0] if candidates else None
