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
    parser.add_argument("--config-dir", default=None, help="diretório local das configurações e perfis dedicados")
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
    for name, help_text in (("configure", "assistente para escolher navegador e chat"),
                            ("repair", "corrigir campos apontando na página"),
                            ("check", "testar um chat com uma mensagem autorizada"),
                            ("status", "mostrar última verificação, sem enviar nada"),
                            ("ask", "enviar uma mensagem com confirmação manual")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("name", help="nome salvo do chat, por exemplo meu-gemini")
    sub.add_parser("chats", help="listar chats configurados, sem abrir navegador")
    debug = sub.add_parser("chrome-debug",
                           help="configura a depuração do Chrome UMA vez (atalho com porta fixa)")
    debug.add_argument("--port", type=int, default=9222,
                       help="porta local de depuração (padrão 9222, só 127.0.0.1)")
    debug.add_argument("--open", action="store_true",
                       help="abre o Chrome agora, já com a porta ligada")
    debug.add_argument("--print", dest="show", action="store_true",
                       help="só mostra o atalho que seria criado; não grava nada")
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


def cmd_chrome_debug(args: argparse.Namespace) -> int:
    from . import persistent_chrome
    from .browser import chrome_executable
    from .profiles import installation_root

    executable = chrome_executable()
    user_data_dir = installation_root("chrome")
    if not executable:
        print("Chrome não encontrado. Instale o Google Chrome e tente de novo.")
        return 1
    script = persistent_chrome.launcher_script(executable, user_data_dir, args.port)
    if args.show:
        print(script)
        return 0
    try:
        paths = persistent_chrome.install(executable, user_data_dir, port=args.port)
    except persistent_chrome.PersistentChromeError as problem:
        print(f"Não foi possível criar o atalho: {problem}")
        return 1
    print("Depuração configurada uma vez:")
    print(f"  atalho de terminal : {paths['launcher']}")
    print(f"  atalho de aplicativo: {paths['desktop']}")
    print(f"  porta local         : 127.0.0.1:{args.port}")
    print(f"  perfil do Chrome    : {user_data_dir}")
    print()
    print("Abra o Chrome por esse atalho e faça login uma vez. Nas próximas vezes,")
    print("o programa só se conecta — sem reabrir chrome://inspect.")
    print("Feche as outras janelas desse Chrome antes de usar o atalho.")
    if args.open:
        try:
            address = persistent_chrome.start(executable, user_data_dir, args.port)
        except persistent_chrome.PersistentChromeError as problem:
            print(f"O Chrome não abriu com a porta: {problem}")
            return 1
        print(f"Chrome aberto e respondendo em {address}")
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
    if args.command == "chrome-debug":
        return cmd_chrome_debug(args)
    if args.command in ("configure", "repair", "check", "status", "ask", "chats"):
        from .config import ConfigStore, DEFAULT_CONFIG_DIR
        from .setup import configure, check, status
        from .session import ProfileBusyError
        store = ConfigStore(args.config_dir or DEFAULT_CONFIG_DIR)
        try:
            if args.command == "chats":
                print(json.dumps(store.names(), ensure_ascii=False))
                return 0
            if args.command == "status":
                receipt = status(store, args.name)
            elif args.command in ("configure", "repair"):
                receipt = configure(store, args.name, repairing=args.command == "repair")
            else:
                message = input("Sua mensagem (não será gravada em relatório): ") if args.command == "ask" else None
                if args.command == "ask" and not message.strip():
                    print("Mensagem vazia; nada enviado.", file=sys.stderr)
                    return 2
                receipt = check(store, args.name, message=message)
            print(json.dumps(receipt, indent=2, ensure_ascii=False))
            return 0 if receipt.get("compatible_in_this_run") else 1
        except ProfileBusyError:
            print("Perfil em uso. Feche a outra execução deste chat e tente novamente.", file=sys.stderr)
            return 2
        except (KeyboardInterrupt, EOFError):
            print("Cancelado; não retomaremos nem reenviaremos automaticamente.", file=sys.stderr)
            return 130
        except (OSError, ValueError, TypeError):
            print("Configuração inválida ou ausente. Execute configure; se já configurou, use repair. "
                  "Consulte --help para as opções.", file=sys.stderr)
            return 2
        except Exception:
            print("Não foi possível abrir ou acessar o navegador. Execute doctor, confira a rede e "
                  "selecione um navegador instalado. Nenhum detalhe privado foi registrado.", file=sys.stderr)
            return 2
    parser.error(f"comando desconhecido: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
