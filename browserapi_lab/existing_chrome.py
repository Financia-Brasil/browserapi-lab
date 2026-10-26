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
