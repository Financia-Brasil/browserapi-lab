"""Conexão consentida ao Chrome existente. Sem lançar/copiar o perfil pessoal."""
import os
from pathlib import Path
import re
import time


class ExistingChromeError(RuntimeError):
    pass


def endpoint(config_home=None, installation='chrome'):
    root = Path(config_home) if config_home is not None else Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    from .profiles import installation_root, CHROME_INSTALLATIONS
    if installation not in CHROME_INSTALLATIONS:
        raise ExistingChromeError('Esta instalação não suporta a conexão pessoal implementada.')
    path = installation_root(installation,root) / 'DevToolsActivePort'
    try:
        if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_size > 1024:
            raise ValueError()
        lines = path.read_text().splitlines()
        if len(lines) != 2 or not lines[0].isdigit() or not 1 <= int(lines[0]) <= 65535:
            raise ValueError()
        if not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]{1,128}', lines[1]):
            raise ValueError()
        # Não fazer probe HTTP: o Chrome pode expor somente o WebSocket com confirmação.
        return f'ws://127.0.0.1:{int(lines[0])}{lines[1]}'
    except (OSError, ValueError, UnicodeError):
        raise ExistingChromeError('Não encontramos a conexão consentida do Chrome. Abra seu Chrome 144+, habilite Depuração remota em chrome://inspect/#remote-debugging e tente de novo. Algumas versões podem não disponibilizar essa conexão.') from None


class ProfileMismatchError(ExistingChromeError):
    """Não prosseguir no contexto concedido para outro perfil."""


def verify_profile(context, expected, probe=None):
    """Prova local do diretório pelo Chrome, antes de acessar qualquer chat.

    A permissão/endpoint identifica uma instalação, não a opção do inventário.
    Não ler cookies, contas, argumentos de processo ou outras abas. Só fechar a
    aba interna que criamos; nunca persistir o caminho pessoal lido.
    """
    stage = 'abrir página interna'
    try:
        if probe is None:
            probe = context.new_page()
            probe.goto('chrome://version/', wait_until='domcontentloaded', timeout=10000)
        if probe.url.partition('#')[0] != 'chrome://version/':
            raise ValueError('not a browser-owned page')
        stage = 'ler identificação do perfil'
        # WebUI pode bloquear eval usado por wait_for_function (CSP). Ler só
        # o campo nativo, sem relaxar CSP nem injetar código na página interna.
        deadline = time.monotonic() + 5
        field = probe.locator('#profile_path')
        actual = field.inner_text(timeout=5000).strip()
        while not actual and time.monotonic() < deadline:
            probe.wait_for_timeout(100)
            actual = field.inner_text(timeout=1000).strip()
        if not actual or not Path(actual).is_absolute():
            raise ValueError('missing profile path')
        actual_path, expected_path = Path(actual).resolve(), Path(expected).resolve()
        if actual_path != expected_path:
            if actual_path.parent != expected_path.parent:
                raise ProfileMismatchError(
                    'O Chrome conectado usa outra pasta de dados que a instalação escolhida. '
                    'Paramos antes de abrir o chat ou escrever. Escolha a instalação e o perfil que aparecem na lista, '
                    'ou abra o perfil pelo avatar do Chrome e reconecte. Não copie perfis para resolver isso.')
            raise ProfileMismatchError(
                'O Chrome concedeu outro perfil, não o escolhido. Paramos antes de abrir o chat ou escrever. '
                'Abra o perfil desejado pelo avatar do Chrome, confira a Depuração remota e reconecte. '
                'Se o Chrome continuar concedendo outro perfil, este modo não consegue usar esse perfil nesta versão. '
                'Não copie o perfil nem refaça os campos do chat para resolver isso.')
    except ProfileMismatchError:
        raise
    except Exception:
        raise ExistingChromeError(
            'Não foi possível verificar o perfil recebido do Chrome (' + stage + '). Nenhum chat foi aberto ou preenchido. '
            'Confira se a página interna chrome://version abre normalmente e reconecte; não assumimos outro perfil.') from None
    finally:
        if probe is not None:
            try:
                probe.close()
            except Exception:
                pass


def target_context_id(context, page):
    """Identidade real do target CDP, mesmo se Playwright agrupar perfis."""
    session = None
    try:
        session = context.new_cdp_session(page)
        value = session.send('Target.getTargetInfo')['targetInfo'].get('browserContextId')
        if not isinstance(value, str) or not value or len(value) > 256:
            raise ValueError()
        return value
    except Exception:
        raise ExistingChromeError('O Chrome não informou a identidade da aba. Paramos sem abrir ou preencher o chat.') from None
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass
