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
