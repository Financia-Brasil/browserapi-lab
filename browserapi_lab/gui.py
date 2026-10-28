"""Painel local Ubuntu: stdlib, um worker Playwright, consentimento por botão."""
from collections import deque
import argparse
from dataclasses import replace
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

from .config import ChatConfig, ConfigStore, DEFAULT_CONFIG_DIR, PROVIDERS, safe_name
from .session import ProfileBusyError, ProfileLock
from .setup import configure, check, pick, status, point_controls
from .existing_chrome import ExistingChromeError
from .version import APP_VERSION
from .telemetry import Telemetry
from .transcript import Transcript

ASSETS = Path(__file__).parent / 'assets'
DATA_DIR = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'browserapi-lab'


class PanelInputError(ValueError):
    """Mensagem controlada, segura para exibição; nunca exceção bruta do navegador/SO."""


def activate_private_runtime(data_dir):
    # Um supervisor iniciado antes de Preparar pode ainda usar o Python do
    # sistema. Reativar os mesmos pacotes privados também em código atualizado
    # por supervisores ABI 1 anteriores, sem pedir nova preparação ao usuário.
    if os.geteuid() == 0:
        return
    packages = Path(data_dir)/'runtime/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    if packages.is_dir():
        site.addsitedir(str(packages))


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
        self.telemetry = Telemetry()
        self.transcript = Transcript()
        self.updater = None
        self.closed = False
        self.api_service = None
        self.warm = None
        self.thread = threading.Thread(target=self._worker, name='BrowserAPI', daemon=True)
        self.thread.start()

    def tell(self, text):
        with self.lock:
            self.messages.append(str(text))

    def record_answer(self, name, question, answer, receipt):
        """Guarda o turno validado na memória do painel; nunca no recibo.

        Só é chamado depois de uma resposta nova confirmada. Falhar aqui não
        pode transformar um envio bem-sucedido em erro da tarefa.
        """
        timings = receipt.get('timings') if isinstance(receipt, dict) else None
        total = timings.get('total_ms') if isinstance(timings, dict) else None
        self.transcript.add_exchange(name, question, answer, total_ms=total)
        # Contabilidade medida (caracteres), sem transformar em tokens inventados.
        self.telemetry.usage(len(question), len(answer))

    def ask(self, text):
        with self.condition:
            if self.cancelled.is_set():
                raise EOFError()
            identifier = secrets.token_hex(12)
            self.answer = None
            self.prompt = {'id': identifier, 'text': text.replace(' [s/N]', '').strip(),
                           'kind': 'yesno' if '[s/N]' in text else 'continue'}
            self.phase = 'waiting'
            wait_started = time.perf_counter()
            try:
                self.condition.wait_for(lambda: self.answer is not None or self.cancelled.is_set())
            finally:
                self.telemetry.user_wait((time.perf_counter() - wait_started) * 1000)
            if self.cancelled.is_set():
                raise EOFError()
            value = self.answer
            self.prompt = None
            self.phase = 'running'
            return value

    def reply(self, identifier, value):
        with self.condition:
            if not self.prompt or self.prompt['id'] != identifier or self.answer is not None:
                raise PanelInputError('Pergunta encerrada. Aguarde a próxima etapa.')
            allowed = ('s', 'n') if self.prompt['kind'] == 'yesno' else ('',)
            if value not in allowed:
                raise PanelInputError('Resposta inválida.')
            self.answer = value
            self.condition.notify_all()

    def cancel(self):
        with self.condition:
            self.cancelled.set()
            self.condition.notify_all()

    def submit(self, payload):
        allowed = ('configure', 'check', 'repair', 'ask', 'doctor', 'prepare', 'point_voice', 'point_send', 'use_existing')
        if payload.get('operation') not in allowed:
            raise PanelInputError('Este painel pediu uma ação não reconhecida. Reabra BrowserAPI pelo menu; se você atualizou, reinicie para encerrar a versão antiga.')
        if payload['operation'] == 'configure':
            provider = payload.get('provider')
            if provider not in (*PROVIDERS, 'custom'):
                raise PanelInputError('Escolha um chat válido.')
            try:
                from .profiles import inventory
                selected=payload.get('personal_profile','')
                profile=next((p for p in inventory() if p['id']==selected and p['connectable']),None) if selected else None
                if selected and profile is None:
                    raise ValueError('Perfil não encontrado')
                config = ChatConfig(payload.get('name'), PROVIDERS.get(provider) or payload.get('url'),
                                    provider=provider, browser=payload.get('browser'), session_mode=payload.get('session_mode', 'dedicated'),
                                    personal_installation=profile['installation'] if profile else 'chrome',
                                    personal_profile=profile['directory'] if profile else '').validate()
            except (ValueError, TypeError):
                raise PanelInputError('Confira o nome (letras, números, hífen ou sublinhado), a URL sem parâmetros e a sessão. Chrome já aberto exige Google Chrome.') from None
            # Formulário básico só oferece produtos conhecidos. Não executa caminho recebido via HTTP.
            if config.browser not in ('chrome', 'chromium', 'msedge'):
                raise PanelInputError('Escolha Chrome, Chromium ou Edge.')
            if config.name in self.store.names():
                raise PanelInputError('Nome já salvo. Use Corrigir campos ou escolha outro nome.')
            task = (payload['operation'], config)
        elif payload['operation'] in ('check', 'repair', 'ask', 'point_voice', 'point_send', 'use_existing'):
            try:
                config = self.store.load(payload.get('name'))
            except (ValueError, TypeError, OSError):
                raise PanelInputError('Chat salvo não encontrado ou configuração inválida. Atualize o painel e selecione um chat existente.') from None
            if payload['operation'] == 'ask' and (not isinstance(payload.get('message'), str)
                                                or not payload['message'].strip()
                                                or len(payload['message']) > 32000):
                raise PanelInputError('Digite uma mensagem de até 32 mil caracteres.')
            selection=None
            if payload['operation']=='use_existing' and payload.get('personal_profile'):
                from .profiles import inventory
                selection=next((p for p in inventory() if p['id']==payload['personal_profile'] and p['connectable']),None)
                if selection is None:
                    raise PanelInputError('Perfil não encontrado no inventário local.')
            task = (payload['operation'], (config.name, payload.get('message'),selection))
        else:
            task = (payload['operation'], None)
        with self.lock:
            if self.closed or self.phase in ('running', 'waiting', 'updating'):
                raise PanelInputError('Uma operação já está em andamento.')
            self.cancelled.clear()
            self.phase = 'running'
            self.prompt = None
            self.receipt = None
            self.messages.clear()
            self.tasks.put(task)

    def submit_api(self,job):
        from .llm_api import APIError
        with self.lock:
            if self.closed or self.phase in ('running','waiting','updating'):
                raise APIError('Uma operação já está ativa','busy',409)
            self.cancelled.clear()
            self.phase='running'
            self.receipt=None
            self.prompt=None
            self.tasks.put(('api',job))

    def snapshot(self):
        with self.lock:
            chats = []
            for name in self.store.names():
                try:
                    config = self.store.load(name)
                    previous = status(self.store, name)
                    chats.append({'name': name, 'provider': config.provider, 'browser': config.browser, 'session_mode': config.session_mode,
                                  'compatible': previous.get('compatible_in_this_run', False),
                                  'checked_at': previous.get('checked_at'), 'personal_installation':config.personal_installation,'personal_profile':config.personal_profile,
                                  'conversation': self.transcript.summary(name)})
                except (OSError, ValueError, TypeError):
                    chats.append({'name': name, 'compatible': False, 'invalid': True,
                                  'conversation': {'turns': 0, 'revision': 0, 'characters': 0, 'dropped': 0}})
            return {'version': APP_VERSION, 'phase': self.phase, 'prompt': self.prompt, 'messages': list(self.messages),
                    'receipt': self.receipt, 'chats': chats, 'prepared': playwright_ready(), 'telemetry': self.telemetry.snapshot(),
                    'api_service': self.api_service.snapshot() if self.api_service else {'enabled':False,'available':False},
                    'updates': self.updater.snapshot() if self.updater else {'managed':False,'enabled':False,'status':'unmanaged','message':'Atualização automática disponível no aplicativo instalado.'}}

    def _worker(self):
        while True:
            task = self.tasks.get()
            if task is None:
                if self.warm:
                    self.warm.close()
                return
            operation, value = task
            if operation == 'api_close':
                if self.warm:
                    self.warm.close()
                continue
            end_phase = 'error'
            try:
                if operation != 'api' and self.warm:
                    self.warm.close()
                name = value.names[0] if operation == 'api' else value.name if operation == 'configure' else value[0] if isinstance(value, tuple) else None
                self.telemetry.begin(operation, name)
                common = dict(ask=self.ask, tell=self.tell, cancelled=self.cancelled.is_set)
                if operation == 'api':
                    from .llm_api import WarmBrowser, APIError
                    if self.warm is None:
                        self.warm=WarmBrowser(self.store)
                    value.observe=self.telemetry.source
                    self.warm.run(value,self.cancelled.is_set)
                    if value.result:
                        if value.result.answer and len(value.result.answer)>1_000_000:
                            value.result.answer=None
                            value.error=APIError('Resposta excede limite local; consulte o navegador, não repita','response_too_large',502)
                        self.telemetry.source(value.config.name)
                        self.receipt=value.result.receipt(value.config)
                        self.receipt['attempts']=[{'name':a['model'],'status':a['status']} for a in value.attempts]
                elif operation == 'prepare':
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
                                             picker=lambda page, role: pick(page, role, self.cancelled.is_set), manual_send=True, **common)
                elif operation == 'use_existing':
                    if self.ask('Mudar este chat salvo para conectar ao Chrome já aberto, sem iniciar perfil separado? A conexão seguinte pedirá permissão e pode acessar todas as abas/contas. [s/N] ') == 's':
                        config = replace(self.store.load(value[0]), browser='chrome', executable=None, session_mode='existing_chrome',
                                         personal_installation=value[2]['installation'] if len(value)>2 and value[2] else 'chrome',
                                         personal_profile=value[2]['directory'] if len(value)>2 and value[2] else '').validate()
                        self.store.save(config)
                        self.tell('Modo salvo: Chrome já aberto. Abra o chat na conta desejada e autorize a conexão ao usar os botões de seleção. Nenhuma janela foi aberta nesta mudança.')
                    else:
                        self.tell('Modo anterior preservado. Nenhum navegador foi aberto.')
                elif operation in ('point_voice', 'point_send'):
                    self.receipt = point_controls(self.store, value[0], 'voice' if operation == 'point_voice' else 'send',
                        picker=lambda page, role: pick(page, role, self.cancelled.is_set), **common)
                elif operation == 'repair':
                    self.receipt = configure(self.store, value[0], repairing=True,
                                             picker=lambda page, role: pick(page, role, self.cancelled.is_set), manual_send=True, **common)
                else:
                    # O texto fica na conversa do painel, não duplicado no log.
                    self.receipt = check(self.store, value[0], message=value[1] if operation == 'ask' else None,
                                         record=self.record_answer, show_answer=False, **common)
                end_phase = 'done'
            except (EOFError, KeyboardInterrupt):
                self.tell('Operação interrompida. Isso não desfaz mensagens que já foram enviadas.')
                end_phase = 'cancelled'
            except ExistingChromeError as error:
                self.tell(str(error))
                end_phase = 'error'
            except ProfileBusyError:
                self.tell('Este perfil já está aberto. Feche a outra janela do projeto que usa o mesmo chat e tente de novo.')
                end_phase = 'error'
            except Exception:
                self.tell('Não foi possível concluir. Confira a conexão e o navegador. Use Preparar ou Corrigir campos. Nenhum reenvio automático foi feito.')
                end_phase = 'error'
            finally:
                with self.lock:
                    # Publicar conclusão + métricas atomicamente: submit não pode
                    # apagar o recibo da tarefa anterior antes de finish.
                    self.telemetry.finish(self.receipt, end_phase)
                    self.phase = end_phase
                    self.prompt = None
                    if operation == 'api':
                        from .llm_api import APIError
                        if value.result is None and value.error is None:
                            value.error=APIError('Execução interrompida ou fonte não disponível; confira o navegador antes de repetir','execution_failed',409)
                        value.prompt=''
                        if value.owner:
                            value.owner.complete(value)
                        value.done.set()

    def close(self):
        with self.lock:
            self.closed = True
        self.cancel()
        self.tasks.put(None)
        self.thread.join(timeout=7)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, panel, port=0):
        self.panel = panel
        managed = os.environ.get('BROWSERAPI_SUPERVISED') == '1'
        port = int(os.environ.get('BROWSERAPI_MANAGED_PORT','0')) if managed else port
        self.token = os.environ.get('BROWSERAPI_MANAGED_TOKEN') if managed else None
        self.token = self.token or secrets.token_urlsafe(32)
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
        if self.path == '/favicon.ico':
            return self.send(204, b'', 'image/x-icon')
        static = {'/': ('panel.html', 'text/html; charset=utf-8'),
                  '/panel.js': ('panel.js', 'text/javascript; charset=utf-8'),
                  '/panel.css': ('panel.css', 'text/css; charset=utf-8')}
        if self.path in ('/inter.ttf','/mono.ttf'):
            from .font_assets import content
            return self.send(200,content('inter' if self.path=='/inter.ttf' else 'mono'),'font/ttf')
        if self.path in static:
            name, mime = static[self.path]
            return self.send(200, (ASSETS / name).read_bytes(), mime)
        if not self.authorized():
            return self.send(403, {'error': 'Abra o programa pelo menu BrowserAPI para autorizar esta janela.'})
        if self.path == '/api/profiles':
            from .profiles import connection_inventory
            return self.send(200,{'profiles':connection_inventory()})
        if self.path == '/api/state':
            return self.send(200, self.server.panel.snapshot())
        if self.path == '/api/conversation' or self.path.startswith('/api/conversation?'):
            from urllib.parse import parse_qs, urlsplit
            names = parse_qs(urlsplit(self.path).query).get('name', [])
            if len(names) != 1:
                return self.send(400, {'error': 'Informe uma conexão para ver a conversa.'})
            panel = self.server.panel
            try:
                safe_name(names[0])
            except (ValueError, TypeError):
                return self.send(400, {'error': 'Nome de conexão inválido.'})
            if names[0] not in panel.store.names():
                return self.send(404, {'error': 'Conexão não encontrada. Atualize o painel.'})
            return self.send(200, panel.transcript.snapshot(names[0]))
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
            elif self.path == '/api/chat/delete':
                panel = self.server.panel
                with panel.lock:
                    if panel.closed or panel.phase in ('running','waiting','updating') or (panel.api_service and panel.api_service.server):
                        raise PanelInputError('Termine a operação e desative a API antes de excluir a conexão.')
                    try:
                        panel.store.delete(payload.get('name'))
                    except (ValueError, TypeError) as error:
                        raise PanelInputError(str(error)) from None
                    # A conversa exibida pertence ao cadastro removido.
                    try:
                        panel.transcript.clear(payload.get('name'))
                    except (ValueError, TypeError):
                        pass
            elif self.path == '/api/conversation/clear':
                panel = self.server.panel
                with panel.lock:
                    if panel.closed or panel.phase in ('running','waiting','updating') or (panel.api_service and panel.api_service.busy()):
                        raise PanelInputError('Termine a operação antes de limpar a conversa do painel.')
                    try:
                        panel.transcript.clear(payload.get('name'))
                    except (ValueError, TypeError) as error:
                        raise PanelInputError(str(error)) from None
            elif self.path == '/api/profile':
                from .profiles import open_profile
                panel=self.server.panel
                with panel.lock:
                    if panel.closed or panel.phase in ('running','waiting','updating') or (panel.api_service and (panel.api_service.busy() or panel.api_service.server)):
                        raise PanelInputError('Termine a operação e desative a API antes de abrir outra aba do perfil.')
                    destination=payload.get('destination')
                    if destination=='permission':
                        target='chrome://inspect/#remote-debugging'
                    elif destination=='chat':
                        provider=payload.get('provider')
                        if provider not in (*PROVIDERS,'custom'):
                            raise PanelInputError('Escolha o chat que deseja abrir.')
                        target=PROVIDERS.get(provider) or payload.get('url')
                    else:
                        raise PanelInputError('Ação de perfil inválida.')
                    try:
                        open_profile(payload.get('profile'),target)
                    except ValueError as error:
                        raise PanelInputError(str(error)) from None
            elif self.path == '/api/reply':
                self.server.panel.reply(payload.get('id'), payload.get('value'))
            elif self.path == '/api/service':
                if self.server.panel.api_service is None:
                    raise PanelInputError('Abra o aplicativo pelo menu para gerenciar a API.')
                self.server.panel.api_service.configure(payload)
            elif self.path == '/api/updates':
                updater = self.server.panel.updater
                if updater is None or type(payload.get('enabled')) is not bool:
                    raise ValueError()
                updater.store.write(enabled=payload['enabled'])
                updater.wake.set()
            elif self.path == '/api/cancel':
                self.server.panel.cancel()
            else:
                return self.send(404, {'error': 'Ação não encontrada.'})
            self.send(200, {'ok': True})
        except PanelInputError as error:
            self.send(400, {'error': str(error)})
        except (ValueError, TypeError, OSError):
            self.send(400, {'error': 'Não foi possível iniciar. Confira os dados ou aguarde a operação atual terminar.'})


def main(argv=None):
    parser = argparse.ArgumentParser(description='Janela local do BrowserAPI para Ubuntu')
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--config-dir', default=str(DEFAULT_CONFIG_DIR))
    args = parser.parse_args(argv)
    activate_private_runtime(DATA_DIR)
    panel = Panel(ConfigStore(args.config_dir),DATA_DIR)
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
    restarting = threading.Event()
    updater = None
    try:
        ConfigStore.write_json(instance, {'url': server.url, 'token': server.token})
        if os.environ.get('BROWSERAPI_SUPERVISED') == '1':
            from .updates import Updater, UpdateStore
            from .llm_api import APIService
            panel.api_service=APIService(panel)
            store = UpdateStore(DATA_DIR)
            def restart_when_idle():
                with panel.lock:
                    if panel.phase in ('running','waiting','updating') or (panel.api_service and panel.api_service.busy()):
                        return False
                    ConfigStore.write_json(DATA_DIR/'relaunch.json',{'port':server.server_port,'token':server.token})
                    panel.phase = 'updating'
                    restarting.set()
                    threading.Thread(target=server.shutdown,daemon=True).start()
                    return True
            updater = Updater(store,APP_VERSION,restart_when_idle)
            panel.updater = updater
            updater.start()
            ConfigStore.write_json(DATA_DIR/'started.json',{'boot':os.environ.get('BROWSERAPI_BOOT_ID')})
        if not args.no_open and os.environ.get('BROWSERAPI_NO_OPEN') != '1':
            webbrowser.open(server.entry_url)
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        if updater:
            updater.close()
        if panel.api_service:
            panel.api_service.close()
        panel.close()
        server.server_close()
        instance.unlink(missing_ok=True)
        lock.release()
    return 75 if restarting.is_set() else 0


if __name__ == '__main__':
    raise SystemExit(main())
