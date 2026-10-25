#!/usr/bin/env python3
"""Monta .deb sem instalar nada, sem dependências Python adicionais."""
import argparse
from pathlib import Path
import shutil
import runpy
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = runpy.run_path(str(ROOT / 'browserapi_lab/version.py'))['APP_VERSION']
DEPENDENCIES = (
    'python3 (>= 3.11), python3-venv, xdg-utils, '
    'libnss3, libnspr4, libatk1.0-0t64 | libatk1.0-0, '
    'libatk-bridge2.0-0t64 | libatk-bridge2.0-0, libcups2t64 | libcups2, '
    'libdrm2, libdbus-1-3, libxkbcommon0, libxcomposite1, libxdamage1, '
    'libxfixes3, libxrandr2, libgbm1, libasound2t64 | libasound2, '
    'libpango-1.0-0, libcairo2, libglib2.0-0t64 | libglib2.0-0, libx11-6, libxcb1, fonts-liberation'
)
LAUNCHER = '''#!/usr/bin/python3
import os
from pathlib import Path
import sys
root = Path('/usr/share/browserapi-lab')
data = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'browserapi-lab'
python = data / 'runtime/bin/python'
if sys.version_info < (3, 11):
    raise SystemExit('BrowserAPI requer Python 3.11 ou mais recente.')
# Nunca trocar para código gravável pelo usuário em execução privilegiada.
if os.geteuid() == 0:
    raise SystemExit('Abra BrowserAPI no menu da sua sessão, não como administrador.')
if python.is_file():
    os.execv(str(python), [str(python), str(root / 'open_window.py')])
sys.path.insert(0, str(root))
from browserapi_lab.gui import main
raise SystemExit(main())
'''
BOOTSTRAP = '''from browserapi_lab.gui import main
raise SystemExit(main())
'''
DESKTOP = '''[Desktop Entry]
Type=Application
Name=BrowserAPI
Comment=Configurar e testar seus chats no navegador
Exec=/usr/bin/browserapi-window
Icon=web-browser
Terminal=false
Categories=Network;Utility;
StartupNotify=false
'''


def build(output):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='browserapi-deb-') as tmp:
        stage = Path(tmp)
        control = stage / 'DEBIAN'
        control.mkdir()
        app = stage / 'usr/share/browserapi-lab'
        package = app / 'browserapi_lab'
        package.mkdir(parents=True)
        for source in sorted((ROOT / 'browserapi_lab').glob('*.py')):
            shutil.copyfile(source, package / source.name)
        assets = package / 'assets'
        assets.mkdir()
        for source in sorted((ROOT / 'browserapi_lab/assets').iterdir()):
            if source.suffix in ('.html', '.js', '.css'):
                shutil.copyfile(source, assets / source.name)
        (app / 'open_window.py').write_text(BOOTSTRAP)
        bin_dir = stage / 'usr/bin'
        bin_dir.mkdir(parents=True)
        launcher = bin_dir / 'browserapi-window'
        launcher.write_text(LAUNCHER)
        launcher.chmod(0o755)
        desktop = stage / 'usr/share/applications'
        desktop.mkdir(parents=True)
        (desktop / 'browserapi-lab.desktop').write_text(DESKTOP)
        docs = stage / 'usr/share/doc/browserapi-lab'
        docs.mkdir(parents=True)
        shutil.copyfile(ROOT / 'docs/UBUNTU.md', docs / 'LEIA-ME.md')
        if (ROOT / 'LICENSE').is_file():
            shutil.copyfile(ROOT / 'LICENSE', docs / 'copyright')
        size = sum(path.stat().st_size for path in stage.rglob('*') if path.is_file()) // 1024
        (control / 'control').write_text(
            f'Package: browserapi-lab\nVersion: {VERSION}\nSection: net\nPriority: optional\n'
            f'Architecture: all\nDepends: {DEPENDENCIES}\nInstalled-Size: {size}\n'
            'Maintainer: BrowserAPI Lab <noreply@github.com>\n'
            'Homepage: https://github.com/Financia-Brasil/browserapi-lab\n'
            'Description: Painel local assistido para chats no navegador\n'
            ' Janela com configuracao, autorizacao, teste e reparo de campos.\n'
            ' Ambiente experimental, sem servidor de API remoto.\n'
        )
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(stage), str(output)], check=True)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='dist/BrowserAPI-Ubuntu.deb')
    print(build(parser.parse_args().output))
