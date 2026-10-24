"""CLI do laboratorio.

Marco 0 expoe apenas ``doctor``. Os demais comandos sao registrados conforme cada
marco e entregue (evita criar modulos vazios antes da hora).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="browserapi-lab",
        description="Laboratorio de pesquisa para automacao de chats de IA via navegador.",
    )
    parser.add_argument("--version", action="version", version=f"browserapi-lab {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="audita o ambiente (Marco 0)")
    doctor.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="caminho para gravar o relatorio em JSON (padrao: apenas stdout)",
    )
    doctor.add_argument(
        "--results",
        default="results",
        help="diretorio de resultados usado para medir disco (padrao: results)",
    )
    verify = sub.add_parser("verify", help="testa ponta a ponta a fixture e mede latência (sem sites reais)")
    verify.add_argument("--iterations", type=int, default=10)
    verify.add_argument("--results", default="results/verify")
    verify.add_argument("--channel", choices=("chromium", "chrome"), default="chromium")
    verify.add_argument("--headed", action="store_true", help="abre navegador visível; requer display")
    return parser


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import build_report, render_text

    report = build_report(results_path=args.results)
    print(render_text(report))
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"relatorio JSON gravado em: {path}")
    # Nao e falha: o doctor apenas diagnostica.
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "verify":
        if not 1 <= args.iterations <= 1000:
            parser.error("--iterations deve estar entre 1 e 1000")
        from .benchmark import verify
        try:
            summary = verify(args.iterations, args.results,
                             None if args.channel == "chromium" else args.channel, args.headed)
        except KeyboardInterrupt:
            print("Verificação interrompida; navegador e perfil liberados.", file=sys.stderr)
            return 130
        except Exception as exc:
            print(f"Verificação indisponível ({type(exc).__name__}). Execute doctor; "
                  "instale Chromium e suas dependências se necessário.", file=sys.stderr)
            return 2
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if summary["passed"] else 1
    parser.error(f"comando desconhecido: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
