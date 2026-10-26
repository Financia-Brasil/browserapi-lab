"""Supervisor estável do instalador: trocar processo, nunca reload de código vivo."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

from .updates import UpdateStore


def _supervise(argv=None):
    if os.geteuid()==0:
        raise SystemExit('Abra BrowserAPI no menu da sua sessão, não como administrador.')
    arguments = sys.argv[1:] if argv is None else argv
    data = Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'browserapi-lab'
    store = UpdateStore(data)
    baseline = Path(__file__).resolve().parents[1]
    # O supervisor do .deb é a âncora. Releases ABI 1 não substituem este processo.
    env = dict(os.environ,BROWSERAPI_SUPERVISED='1')
    while True:
        active = store.activate()
        root = store.directory(active) if active else baseline
        boot = secrets.token_hex(16)
        env['BROWSERAPI_BOOT_ID'] = boot
        code = 'import sys; sys.path.insert(0,sys.argv.pop(1)); from browserapi_lab.gui import main; raise SystemExit(main())'
        if active and not store.read().get('trial'):
            store.write(trial=active)
        trial = store.read().get('trial')
        try:
            child = subprocess.Popen([sys.executable,'-c',code,str(root),*arguments],env=env,cwd=str(root))
        except OSError:
            if trial:
                store.rollback()
                continue
            raise
        if trial:
            try:
                result = child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    ready = json.loads((data/'started.json').read_text()).get('boot')==boot
                except (OSError,ValueError):
                    ready = False
                if ready:
                    store.confirm()
                    result = child.wait()
                else:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                    result = 1
            if result not in (0,75) and store.read().get('trial'):
                store.rollback()
                continue
            store.confirm()
        else:
            result = child.wait()
        if result!=75:
            return result
        # Mesmo endereço e token mantêm a aba existente; segredo nunca em logs.
        handoff = json.loads((data/'relaunch.json').read_text())
        env['BROWSERAPI_MANAGED_PORT'] = str(handoff['port'])
        env['BROWSERAPI_MANAGED_TOKEN'] = handoff['token']
        env['BROWSERAPI_NO_OPEN'] = '1'
        (data/'relaunch.json').unlink(missing_ok=True)


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if '--help' in arguments:
        from .gui import main as gui_main
        return gui_main(arguments)
    if os.geteuid()==0:
        raise SystemExit('Abra BrowserAPI no menu da sua sessão, não como administrador.')
    from .session import ProfileLock, ProfileBusyError
    data = Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'browserapi-lab'
    lock = ProfileLock(data/'supervisor-lock')
    try:
        lock.acquire()
    except ProfileBusyError:
        # Só abrir a janela existente; não ativar pending ou tocar em trial.
        from .gui import main as gui_main
        return gui_main(arguments)
    try:
        return _supervise(arguments)
    finally:
        lock.release()
