"""Depuração do Chrome configurada **uma vez** e reaproveitada sempre.

O problema que este módulo resolve (relato): *"eu queria que você melhorasse
esse negócio de tá manualmente permitindo a depuração do navegador toda vez, tem
como só configurar uma vez que funciona pra sempre?"*

Abrir `chrome://inspect/#remote-debugging` e ligar a depuração vale para a
**sessão** do Chrome: fechou o navegador, acabou. A alternativa que não expira é
iniciar o Chrome com uma porta de depuração fixa (`--remote-debugging-port`),
apontando para um diretório de perfil **dedicado** — login feito uma vez, cookies
persistidos, e a porta sempre no mesmo lugar.

Aqui ficam, sem depender de Playwright:

* ``probe`` — o Chrome está escutando em 127.0.0.1:porta? Devolve o WebSocket.
* ``launcher_script``/``desktop_entry`` — o texto do atalho de uma vez só.
* ``install`` — grava o atalho (+ entrada de aplicativo) de forma atômica.
* ``start`` — abre o Chrome já com a porta, destacado do processo.
* ``find``/``ensure`` — usa o que já existe, abre se preciso, ou explica.

Tudo escuta só em 127.0.0.1: a porta de depuração dá controle total do navegador
e não pode ficar exposta na rede.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
from urllib.parse import urlsplit
import urllib.request

DEFAULT_PORT = 9222
LOOPBACK = ('127.0.0.1', 'localhost', '::1')
_WS_PATH = re.compile(r'/devtools/browser/[A-Za-z0-9-]{1,128}')
LAUNCHER_NAME = 'browserapi-chrome-debug'
DESKTOP_NAME = 'browserapi-chrome-debug.desktop'


class PersistentChromeError(RuntimeError):
    """Sem porta de depuração e sem como abrir: o texto diz o que fazer."""


def _applications_dir():
    base = Path(os.environ.get('XDG_DATA_HOME') or (Path.home() / '.local' / 'share'))
    return base / 'applications'


def probe(port=DEFAULT_PORT, timeout=1.5):
    """WebSocket de depuração em ``127.0.0.1:porta``, ou ``None``.

    Usa ``/json/version`` (stdlib): é o mesmo endpoint que o Chrome publica, e
    não exige Playwright. Qualquer host que não seja loopback é recusado — o
    endereço tem que ser da própria máquina.
    """
    if type(port) is not int or not 1 <= port <= 65535:
        return None
    url = f'http://127.0.0.1:{port}/json/version'
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            raw = response.read(65_536)
    except Exception:
        return None
    try:
        value = json.loads(raw.decode('utf-8', 'replace'))
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    address = value.get('webSocketDebuggerUrl')
    if not isinstance(address, str) or not address.startswith('ws://'):
        return None
    parts = urlsplit(address)
    if parts.hostname not in LOOPBACK or not _WS_PATH.fullmatch(parts.path or ''):
        return None
    return address


def launcher_script(executable, user_data_dir, port=DEFAULT_PORT):
    """Conteúdo do atalho: o **seu** Chrome, com a porta de depuração ligada.

    ``user_data_dir`` é a pasta de dados da instalação escolhida (a mesma que o
    app verifica em ``chrome://version``), não uma cópia: nada de perfil
    duplicado. Como o Chrome só aceita um processo por pasta de dados, feche as
    janelas desse Chrome antes de abrir pelo atalho.
    """
    exe = shlex.quote(str(executable))
    profile = shlex.quote(str(user_data_dir))
    return (
        '#!/bin/sh\n'
        '# Gerado por BrowserAPI — não precisa editar.\n'
        f'# Abre o Chrome com depuração local em 127.0.0.1:{int(port)}, no mesmo perfil de sempre.\n'
        f'exec {exe} \\\n'
        f'  --remote-debugging-port={int(port)} \\\n'
        '  --remote-debugging-address=127.0.0.1 \\\n'
        f'  --user-data-dir={profile} \\\n'
        '  --no-first-run --no-default-browser-check "$@"\n'
    )


def desktop_entry(launcher_path, port=DEFAULT_PORT, name='BrowserAPI · Chrome com depuração'):
    """Entrada de aplicativo para abrir o Chrome no modo que a API precisa."""
    # O campo Exec do .desktop tem regras próprias de aspas (não é shell).
    path = str(launcher_path)
    if any(character in path for character in ' \t"\\'):
        path = '"' + path.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return (
        '[Desktop Entry]\n'
        'Type=Application\n'
        f'Name={name}\n'
        f'Comment=Abre o Chrome com depuração local (127.0.0.1:{int(port)}) para o BrowserAPI\n'
        f'Exec={path} %U\n'
        'Terminal=false\n'
        'Categories=Network;WebBrowser;\n'
        'StartupNotify=true\n'
    )


def _write_private(path: Path, text: str, mode: int = 0o644) -> Path:
    """Grava de forma atômica, sem seguir symlink e sem sobrescrever diretório."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise PersistentChromeError(f'{path} é um link simbólico; não gravamos por cima.')
    if path.exists() and path.is_dir():
        raise PersistentChromeError(f'{path} é um diretório; esperávamos um arquivo.')
    temporary = path.with_name(path.name + '.new')
    if temporary.is_symlink() or temporary.exists():
        temporary.unlink()
    temporary.write_text(text, encoding='utf-8')
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    return path


def install(executable, user_data_dir, port=DEFAULT_PORT, root=None):
    """Cria o atalho de uma vez e devolve os caminhos gerados.

    ``root`` permite testar sem tocar em ``~/.local``. Rodar de novo reescreve
    os mesmos arquivos (idempotente): mudar a porta ou o perfil exige só chamar
    de novo.
    """
    if not executable:
        raise PersistentChromeError('Não encontramos o executável do Chrome. Instale o '
                                    'Chrome ou aponte o caminho no painel.')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise PersistentChromeError('A porta de depuração precisa estar entre 1024 e 65535.')
    root = Path(root) if root is not None else None
    bin_dir = (root / 'bin') if root else (Path.home() / '.local' / 'bin')
    apps_dir = (root / 'applications') if root else _applications_dir()
    launcher = _write_private(bin_dir / LAUNCHER_NAME,
                              launcher_script(executable, user_data_dir, port), 0o755)
    desktop = _write_private(apps_dir / DESKTOP_NAME, desktop_entry(launcher, port), 0o644)
    return {'launcher': launcher, 'desktop': desktop, 'port': port,
            'user_data_dir': str(user_data_dir)}


def start(executable, user_data_dir, port=DEFAULT_PORT, timeout=20.0):
    """Abre o Chrome destacado com a porta ligada e espera ela responder.

    Devolve o WebSocket. Não abre nada duas vezes: se a porta já responde, usa o
    Chrome que está lá (é o caso normal depois da primeira configuração).
    """
    address = probe(port)
    if address:
        return address
    if not executable:
        raise PersistentChromeError('Não encontramos o executável do Chrome para abrir.')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise PersistentChromeError('Porta de depuração inválida.')
    Path(user_data_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
    command = [str(executable), f'--remote-debugging-port={int(port)}',
               '--remote-debugging-address=127.0.0.1',
               f'--user-data-dir={user_data_dir}',
               '--no-first-run', '--no-default-browser-check', 'about:blank']
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    except OSError as problem:
        raise PersistentChromeError(
            f'Não foi possível abrir o Chrome ({type(problem).__name__}). '
            'Confira o caminho do executável e tente de novo.') from problem
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        address = probe(port)
        if address:
            return address
        time.sleep(0.25)
    raise PersistentChromeError(
        f'O Chrome abriu, mas a porta {port} não respondeu em {int(timeout)} s. '
        'Feche outras janelas do Chrome abertas com o mesmo atalho e tente de novo. '
        'Se o aviso de segurança do sistema aparecer, autorize uma vez.')


def find(port=0, config_home=None, installation='chrome'):
    """Endpoint já disponível, sem abrir nada.

    Ordem: porta configurada (a que o atalho usa) e, se não houver, a conexão
    temporária que o Chrome publica em ``DevToolsActivePort``.
    """
    if type(port) is int and port:
        address = probe(port)
        if address:
            return {'address': address, 'source': f'porta {port}', 'port': port}
    from .existing_chrome import ExistingChromeError, endpoint
    try:
        address = endpoint(config_home=config_home, installation=installation)
    except ExistingChromeError:
        return None
    return {'address': address, 'source': 'DevToolsActivePort (sessão atual)', 'port': 0}


def ensure(port=DEFAULT_PORT, *, executable=None, user_data_dir=None, auto_launch=False,
           config_home=None, installation='chrome', timeout=20.0):
    """Endpoint para conectar: usa o existente ou abre o Chrome se autorizado.

    ``auto_launch`` é a decisão guardada na conexão ("configurar uma vez"): sem
    ela, nada é aberto — só explicamos o próximo passo.
    """
    found = find(port=port, config_home=config_home, installation=installation)
    if found:
        return found
    if auto_launch and executable and user_data_dir:
        address = start(executable, user_data_dir, port=port, timeout=timeout)
        return {'address': address, 'source': f'aberto agora na porta {port}', 'port': port}
    raise PersistentChromeError(
        'O Chrome não está com a depuração ligada. Abra o Chrome pelo atalho '
        '"Chrome com depuração" (criado por Configurar uma vez) ou ligue a opção '
        '"abrir o Chrome sozinho" na conexão. Nada foi aberto agora.')
