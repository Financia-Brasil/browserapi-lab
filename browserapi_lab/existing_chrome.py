"""Conexão consentida ao Chrome existente. Sem lançar/copiar o perfil pessoal."""
import os
from pathlib import Path
import re


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


def verify_profile(context, expected):
    """Prova local do diretório pelo Chrome, antes de acessar qualquer chat.

    A permissão/endpoint identifica uma instalação, não a opção do inventário.
    Não ler cookies, contas, argumentos de processo ou outras abas. Só fechar a
    aba interna que criamos; nunca persistir o caminho pessoal lido.
    """
    probe = None
    try:
        probe = context.new_page()
        probe.goto('chrome://version/', wait_until='domcontentloaded', timeout=10000)
        if probe.url != 'chrome://version/':
            raise ValueError('not a browser-owned page')
        probe.wait_for_function("document.getElementById('profile_path')?.textContent.trim()", timeout=5000)
        actual = probe.locator('#profile_path').inner_text().strip()
        if not actual or not Path(actual).is_absolute():
            raise ValueError('missing profile path')
        if Path(actual).resolve() != Path(expected).resolve():
            raise ProfileMismatchError(
                'O Chrome concedeu outro perfil, não o escolhido. Paramos antes de abrir o chat ou escrever. '
                'A conexão automática pode expor somente o perfil padrão do Chrome; a lista de perfis não muda essa permissão. '
                'Abra o perfil desejado pelo avatar, confira Depuração remota e reconecte. '
                'Se o Chrome continuar concedendo outro perfil, este modo não suporta a seleção nessa versão. '
                'Não copie o perfil nem repita a configuração dos campos para resolver isso.')
    except ProfileMismatchError:
        raise
    except Exception:
        raise ExistingChromeError(
            'Não foi possível verificar o perfil recebido do Chrome. Nenhum chat foi aberto ou preenchido. '
            'Confira se a página interna chrome://version abre normalmente e reconecte; não assumimos outro perfil.') from None
    finally:
        if probe is not None:
            try:
                probe.close()
            except Exception:
                pass
