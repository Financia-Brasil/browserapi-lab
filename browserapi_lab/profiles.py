"""Inventário local de metadados. Nunca abrir bancos de credenciais ou cookies."""
import json
from itertools import islice
import os
from pathlib import Path
import re

INSTALLATIONS = {'chrome':'google-chrome','chrome-beta':'google-chrome-beta',
                 'chrome-unstable':'google-chrome-unstable','chromium':'chromium','edge':'microsoft-edge'}
CHROME_INSTALLATIONS = ('chrome','chrome-beta','chrome-unstable')


def installation_root(installation='chrome',config_home=None):
    if installation not in INSTALLATIONS:
        raise ValueError('Instalação desconhecida')
    base=Path(config_home) if config_home is not None else Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))
    return base/INSTALLATIONS[installation]


def profile_name(value):
    if not isinstance(value,str) or not re.fullmatch(r'(Default|Profile [0-9]{1,6})',value):
        raise ValueError('Perfil inválido')
    return value


def inventory(config_home=None):
    found=[]
    for installation in INSTALLATIONS:
        root=installation_root(installation,config_home)
        try:
            if root.is_symlink() or not root.is_dir() or root.stat().st_uid!=os.getuid():
                continue
            state=root/'Local State'
            cache={}
            if not state.is_symlink() and state.stat().st_uid==os.getuid() and state.stat().st_size<=2_000_000:
                with state.open('rb') as file:
                    raw=file.read(2_000_001)
                if len(raw)<=2_000_000:
                    value=json.loads(raw)
                    cache=value.get('profile',{}).get('info_cache',{})
            if not isinstance(cache,dict):
                cache={}
        except (OSError,ValueError,TypeError,AttributeError):
            cache={}
        # Somente Default/Profile N, inclusive sem Local State íntegro.
        try:
            entries=list(islice(root.iterdir(),200))
        except OSError:
            continue
        for path in sorted(entries):
            try:
                profile_name(path.name)
                if path.is_symlink() or not path.is_dir() or path.stat().st_uid!=os.getuid():
                    continue
                metadata=cache.get(path.name,{})
                label=metadata.get('name') if isinstance(metadata,dict) else None
                label=label[:100] if isinstance(label,str) else path.name
                found.append({'id':installation+':'+path.name,'installation':installation,'directory':path.name,
                              'label':label,'connectable':installation in CHROME_INSTALLATIONS,
                              'account_verified':False})
            except (OSError,ValueError):
                continue
    return found


CHROME_BINARIES = {
    'chrome': ('google-chrome', 'google-chrome-stable'),
    'chrome-beta': ('google-chrome-beta',),
    'chrome-unstable': ('google-chrome-unstable',),
}


def chrome_binary(installation):
    import shutil
    return next((path for name in CHROME_BINARIES.get(installation,())
                 if (path := shutil.which(name))),None)


def connection_inventory(config_home=None):
    """Estado do arquivo de endpoint, não prova de conexão/conta nem probe HTTP."""
    from .existing_chrome import endpoint, ExistingChromeError
    rows=inventory(config_home)
    for row in rows:
        row['openable']=bool(chrome_binary(row['installation']))
        row['endpoint_available']=False
        if row['connectable']:
            try:
                endpoint(config_home,installation=row['installation'])
                row['endpoint_available']=True
            except ExistingChromeError:
                pass
    return rows


def open_profile(identifier, target, config_home=None):
    """Pedido nativo ao Chrome: usa ProcessSingleton, não Playwright/user_data_dir.

    Sem shell, sem flags CDP, sem cópia de credenciais. Só perfis já inventariados.
    Chrome encaminha o pedido à instância existente ou abre a instalação normal.
    O retorno confirma o pedido ao SO, NÃO uma conexão CDP nem a conta correta.
    """
    import subprocess
    from .config import safe_url
    profile=next((row for row in inventory(config_home) if row['id']==identifier and row['connectable']),None)
    if profile is None:
        raise ValueError('Escolha um perfil do Chrome encontrado neste computador.')
    binary=chrome_binary(profile['installation'])
    if binary is None:
        raise ValueError('Esta instalação do Chrome não foi encontrada. Atualize a lista ou instale o Chrome pelo gerenciador gráfico.')
    native_proof = bool(re.fullmatch(r'chrome://version/#browserapi-[0-9a-f]{32}', target))
    if target!='chrome://inspect/#remote-debugging' and not native_proof:
        safe_url(target)
    try:
        process=subprocess.Popen([binary,'--profile-directory='+profile['directory'],target],
                                 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                 close_fds=True,start_new_session=True)
        try:
            code=process.wait(timeout=.8)
        except subprocess.TimeoutExpired:
            return  # Chrome continua aberto; não encerrar nem assumir conexão.
        if code!=0:
            raise ValueError('O Chrome recusou a abertura. Abra esse perfil pelo avatar do Chrome e tente conectar novamente.')
    except OSError:
        raise ValueError('Não foi possível abrir esta instalação do Chrome. Abra-a pelo menu e atualize a lista.') from None
