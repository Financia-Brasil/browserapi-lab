"""Escrita e validacao de resultados (Marco 0).

Implementa o esquema descrito em ``docs/RESULTS_SCHEMA.md``:

* um envelope JSON por execucao (``results/json/<run_id>.json``);
* CSV longo de metricas (``results/csv/metrics.csv``);
* CSV largo de execucoes (``results/csv/runs.csv``).

Somente biblioteca padrao. Nada aqui grava cookies, tokens ou conteudo de mensagens
(ADR-009): o chamador e responsavel por passar apenas dados sanitizados.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = "1.0"

REQUIRED_FIELDS = (
    "schema_version",
    "run_id",
    "timestamp_utc",
    "milestone",
    "experiment",
    "target",
    "strategy",
    "iteration",
    "status",
    "error",
    "env",
    "metrics",
    "events",
)

VALID_STATUS = ("success", "failure", "timeout", "skipped")

# Colunas fixas do CSV largo (RESULTS_SCHEMA.md secao 4.2).
RUNS_COLUMNS = (
    "run_id",
    "timestamp_utc",
    "milestone",
    "experiment",
    "target",
    "strategy",
    "iteration",
    "status",
    "error",
    "total_ms",
    "ttft_ms",
    "stream_ms",
    "settle_overhead_ms",
    "discovery_ms",
    "fill_ms",
    "send_ms",
    "extract_ms",
    "python_rss_kb",
    "browser_rss_kb",
    "mutation_count",
    "candidate_count",
    "success",
)

METRICS_COLUMNS = (
    "run_id",
    "timestamp_utc",
    "milestone",
    "experiment",
    "target",
    "strategy",
    "iteration",
    "status",
    "metric",
    "value",
    "unit",
)

# Unidades conhecidas; metricas novas entram com unidade vazia.
UNITS = {
    "ms": (
        "discovery_ms",
        "fill_ms",
        "send_ms",
        "ttft_ms",
        "stream_ms",
        "settle_overhead_ms",
        "extract_ms",
        "total_ms",
    ),
    "KB": ("python_rss_kb", "browser_rss_kb"),
    "count": ("mutation_count", "candidate_count", "iterations", "failures"),
    "bool": ("success",),
}


def new_run_id(now: Optional[float] = None) -> str:
    """ID unico e ordenavel: data/hora UTC compacta + sufixo aleatorio curto."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now if now is not None else time.time()))
    return f"{stamp}-{secrets.token_hex(3)}"


def utc_now_iso(now: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now is not None else time.time()))


def unit_for(metric: str) -> str:
    for unit, names in UNITS.items():
        if metric in names:
            return unit
    return ""


@dataclass
class Run:
    """Envelope de uma execucao de experimento."""

    experiment: str
    target: str = "unit"
    milestone: str = "M0"
    strategy: str = "none"
    iteration: int = 1
    env: Dict[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=new_run_id)
    timestamp_utc: str = field(default_factory=utc_now_iso)
    status: str = "success"
    error: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: Dict[str, Optional[str]] = field(default_factory=dict)

    def metric(self, name: str, value: Any) -> "Run":
        self.metrics[name] = value
        return self

    def event(self, t_ms: float, type_: str, detail: Optional[str] = None) -> "Run":
        event: Dict[str, Any] = {"t_ms": round(float(t_ms), 3), "type": type_}
        if detail is not None:
            event["detail"] = detail
        self.events.append(event)
        return self

    def finish(self, status: str, error: Optional[str] = None) -> "Run":
        if status not in VALID_STATUS:
            raise ValueError(f"status invalido: {status!r} (validos: {VALID_STATUS})")
        self.status = status
        self.error = error
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "timestamp_utc": self.timestamp_utc,
            "milestone": self.milestone,
            "experiment": self.experiment,
            "target": self.target,
            "strategy": self.strategy,
            "iteration": self.iteration,
            "status": self.status,
            "error": self.error,
            "env": self.env,
            "metrics": self.metrics,
            "events": self.events,
            "artifacts": self.artifacts,
        }


def validate_envelope(envelope: Dict[str, Any]) -> List[str]:
    """Retorna a lista de problemas do envelope (vazia == valido)."""
    problems: List[str] = []
    for key in REQUIRED_FIELDS:
        if key not in envelope:
            problems.append(f"campo obrigatorio ausente: {key}")
    if envelope.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version incompativel: {envelope.get('schema_version')!r} != {SCHEMA_VERSION!r}"
        )
    status = envelope.get("status")
    if status is not None and status not in VALID_STATUS:
        problems.append(f"status invalido: {status!r}")
    metrics = envelope.get("metrics")
    if metrics is not None and not isinstance(metrics, dict):
        problems.append("metrics deve ser objeto")
    events = envelope.get("events")
    if events is not None:
        if not isinstance(events, list):
            problems.append("events deve ser lista")
        else:
            for i, ev in enumerate(events):
                if not isinstance(ev, dict) or "t_ms" not in ev or "type" not in ev:
                    problems.append(f"evento {i} invalido: {ev!r}")
    return problems


def read_envelopes(paths: Iterable[Path]) -> List[Dict[str, Any]]:
    envelopes = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            envelopes.append(json.load(handle))
    return envelopes


def metrics_rows(envelope: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Converte um envelope em linhas do CSV longo (uma por metrica)."""
    base = {
        "run_id": envelope.get("run_id", ""),
        "timestamp_utc": envelope.get("timestamp_utc", ""),
        "milestone": envelope.get("milestone", ""),
        "experiment": envelope.get("experiment", ""),
        "target": envelope.get("target", ""),
        "strategy": envelope.get("strategy", ""),
        "iteration": envelope.get("iteration", ""),
        "status": envelope.get("status", ""),
    }
    rows = []
    for name, value in sorted((envelope.get("metrics") or {}).items()):
        rows.append({**base, "metric": name, "value": _csv_value(value), "unit": unit_for(name)})
    return rows


def run_row(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Converte um envelope em uma linha do CSV largo."""
    metrics = envelope.get("metrics") or {}
    return {
        "run_id": envelope.get("run_id", ""),
        "timestamp_utc": envelope.get("timestamp_utc", ""),
        "milestone": envelope.get("milestone", ""),
        "experiment": envelope.get("experiment", ""),
        "target": envelope.get("target", ""),
        "strategy": envelope.get("strategy", ""),
        "iteration": envelope.get("iteration", ""),
        "status": envelope.get("status", ""),
        "error": envelope.get("error") or "",
        "total_ms": _csv_value(metrics.get("total_ms")),
        "ttft_ms": _csv_value(metrics.get("ttft_ms")),
        "stream_ms": _csv_value(metrics.get("stream_ms")),
        "settle_overhead_ms": _csv_value(metrics.get("settle_overhead_ms")),
        "discovery_ms": _csv_value(metrics.get("discovery_ms")),
        "fill_ms": _csv_value(metrics.get("fill_ms")),
        "send_ms": _csv_value(metrics.get("send_ms")),
        "extract_ms": _csv_value(metrics.get("extract_ms")),
        "python_rss_kb": _csv_value(metrics.get("python_rss_kb")),
        "browser_rss_kb": _csv_value(metrics.get("browser_rss_kb")),
        "mutation_count": _csv_value(metrics.get("mutation_count")),
        "candidate_count": _csv_value(metrics.get("candidate_count")),
        "success": _csv_value(metrics.get("success")),
    }


def _csv_value(value: Any) -> str:
    """Metricas ausentes viram celula vazia; booleanos viram true/fast (RESULTS_SCHEMA secao 2)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") if value == value else ""
    return str(value)


class ResultWriter:
    """Grava envelopes JSON e mantem os dois CSVs agregados."""

    def __init__(self, results_dir: os.PathLike | str = "results") -> None:
        self.root = Path(results_dir)
        self.json_dir = self.root / "json"
        self.csv_dir = self.root / "csv"
        self.json_dir.mkdir(parents=True, exist_ok=True)
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        self.metrics_csv = self.csv_dir / "metrics.csv"
        self.runs_csv = self.csv_dir / "runs.csv"

    def write(self, run: Run) -> Path:
        envelope = run.to_dict()
        problems = validate_envelope(envelope)
        if problems:
            raise ValueError("envelope invalido: " + "; ".join(problems))
        path = self.json_dir / f"{run.run_id}.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
        self._append_csv(self.metrics_csv, METRICS_COLUMNS, metrics_rows(envelope))
        self._append_csv(self.runs_csv, RUNS_COLUMNS, [run_row(envelope)])
        return path

    def write_candidates(self, run_id: str, payload: Dict[str, Any]) -> Path:
        """Arquivo auxiliar de candidatos (RESULTS_SCHEMA secao 5)."""
        path = self.json_dir / f"{run_id}.candidates.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return path

    @staticmethod
    def _append_csv(path: Path, columns: Iterable[str], rows: List[Dict[str, Any]]) -> None:
        header = list(columns)
        exists = path.exists() and path.stat().st_size > 0
        with open(path, "a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            for row in rows:
                writer.writerow(row)


def env_facts() -> Dict[str, Any]:
    """Fatos minimos do ambiente para o campo ``env`` do envelope."""
    try:
        import playwright  # import tardio: o nucleo funciona sem playwright

        pw_version = getattr(playwright, "__version__", None)
        if pw_version is None:
            from importlib.metadata import version

            try:
                pw_version = version("playwright")
            except Exception:  # pragma: no cover - ambiente sem metadados
                pw_version = None
    except Exception:
        pw_version = None

    ram_total_kb = None
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    ram_total_kb = int(line.split()[1])
                    break
    except OSError:
        pass

    ci = any(
        os.environ.get(name)
        for name in ("CI", "GITHUB_ACTIONS", "CODESPACES", "GITHUB_CODESPACES_TOKEN")
    )

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "ram_total_kb": ram_total_kb,
        "playwright": pw_version,
        "browser_channel": "none",
        "browser_version": None,
        "headed": False,
        "ci": bool(ci),
    }
