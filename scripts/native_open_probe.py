#!/usr/bin/env python3
"""Experimento informativo: o fluxo REAL do produto contra o Google Chrome instalado.

Cria um Chrome descartável (pasta temporária, dois perfis vazios) e executa
``BrowserSession`` com o ``open_profile`` real para ``Default`` e ``Profile 1``.
Mostra se o pedido nativo ``--profile-directory`` chega ao processo existente,
se a aba de prova aparece por CDP, se o *Profile Path* confere, se as duas
sessões recebem identidades diferentes e se uma sessão nunca enxerga a aba da
outra, mesmo com a mesma origem.

Nunca toca ``~/.config`` nem contas reais. O resultado é evidência sobre um Chrome
descartável, não homologação do Chrome pessoal, que usa a permissão de depuração
por aprovação (diálogo nativo que a CI não consegue aceitar).
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('Default', 'Profile 1')


class ProbePage(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - API do http.server
        body = b'<!doctype html><meta charset="utf-8"><title>probe</title><p>probe</p>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def chrome_binary():
    return shutil.which('google-chrome') or shutil.which('google-chrome-stable')


def write_wrapper(path, binary, user_data_dir):
    """Wrapper do binário usado só neste experimento.

    ``open_profile`` real não passa ``--user-data-dir`` (usa a pasta padrão do
    usuário). O Chrome 136+ ignora ``--remote-debugging-port`` na pasta padrão,
    então o Chrome descartável usa uma pasta explícita e o wrapper repete essa
    pasta nos pedidos de perfil. O resto do pedido (``--profile-directory`` e a
    URL) é o do produto.
    """
    path.write_text('#!/bin/sh\nunset XDG_CONFIG_HOME\n'
                    'exec "%s" --user-data-dir="%s" --no-sandbox --password-store=basic '
                    '--no-first-run --no-default-browser-check "$@"\n' % (binary, user_data_dir))
    path.chmod(0o755)
    return str(path)


NOISE = ('dbus', 'object_proxy', 'XNNPACK', 'TensorFlow')


def interesting_log(path, limit=40):
    """Linhas do log do Chrome sem o ruído de D-Bus de um runner sem sessão."""
    lines = [line for line in path.read_text(errors='replace').splitlines() if not any(n in line for n in NOISE)]
    return lines[-limit:]


def target_urls(port):
    """URLs das abas pelo endpoint HTTP do Chrome descartável (modo padrão, sem aprovação)."""
    import urllib.request
    with urllib.request.urlopen('http://127.0.0.1:%s/json/list' % port, timeout=5) as response:
        return [item.get('url', '') for item in json.loads(response.read()) if item.get('type') == 'page']


def link(path):
    try:
        return os.readlink(path)
    except OSError as error:
        return 'ausente (%s)' % error.strerror


def process_states():
    """Estados dos processos chrome: um processo zumbi ('Z') ou ausente explicaria um hand-off recusado."""
    output = subprocess.run(['ps', '-eo', 'pid,ppid,stat,comm'], capture_output=True, text=True, timeout=10).stdout
    rows = [line.split(None, 3) for line in output.splitlines()[1:] if 'chrome' in line]
    return {'total': len(rows), 'zumbis': sum(1 for row in rows if 'Z' in row[2])}


def handoff(wrapper, root, port, target, directory='Default'):
    """Pedido nativo com a saída VISÍVEL (open_profile() descarta stdout/stderr)."""
    before = target_urls(port)
    begun = time.perf_counter()
    info = {'target': target.split('#')[0], 'directory': directory,
            'lock': link(root / 'SingletonLock'), 'socket_exists': 'ausente' not in link(root / 'SingletonSocket')}
    try:
        done = subprocess.run([wrapper, '--profile-directory=' + directory, target],
                              capture_output=True, text=True, timeout=45)
        info.update(exit_code=done.returncode, stdout=done.stdout[-300:], stderr=done.stderr[-900:])
    except subprocess.TimeoutExpired as error:
        info.update(exit_code='timeout', stdout=(error.stdout or b'')[-300:].decode(errors='replace'),
                    stderr=(error.stderr or b'')[-900:].decode(errors='replace'))
    info['seconds'] = round(time.perf_counter() - begun, 2)
    time.sleep(2)
    info['new_targets'] = [url.split('#')[0] for url in target_urls(port) if url not in before]
    return info


def finish(result, output):
    destination = Path(str(output) + '.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result['outcome'] == 'FAIL' else 0


def run(output):
    started = time.perf_counter()
    result = {'schema': 1, 'captured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'outcome': 'FAIL', 'error': None, 'steps': [],
              'scope': 'Chrome descartável em pasta temporária; não é o seu Chrome nem uma conta real.'}

    def note(step, **info):
        result['steps'].append({'t': round(time.perf_counter() - started, 2), 'step': step, **info})

    binary = chrome_binary()
    if not binary:
        result.update(outcome='SKIPPED', error='google-chrome não encontrado no PATH')
        return finish(result, output)
    result['chrome'] = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=30).stdout.strip()
    result['display_available'] = bool(os.environ.get('DISPLAY'))
    sys.path.insert(0, str(ROOT))

    tmp = Path(tempfile.mkdtemp(prefix='bal-probe-'))
    config_home = tmp / 'config'
    root = config_home / 'google-chrome'
    for directory in DIRECTORIES:
        (root / directory).mkdir(parents=True)
    log_path = tmp / 'chrome.log'
    chrome = server = None
    previous_xdg = os.environ.get('XDG_CONFIG_HOME')
    try:
        server = ThreadingHTTPServer(('127.0.0.1', 0), ProbePage)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = 'http://127.0.0.1:%d/' % server.server_address[1]
        clean_env = {key: value for key, value in os.environ.items() if key != 'XDG_CONFIG_HOME'}
        with log_path.open('wb') as log:
            chrome = subprocess.Popen(
                [binary, '--user-data-dir=' + str(root), '--remote-debugging-port=0', '--no-sandbox',
                 '--password-store=basic', '--no-first-run', '--no-default-browser-check', 'about:blank'],
                stdout=log, stderr=log, env=clean_env, start_new_session=True)
        deadline = time.monotonic() + 60
        while not (root / 'DevToolsActivePort').exists():
            if chrome.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('o Chrome descartável não expôs a porta (código %s)' % chrome.poll())
            time.sleep(0.2)
        note('chrome_started')

        wrapper = write_wrapper(tmp / 'chrome-wrapper.sh', binary, root)
        port = (root / 'DevToolsActivePort').read_text().splitlines()[0]
        # Diagnóstico ANTES do fluxo do produto: URL neutra e URL interna, com saída visível.
        # Ordem fixa (a primeira observação, em 2026-10-27, foi nesta ordem). Uma URL descartada
        # pode reaparecer como página inicial (chrome://newtab/) se ainda não houver janela.
        launches = (('about_blank_with_fragment', 'about:blank#browserapi-neutral'),
                    ('chrome_version', 'chrome://version/#browserapi-' + '0' * 32),
                    ('chrome_inspect', 'chrome://inspect/#remote-debugging'),
                    ('http_loopback', url + 'browserapi-handoff-http'))
        result['handoff'] = []
        for label, target in launches:
            result['handoff'].append(dict(label=label, **handoff(wrapper, root, port, target)))
        result['process_states'] = process_states()
        result['launch_opens_requested_page'] = {
            item['label']: [u for u in item['new_targets'] if u.split('#')[0] == item['target']] != []
            for item in result['handoff']}
        note('handoff_diagnostic', exit_codes=[item['exit_code'] for item in result['handoff']],
             opens_requested_page=result['launch_opens_requested_page'])
        # O código do produto lê a pasta de configuração do ambiente.
        os.environ['XDG_CONFIG_HOME'] = str(config_home)
        from browserapi_lab.browser import BrowserConfig, BrowserSession

        def config_for(directory):
            return BrowserConfig(profile='probe', profiles_root=tmp / 'app', attach_existing_chrome=True,
                                 existing_installation='chrome', existing_profile=directory)

        identities, sessions = {}, []
        with patch('browserapi_lab.profiles.chrome_binary', return_value=wrapper):
            for directory in DIRECTORIES:
                begun = time.perf_counter()
                with BrowserSession(config_for(directory)) as session:
                    page = session.page(url)
                    identities[directory] = session._profile_context_id
                    page.evaluate('name => { window.__probe = name }', directory)
                    sessions.append({'directory': directory, 'identity': identities[directory][:8],
                                     'verified_tag': getattr(page, '_browserapi_verified_profile', None),
                                     'seconds': round(time.perf_counter() - begun, 2)})
                note('session', **sessions[-1])
            result['sessions'] = sessions

            isolation = {}
            for directory in reversed(DIRECTORIES):
                with BrowserSession(config_for(directory)) as session:
                    isolation[directory] = session.page(url).evaluate('window.__probe')
                note('reopen', directory=directory, value=isolation[directory])
            result['reopen_isolation'] = isolation

            try:
                with BrowserSession(config_for('Profile 7')):
                    pass
                result['unknown_profile_rejected'] = False
            except ValueError:
                result['unknown_profile_rejected'] = True
            note('unknown_profile', rejected=result['unknown_profile_rejected'])

        from playwright.sync_api import sync_playwright
        from browserapi_lab.existing_chrome import endpoint
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(endpoint())
            targets = [t for t in browser.new_browser_cdp_session().send('Target.getTargets')['targetInfos']
                       if t['type'] == 'page' and t['url'].startswith(url)]
            result['probe_tabs'] = len(targets)
            result['probe_tab_context_ids'] = len({t['browserContextId'] for t in targets})
            result['playwright_contexts'] = len(browser.contexts)

        expected_isolation = {directory: directory for directory in DIRECTORIES}
        checks = {
            'tags_match_directories': [s['verified_tag'] for s in sessions] == list(DIRECTORIES),
            'identities_differ': len(set(identities.values())) == len(DIRECTORIES),
            'isolation_matches': isolation == expected_isolation,
            'unknown_profile_rejected': result['unknown_profile_rejected'],
            'two_tabs_two_identities': result['probe_tabs'] == 2 and result['probe_tab_context_ids'] == 2,
        }
        result['checks'] = checks
        result['outcome'] = 'PASS' if all(checks.values()) else 'FAIL'
        if result['outcome'] == 'FAIL':
            result['error'] = 'verificações que falharam: ' + ', '.join(k for k, v in checks.items() if not v)
    except Exception as error:  # noqa: BLE001 - o experimento relata qualquer causa
        result['error'] = '%s: %s' % (type(error).__name__, str(error)[:600])
    finally:
        if previous_xdg is None:
            os.environ.pop('XDG_CONFIG_HOME', None)
        else:
            os.environ['XDG_CONFIG_HOME'] = previous_xdg
        if chrome is not None:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    address = (root / 'DevToolsActivePort').read_text().splitlines()
                    pw.chromium.connect_over_cdp('ws://127.0.0.1:%s%s' % (address[0], address[1])) \
                        .new_browser_cdp_session().send('Browser.close')
            except Exception:  # noqa: BLE001 - encerrar o processo logo abaixo
                pass
            try:
                chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(chrome.pid, signal.SIGKILL)  # processo e filhos criados por este experimento
                chrome.wait()
        if result['outcome'] != 'PASS' and log_path.exists():
            result['chrome_log_filtered'] = interesting_log(log_path)
        if server is not None:
            server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    return finish(result, output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', default='results/ci/native-open-probe',
                        help='prefixo do arquivo de resultado (grava <prefixo>.json)')
    return run(parser.parse_args(argv).output)


if __name__ == '__main__':
    sys.exit(main())
