"""Painel local Ubuntu: stdlib, um worker Playwright, consentimento por botão."""
from collections import deque
import argparse
import importlib.util
import json
import os
from pathlib import Path
import queue
import secrets
import signal
import shutil
import site
import subprocess
import sys
import threading
import time
import venv
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import ChatConfig, ConfigStore, DEFAULT_CONFIG_DIR, PROVIDERS
from .session import ProfileBusyError, ProfileLock
from .setup import configure, check, pick, status

ASSETS = Path(__file__).parent / 'assets'
DATA_DIR = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'browserapi-lab'


def playwright_ready():
    return importlib.util.find_spec('playwright') is not None


def prepare_runtime(data_dir, tell, cancelled):
    """Somente ambiente do usuário. Nenhum sudo, apt, script remoto ou shell."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.geteuid() == 0:
        raise RuntimeError('A preparação deve ser feita pelo usuário, nunca como root.')
    if shutil.disk_usage(data_dir).free < 1500 * 1024**2:
        raise RuntimeError('Espaço insuficiente para preparar o navegador.')
    tell('Verificação inicial: ambiente do usuário e pelo menos 1,5 GB disponíveis.')
    with ProfileLock(data_dir / 'installation'):
        runtime = data_dir / 'runtime'
        tell('Preparando ambiente privado. Nenhum pacote do Python do sistema será alterado.')
        venv.EnvBuilder(with_pip=True).create(runtime)
        python = runtime / 'bin/python'
        for label, command in (
            ('Baixando o componente de automação. Isso pode levar alguns minutos.',
             [str(python), '-m', 'pip', 'install', '--no-input', '--disable-pip-version-check', 'playwright==1.64.1']),
            ('Baixando Chromium. Mantenha a conexão com a internet.',
             [str(python), '-m', 'playwright', 'install', 'chromium']),
        ):
            if cancelled():
                raise EOFError()
            tell(label)
            env = dict(os.environ)
            env.pop('PYTHONHOME', None)
            env.pop('PYTHONPATH', None)
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True, env=env)
            deadline = time.monotonic() + 900
            try:
                while True:
                    if cancelled() or time.monotonic() > deadline:
                        raise EOFError()
                    try:
                        code = process.wait(timeout=.2)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                if code:
                    raise RuntimeError('Não foi possível baixar os componentes.')
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
        # Mesmo Python/ABI usado para criar a venv; imports são tardios no navegador.
        paths = [runtime / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages']
        for path in paths:
            site.addsitedir(str(path))
        tell('Preparação concluída. Agora escolha o chat e clique em Configurar.')


class Panel:
    def __init__(self, store=None, data_dir=DATA_DIR, installer=prepare_runtime):
        self.store = store or ConfigStore(DEFAULT_CONFIG_DIR)
        self.data_dir = Path(data_dir)
        self.installer = installer
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.tasks = queue.Queue()
        self.cancelled = threading.Event()
        self.phase = 'idle'
        self.prompt = None
        self.answer = None
        self.receipt = None
        self.messages = deque(maxlen=60)
        self.thread = threading.Thread(target=self._worker, name='BrowserAPI', daemon=True)
        self.thread.start()

    def tell(self, text):
        with self.lock:
            self.messages.append(str(text))

    def ask(self, text):
        with self.condition:
            if self.cancelled.is_set():
                raise EOFError()
            identifier = secrets.token_hex(12)
            self.answer = None
            self.prompt = {'id': identifier, 'text': text.replace(' [s/N]', '').strip(),
                           'kind': 'yesno' if '[s/N]' in text else 'continue'}
            self.phase = 'waiting'
            self.condition.wait_for(lambda: self.answer is not None or self.cancelled.is_set())
            if self.cancelled.is_set():
                raise EOFError()
            value = self.answer
            self.prompt = None
            self.phase = 'running'
            return value

    def reply(self, identifier, value):
        with self.condition:
            if not self.prompt or self.prompt['id'] != identifier or self.answer is not None:
                raise ValueError('Pergunta encerrada. Aguarde a próxima etapa.')
            allowed = ('s', 'n') if self.prompt['kind'] == 'yesno' else ('',)
            if value not in allowed:
                raise ValueError('Resposta inválida.')
            self.answer = value
            self.condition.notify_all()

    def cancel(self):
        with self.condition:
            self.cancelled.set()
            self.condition.notify_all()

    def submit(self, payload):
        allowed = ('configure', 'check', 'repair', 'ask', 'doctor', 'prepare')
        if payload.get('operation') not in allowed:
            raise ValueError('Ação inválida.')
        if payload['operation'] == 'configure':
            provider = payload.get('provider')
            if provider not in (*PROVIDERS, 'custom'):
                raise ValueError('Escolha um chat válido.')
            config = ChatConfig(payload.get('name'), PROVIDERS.get(provider) or payload.get('url'),
                                provider=provider, browser=payload.get('browser')).validate()
            # Formulário básico só oferece produtos conhecidos. Não executa caminho recebido via HTTP.
            if config.browser not in ('chrome', 'chromium', 'msedge'):
                raise ValueError('Escolha Chrome, Chromium ou Edge.')
            if config.name in self.store.names():
                raise ValueError('Nome já salvo. Use Corrigir campos ou escolha outro nome.')
            task = (payload['operation'], config)
        elif payload['operation'] in ('check', 'repair', 'ask'):
            config = self.store.load(payload.get('name'))
            if payload['operation'] == 'ask' and (not isinstance(payload.get('message'), str)
                                                or not payload['message'].strip()
                                                or len(payload['message']) > 32000):
                raise ValueError('Digite uma mensagem de até 32 mil caracteres.')
            task = (payload['operation'], (config.name, payload.get('message')))
        else:
            task = (payload['operation'], None)
        with self.lock:
            if self.phase in ('running', 'waiting'):
                raise ValueError('Uma operação já está em andamento.')
            self.cancelled.clear()
            self.phase = 'running'
            self.prompt = None
            self.receipt = None
            self.messages.clear()
            self.tasks.put(task)

    def snapshot(self):
        with self.lock:
            chats = []
            for name in self.store.names():
                try:
                    config = self.store.load(name)
                    previous = status(self.store, name)
                    chats.append({'name': name, 'provider': config.provider, 'browser': config.browser,
                                  'compatible': previous.get('compatible_in_this_run', False),
                                  'checked_at': previous.get('checked_at')})
                except (OSError, ValueError, TypeError):
                    chats.append({'name': name, 'compatible': False, 'invalid': True})
            return {'phase': self.phase, 'prompt': self.prompt, 'messages': list(self.messages),
                    'receipt': self.receipt, 'chats': chats, 'prepared': playwright_ready()}

    def _worker(self):
        while True:
            task = self.tasks.get()
            if task is None:
                return
            operation, value = task
            try:
                common = dict(ask=self.ask, tell=self.tell, cancelled=self.cancelled.is_set)
                if operation == 'prepare':
                    self.installer(self.data_dir, self.tell, self.cancelled.is_set)
                elif operation == 'doctor':
                    from .doctor import build_report
                    report = build_report(results_path=str(Path.home()))
                    self.tell('Navegador pronto para automação.' if report.browser_ready else
                              'O ambiente ainda precisa de componentes. Clique em Preparar ou confira o navegador escolhido.')
                    self.tell('Janela gráfica disponível.' if report.display_server else
                              'Não foi encontrado um ambiente gráfico. Abra o programa na sua sessão normal do Ubuntu.')
                elif operation == 'configure':
                    self.receipt = configure(self.store, value.name, initial_config=value,
                                             picker=lambda page, role: pick(page, role, self.cancelled.is_set), **common)
                elif operation == 'repair':
                    self.receipt = configure(self.store, value[0], repairing=True,
                                             picker=lambda page, role: pick(page, role, self.cancelled.is_set), **common)
                else:
                    self.receipt = check(self.store, value[0], message=value[1] if operation == 'ask' else None, **common)
                with self.lock:
                    self.phase = 'done'
            except (EOFError, KeyboardInterrupt):
                self.tell('Operação interrompida. Isso não desfaz mensagens que já foram enviadas.')
                with self.lock:
                    self.phase = 'cancelled'
            except ProfileBusyError:
                self.tell('Este perfil já está aberto. Feche a outra janela do projeto que usa o mesmo chat e tente de novo.')
                with self.lock:
                    self.phase = 'error'
            except Exception:
                self.tell('Não foi possível concluir. Confira a conexão e o navegador. Use Preparar ou Corrigir campos. Nenhum reenvio automático foi feito.')
                with self.lock:
                    self.phase = 'error'
            finally:
                with self.lock:
                    self.prompt = None

    def close(self):
        self.cancel()
        self.tasks.put(None)
        self.thread.join(timeout=7)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, panel, port=0):
        self.panel = panel
        self.token = secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), Handler)

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_port}'

    @property
    def entry_url(self):
        return self.url + '/#' + self.token


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, code, body, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def authorized(self):
        supplied = self.headers.get('X-BrowserAPI-Token', '')
        return (self.host_ok() and secrets.compare_digest(supplied.encode(), self.server.token.encode())
                and self.headers.get('Origin', self.server.url) == self.server.url)

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {'error': 'Origem não autorizada.'})
        static = {'/': ('panel.html', 'text/html; charset=utf-8'),
                  '/panel.js': ('panel.js', 'text/javascript; charset=utf-8'),
                  '/panel.css': ('panel.css', 'text/css; charset=utf-8')}
        if self.path in static:
            name, mime = static[self.path]
            return self.send(200, (ASSETS / name).read_bytes(), mime)
        if not self.authorized():
            return self.send(403, {'error': 'Abra o programa pelo menu BrowserAPI para autorizar esta janela.'})
        if self.path == '/api/state':
            return self.send(200, self.server.panel.snapshot())
        return self.send(404, {'error': 'Página não encontrada.'})

    def do_POST(self):
        if not self.authorized():
            return self.send(403, {'error': 'Origem ou autorização inválida.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 131072:
                return self.send(413, {'error': 'Solicitação muito grande ou vazia.'})
            if self.headers.get('Content-Type') != 'application/json':
                return self.send(415, {'error': 'Formato inválido.'})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError()
            if self.path == '/api/task':
                self.server.panel.submit(payload)
            elif self.path == '/api/reply':
                self.server.panel.reply(payload.get('id'), payload.get('value'))
            elif self.path == '/api/cancel':
                self.server.panel.cancel()
            else:
                return self.send(404, {'error': 'Ação não encontrada.'})
            self.send(200, {'ok': True})
        except (ValueError, TypeError, OSError):
            self.send(400, {'error': 'Não foi possível iniciar. Confira os dados ou aguarde a operação atual terminar.'})


def main(argv=None):
    parser = argparse.ArgumentParser(description='Janela local do BrowserAPI para Ubuntu')
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--config-dir', default=str(DEFAULT_CONFIG_DIR))
    args = parser.parse_args(argv)
    panel = Panel(ConfigStore(args.config_dir))
    server = LocalServer(panel)
    # Exclusão entre janelas do aplicativo. Um segundo início abre o painel existente.
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    instance = DATA_DIR / 'window.json'
    lock = ProfileLock(DATA_DIR / 'window-lock')
    try:
        lock.acquire()
    except ProfileBusyError:
        panel.close()
        server.server_close()
        try:
            value = json.loads(instance.read_text())
            from urllib.request import Request, urlopen
            url = value['url']
            if not url.startswith('http://127.0.0.1:'):
                return 1
            with urlopen(Request(url + '/api/state', headers={'X-BrowserAPI-Token': value['token']}), timeout=2):
                pass
            if not args.no_open:
                webbrowser.open(url + '/#' + value['token'])
            return 0
        except Exception:
            return 1
    try:
        ConfigStore.write_json(instance, {'url': server.url, 'token': server.token})
        if not args.no_open:
            webbrowser.open(server.entry_url)
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        panel.close()
        server.server_close()
        instance.unlink(missing_ok=True)
        lock.release()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
