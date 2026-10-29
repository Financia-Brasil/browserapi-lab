"""API loopback opt-in; jobs no worker do painel, sem segundo browser/driver.

Subconjunto textual OpenAI: modelos são aliases locais, usage desconhecido,
SSE é bufferizado. Histórico persistente apenas com opt-in explícito.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
import errno
import hashlib
import http.client
import json
import math
import re
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import ConfigStore, safe_name, origin
from .context import plan, ContextError
from . import conversation as windows
from . import tool_calls as tools_mod
from .chat import ChatResult, browser_config, config_fingerprint, exchange
from .browser import BrowserSession
from .setup import status
from .history import History


def diagnose_endpoint(text, port=8765):
    """Explica o erro de quem colou um endereço errado, em uma frase acionável.

    Motivo (relato do uso real): três erros diferentes com a mesma cara — cURL 7
    por ``127.0.0`` incompleto, ``Not found`` por faltar ``/v1/chat/completions``
    e o endereço base ``/v1`` usado como se fosse o de chat. A pessoa não tem
    como adivinhar qual é qual; a frase diz o que fazer.

    Só analisa o texto: não abre porta, não usa a chave e não envia nada.
    """
    raw = str(text or '').strip().strip('"').strip("'")
    if not raw:
        return {'ok': False, 'message': 'Cole o endereço que o seu agente está usando para eu conferir.',
                'normalized': ''}
    if '://' not in raw:
        raw = 'http://' + raw
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(raw)
    except ValueError:
        return {'ok': False, 'message': 'Isso não parece um endereço. Exemplo: '
                f'http://127.0.0.1:{port}/v1/chat/completions', 'normalized': raw}
    host = (parts.hostname or '').lower()
    path = parts.path or ''
    # Host truncado: o caso "Failed to connect to 127.0.0" do relato.
    if re.fullmatch(r'127(:|\.0){1,3}', host) or host in ('127', '127.0', '127.0.0'):
        return {'ok': False, 'normalized': raw, 'message':
                'O IP está incompleto. Use 127.0.0.1 (com o 1 no final) — '
                '"Failed to connect to 127.0.0" é exatamente isso.'}
    if host not in ('127.0.0.1', 'localhost', '::1'):
        return {'ok': False, 'normalized': raw, 'message':
                f'A API só atende este computador. Use 127.0.0.1, não {host or "um nome externo"}.'}
    try:
        given_port = parts.port
    except ValueError:
        return {'ok': False, 'normalized': raw, 'message':
                f'A porta em {raw} não é um número válido. Use :{port}.'}
    if given_port is None:
        return {'ok': False, 'normalized': raw, 'message':
                f'Falta a porta. Use http://127.0.0.1:{port}/v1/chat/completions.'}
    if given_port != int(port):
        return {'ok': False, 'normalized': raw, 'message':
                f'O serviço escuta na porta {port}, não em {given_port}. '
                f'Use http://127.0.0.1:{port}/v1/chat/completions.'}
    route = path.rstrip('/') or ''
    if route in ('', '/v1'):
        return {'ok': False, 'normalized': raw, 'message':
                'Falta a rota de conversa. Sem ela a resposta é "Not found" (404): '
                f'use http://127.0.0.1:{port}/v1/chat/completions ou, no Claude Code, '
                f'ANTHROPIC_BASE_URL=http://127.0.0.1:{port} (sem /v1).'}
    if route == '/v1/messages':
        return {'ok': True, 'normalized': raw, 'message':
                'Endereço do Claude Code correto. Ele chama /v1/messages sozinho a partir da base '
                f'http://127.0.0.1:{port}. Use ANTHROPIC_BASE_URL sem /v1.'}
    if route == '/v1/models':
        return {'ok': True, 'normalized': raw, 'message':
                'Este endereço lista os modelos. Para conversar, troque /v1/models por /v1/chat/completions.'}
    if route == '/v1/chat/completions':
        return {'ok': True, 'normalized': raw, 'message':
                'Endereço completo e correto. Use POST com Authorization: Bearer <chave local>.'}
    return {'ok': False, 'normalized': raw, 'message':
            f'A rota {route} não existe nesta API; por isso vem "Not found". '
            f'Use http://127.0.0.1:{port}/v1/chat/completions.'}


def endpoint_example(port=8765, model='meu-gemini'):
    """Exemplo copiável sem a chave em texto claro (print/tela compartilhada).

    A chave fica numa variável de ambiente: quem copia o exemplo não cola a
    chave em histórico de shell nem em captura de tela.
    """
    base = f'http://127.0.0.1:{port}'
    return ('export BROWSERAPI_KEY="<cole aqui a chave local>"\n'
            f'curl {base}/v1/chat/completions \\\n'
            '  -H "Authorization: Bearer $BROWSERAPI_KEY" \\\n'
            '  -H "Content-Type: application/json" \\\n'
            f'  -d \'{{"model":"{model}","messages":[{{"role":"user","content":"Ola"}}]}}\'')

def agent_env_example(port=8765, model='meu-gemini'):
    """Variáveis de ambiente para uma CLI que fala a API Anthropic.

    ``ANTHROPIC_BASE_URL`` é a base **sem** ``/v1``: o SDK acrescenta
    ``/v1/messages``. A chave vai em ``ANTHROPIC_AUTH_TOKEN`` para não entrar em
    histórico de shell nem em captura de tela.
    """
    return ('export ANTHROPIC_BASE_URL="http://127.0.0.1:%d"\n'
            'export ANTHROPIC_AUTH_TOKEN="<cole aqui a chave local>"\n'
            'export ANTHROPIC_MODEL="%s"' % (port, model))


# APIError e os adaptadores de protocolo vivem em ``api_compat`` para não
# criar ciclo de importação; continuam disponíveis por ``llm_api``.
from .api_compat import APIError, body as reply_body, normalize as normalize_request
from .api_compat import prompt_messages, sse as reply_sse
from . import tool_calls


@dataclass
class Job:
    prompt: str
    names: list
    options: dict
    context: dict
    # Um turno pode virar vários envios (início em blocos) e uma resposta pode
    # precisar de continuação (saída em blocos). ``prompt`` continua sendo o
    # último envio, para quem já dependia dele.
    sends: list = field(default_factory=list)
    fallback_sends: list = field(default_factory=list)
    rotate: bool = False
    limits: object = field(default_factory=windows.Limits)
    tools: list = field(default_factory=list)
    plan_report: dict = field(default_factory=dict)
    characters: int = 0
    page_reused: bool = False
    page_url: str = ''
    conversation: str = ''
    conversation_shared: bool = False
    blocks: int = 0
    stop_reason: str = 'end_turn'
    continuation_reason: str = ''
    commit: object = None
    identifier: str = field(default_factory=lambda:'chatcmpl-'+secrets.token_hex(16))
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    config: object = None
    error: object = None
    attempts: list = field(default_factory=list)
    owner: object = None
    cache_key: str = ''
    completed_at: float = 0
    created_at: float = field(default_factory=time.time)
    observe: object = None
    scope: str = ''
    question: str = ''
    documents: list = field(default_factory=list)


class WarmBrowser:
    """Uma aba quente, um worker: prontidão, blocos, retomada e continuação.

    O defeito do relato (“abre o chat, manda antes de carregar e diz que não
    funciona, e nem tenta de novo”) está resolvido em três camadas: espera ativa
    de prontidão antes do primeiro envio, repetição interna das falhas que
    aconteceram **antes de digitar**, e código HTTP retentável quando nem assim
    deu (503), em vez de 409 — que faz o agente desistir.
    """

    READY_SECONDS = 25
    ATTEMPTS = 2          # além da primeira tentativa
    RELOAD_SECONDS = 15

    def __init__(self, store, factory=BrowserSession):
        self.store = store
        self.factory = factory
        self.session = self.page = self.key = None

    def close(self):
        try:
            if self.session:
                self.session.close()
        finally:
            self.session = self.page = self.key = None

    # -- prontidão ---------------------------------------------------------
    def wait_ready(self, page, config, cancelled, seconds=None):
        """Espera o campo aparecer e ficar editável; recarrega uma vez se sumir.

        SPA pinta o campo depois de `domcontentloaded`. Julgar antes disso era o
        que produzia “não funcionou” com a página ainda carregando.
        """
        deadline = time.monotonic() + (seconds or self.READY_SECONDS)
        reloaded = False
        while True:
            if cancelled and cancelled():
                raise EOFError('Operação interrompida')
            try:
                if page.is_closed():
                    return False, 'page_unavailable'
                locator = page.locator(config.composer)
                if (locator.count() == 1 and locator.is_visible() and locator.is_editable()
                        and not page.locator(config.root).count() == 0):
                    return True, ''
            except Exception:
                pass
            if time.monotonic() >= deadline:
                return False, 'composer_missing'
            if not reloaded and time.monotonic() >= deadline - self.READY_SECONDS + 8:
                reloaded = True
                try:
                    page.reload(wait_until='domcontentloaded', timeout=self.RELOAD_SECONDS * 1000)
                except Exception:
                    pass
            try:
                page.wait_for_timeout(200)
            except Exception:
                time.sleep(0.2)

    def _reload(self, page, config):
        try:
            page.reload(wait_until='domcontentloaded', timeout=self.RELOAD_SECONDS * 1000)
        except Exception:
            pass

    # -- envio com repetição segura ---------------------------------------
    def send_with_retry(self, job, config, text, cancelled):
        """Um envio; repete só o que falhou **antes** de digitar."""
        last = None
        for attempt in range(self.ATTEMPTS + 1):
            if cancelled and cancelled():
                raise EOFError('Operação interrompida')
            result = exchange(self.page, config, text, authorized=True, cancelled=cancelled)
            if result.status == 'success' or not windows.retryable_status(result.status, result.send_state):
                if attempt:
                    result.diagnostics = dict(result.diagnostics or {}) | {'retried': attempt}
                    job.attempts.append({'model': config.name, 'status': result.status,
                                         'send_state': result.send_state, 'retried': attempt})
                return result
            last = result
            if attempt == self.ATTEMPTS:
                break
            # Nada foi digitado: recarregar não duplica mensagem nenhuma.
            job.attempts.append({'model': config.name, 'status': result.status,
                                 'send_state': result.send_state,
                                 'retry': attempt + 1, 'reason': 'pré-envio'})
            self._reload(self.page, config)
            ready, _ = self.wait_ready(self.page, config, cancelled)
            if not ready:
                continue
        return last

    def run_sends(self, job, config, cancelled):
        """Executa todos os envios do turno e as continuações da saída."""
        sends = list(job.sends) or [job.prompt]
        # O delta só vale para a MESMA conversa. Se a aba foi reaberta (o worker
        # recriou a página) ou o endereço mudou, o chat pode estar vazio e o
        # envio precisa ser autossuficiente. Julgar por "a página parece vazia"
        # era pior: conversa com carregamento preguiçoso parece vazia e o
        # contexto seria enviado duas vezes.
        moved = job.conversation and job.page_url and job.conversation != job.page_url
        if job.plan_report.get('mode') == 'delta' and job.fallback_sends and (
                not job.page_reused or moved):
            sends = list(job.fallback_sends)
            job.conversation_shared = True
            job.plan_report['fallback'] = 'page_reopened' if not job.page_reused else 'url_changed'
        result = None
        for index, text in enumerate(sends):
            result = self.send_with_retry(job, config, text, cancelled)
            if result.status != 'success':
                return result, index
            job.conversation = getattr(self.page, 'url', '') or ''
        # Saída em blocos: resposta que parece cortada ganha continuação.
        blocks = [result.answer or '']
        job.blocks = 1
        while True:
            merged = windows.merge_blocks(blocks)
            parsed = tools_mod.parse(merged, job.tools)
            more, reason = windows.needs_continuation(merged, job.blocks, job.limits,
                                                      incomplete=parsed.incomplete,
                                                      last=blocks[-1])
            job.continuation_reason = reason
            if not more:
                break
            cont = self.send_with_retry(job, config, windows.CONTINUATION_PROMPT, cancelled)
            if cont.status != 'success':
                break
            blocks.append(cont.answer or '')
            job.blocks += 1
        job.stop_reason = ('max_tokens' if job.continuation_reason in
                           ('block_limit', 'max_blocks', 'open_code_fence', 'incomplete_tool_call')
                           else 'end_turn')
        result.answer = windows.merge_blocks(blocks)
        result.timings = dict(result.timings or {}) | {'output_blocks': job.blocks}
        return result, len(sends) - 1

    # -- abertura de página ------------------------------------------------
    def open_page(self, config, headless, light, cancelled):
        self.close()
        if cancelled():
            raise EOFError()
        self.session = self.factory(browser_config(config, self.store.root, headless=headless))
        opened = time.perf_counter()
        self.session.start()
        browser_ms = (time.perf_counter() - opened) * 1000
        opened = time.perf_counter()
        if light:
            self.session.context.route('**/*', lambda route: route.abort()
                                       if route.request.resource_type in ('image', 'media', 'font')
                                       else route.continue_())
        target = origin(config.url)
        if config.session_mode == 'existing_chrome':
            # O Playwright agrupa abas de TODOS os perfis neste contexto.
            # Só a sessão verificada pode escolher uma aba do perfil confirmado.
            self.page = self.session.page(config.url)
        else:
            matches = [p for p in self.session.context.pages
                       if p.url.startswith(('http:', 'https:')) and origin(p.url) == target]
            if len(matches) > 1:
                raise APIError('Deixe somente uma aba do chat aberta', 'ambiguous_tabs', 409)
            self.page = matches[0] if matches else self.session.page(config.url)
        self.page.wait_for_load_state('domcontentloaded',
                                      timeout=config.timeout_ms)
        return browser_ms, (time.perf_counter() - opened) * 1000

    def rotate(self, config, cancelled):
        """Conversa nova para retomar contexto: navega ao endereço do chat."""
        if not self.page or self.page.is_closed():
            return False
        try:
            self.page.goto(config.url, wait_until='domcontentloaded',
                           timeout=config.timeout_ms)
            ready, _ = self.wait_ready(self.page, config, cancelled, seconds=10)
            return ready
        except Exception:
            return False

    def run(self, job, cancelled):
        visited = set()
        for name in job.names:
            config = self.store.load(name)
            target = origin(config.url)
            if target in visited:
                continue  # Não trocar contas do mesmo provedor para contornar quota.
            visited.add(target)
            if job.observe:
                job.observe(name)
            headless = job.options['headless']
            light = job.options['lightweight']
            if config.session_mode == 'existing_chrome' and (headless or light):
                raise APIError('Não alteramos modo/recursos do navegador pessoal',
                               'personal_browser_policy', 409)
            key = (config_fingerprint(config), headless, light)
            reused = self.key == key and self.page is not None and not self.page.is_closed()
            browser_ms = page_ms = 0.0
            if not reused:
                try:
                    browser_ms, page_ms = self.open_page(config, headless, light, cancelled)
                except (EOFError, KeyboardInterrupt):
                    self.close()
                    raise
                except APIError:
                    self.close()
                    raise
                except Exception:
                    self.close()
                    job.result = ChatResult('browser_unavailable')
                    job.config = config
                    job.attempts.append({'model': name, 'status': 'browser_unavailable',
                                         'send_state': 'not_sent', 'browser_reused': False})
                    if job.options.get('fallback'):
                        continue
                    return
                self.key = key
            if job.rotate:
                job.rotate = False
                job.conversation_shared = not self.rotate(config, cancelled)
            ready, problem = self.wait_ready(self.page, config, cancelled)
            if not ready:
                result = ChatResult(problem, stage='preflight')
                result.timings = {'browser_start_ms': round(browser_ms, 3),
                                  'page_open_ms': round(page_ms, 3)}
                job.result, job.config = result, config
                job.attempts.append({'model': name, 'status': problem,
                                     'send_state': 'not_sent', 'browser_reused': reused,
                                     'wait_ready': 'timeout'})
                if not job.options.get('fallback'):
                    return
                continue
            job.page_reused = reused
            job.page_url = getattr(self.page, 'url', '') or ''
            result, _ = self.run_sends(job, config, cancelled)
            result.timings.update(browser_start_ms=round(browser_ms, 3),
                                  page_open_ms=round(page_ms, 3))
            job.result, job.config = result, config
            job.attempts.append({'model': name, 'status': result.status,
                                 'send_state': result.send_state, 'browser_reused': reused})
            if result.status == 'success':
                return
            # Somente antes de qualquer ativação; nunca timeout/aceito/ambíguo.
            if result.send_state != 'not_sent' or result.status not in (
                    'not_configured', 'wrong_origin', 'composer_missing', 'draft_present',
                    'send_missing', 'send_is_microphone', 'browser_unavailable',
                    'page_unavailable', 'rate_limit'):
                return
            if not job.options.get('fallback'):
                return


class APIService:
    def __init__(self,panel,port=8765):
        self.panel,self.port=panel,port
        self.history=History(panel.data_dir)
        self.lock=threading.RLock()
        self.path=Path(panel.data_dir)/'api-policy.json'
        try:
            state=json.loads(self.path.read_text())
            if not isinstance(state,dict) or not isinstance(state.get('key'),str) or len(state['key'])<32:
                raise ValueError()
        except (OSError,ValueError,TypeError):
            state={'enabled':False,'key':secrets.token_urlsafe(32)}
        self.state=state
        self.ledger_path=Path(panel.data_dir)/'api-idempotency.json'
        self.ledger_error=False
        try:
            self.ledger=json.loads(self.ledger_path.read_text())
            if not isinstance(self.ledger,dict) or len(self.ledger)>128:
                raise ValueError()
            for k,v in self.ledger.items():
                if not isinstance(k,str) or not re.fullmatch('[0-9a-f]{64}',k) or not isinstance(v,dict) or set(v)!={'digest','at','done'} or not isinstance(v['digest'],str) or not re.fullmatch('[0-9a-f]{64}',v['digest']) or type(v['at']) not in (int,float) or not math.isfinite(v['at']) or v['at']<0 or type(v['done']) is not bool:
                    raise ValueError()
        except FileNotFoundError:
            self.ledger={}
        except (OSError,ValueError,TypeError):
            self.ledger={}
            self.ledger_error=True
            self.state['enabled']=False
        self.server=self.thread=None
        self.active=0
        # O que a API acredita já ter entregue a cada conversa do site. Vive só
        # em memória: reiniciar o programa reinicia a janela (e a retomada).
        self.delivered={}
        self.cache=OrderedDict()
        self.notice='Desativada. Autorize explicitamente antes de usar agentes.'
        if self.ledger_error:
            self.notice='Registro de idempotência inválido; API bloqueada para evitar repetição. Revogue a chave pelo painel.'
        if self.state.get('enabled') is True:
            try:
                self.configure(dict(state))
            except Exception:
                self.state['enabled']=False
                self.notice='Não foi possível reabrir a API. Confira o chat e a porta.'

    def snapshot(self):
        with self.lock:
            return {'available':True,'enabled':self.server is not None,'running':self.server is not None,
                    'port':self.server.server_port if self.server else self.port,'key':self.state['key'],
                    'url':f'http://127.0.0.1:{self.server.server_port if self.server else self.port}/v1',
                    'chat_url':f'http://127.0.0.1:{self.server.server_port if self.server else self.port}/v1/chat/completions',
                    'models_url':f'http://127.0.0.1:{self.server.server_port if self.server else self.port}/v1/models',
                    'example':endpoint_example(self.server.server_port if self.server else self.port,
                                               (self.state.get('names') or ['meu-gemini'])[0]),
                    'messages_url':f'http://127.0.0.1:{self.server.server_port if self.server else self.port}/v1/messages',
                    'agent_example':agent_env_example(self.server.server_port if self.server else self.port,
                                                      (self.state.get('names') or ['meu-gemini'])[0]),
                    'names':self.state.get('names',[]),'headless':self.state.get('headless',False),
                    'lightweight':self.state.get('lightweight',False),'retrieval':self.state.get('retrieval',False),
                    'fallback':self.state.get('fallback',False),'remember':self.state.get('remember',False),'personal_consent':self.state.get('personal_consent',False),'message':self.notice,
                    'limits':windows.Limits.from_state(self.state).as_dict(),
                    'context':{model:{'characters':entry.characters,'turns':entry.turns,
                                      'conversation':entry.conversation}
                               for model,entry in self.delivered.items()}}

    def configure(self,value):
        if type(value.get('enabled')) is not bool:
            raise APIError('Escolha ativar ou desativar')
        if not value['enabled']:
            # Mesmo lock-order do worker: painel → serviço. Não deixar uma nova
            # submissão entrar entre checar ociosidade e apagar/revogar.
            with self.panel.lock,self.lock:
                if (value.get('clear_history') or value.get('rotate')) and (
                        self.busy() or self.panel.phase in ('running','waiting','updating')):
                    raise APIError('Aguarde a tarefa antes de apagar/revogar','busy',409)
                if value.get('clear_history'):
                    self.history.clear()
                if value.get('rotate'):
                    self.state['key']=secrets.token_urlsafe(32)
                    self.ledger={}
                    ConfigStore.write_json(self.ledger_path,self.ledger)
                    self.ledger_error=False
                self.state['enabled']=False
                self.cache.clear()
                self.delivered.clear()
                ConfigStore.write_json(self.path,self.state)
            self.close()
            self.panel.tasks.put(('api_close',None))
            return
        if self.ledger_error:
            raise APIError('Revogue a chave antes de reabrir a API','idempotency_unavailable',409)
        names=value.get('names')
        if not isinstance(names,list) or not 1<=len(names)<=8 or len(set(names))!=len(names):
            raise APIError('Escolha de 1 a 8 chats distintos')
        for key in ('headless','lightweight','retrieval','fallback','remember'):
            if type(value.get(key,False)) is not bool:
                raise APIError('Opção inválida')
        try:
            limits=windows.Limits.from_state(value)
        except ValueError as problem:
            raise APIError(str(problem)) from None
        if value.get('remember') and not value.get('retrieval'):
            raise APIError('Histórico exige recuperação local habilitada')
        for name in names:
            safe_name(name)
            config=self.panel.store.load(name)
            if not config.ready or not status(self.panel.store,name).get('compatible_in_this_run'):
                raise APIError('Teste cada chat antes de autorizar a API','chat_not_validated',409)
            if config.session_mode=='existing_chrome':
                if value.get('personal_consent') is not True:
                    raise APIError('Confirme acesso amplo ao Chrome pessoal','consent_required',409)
                if value.get('headless') or value.get('lightweight'):
                    raise APIError('Modo leve/headless só no perfil dedicado')
        with self.panel.lock:
            if self.panel.phase in ('running','waiting','updating'):
                raise APIError('Aguarde terminar a tarefa atual','busy',409)
            with self.lock:
                if self.server or self.active:
                    raise APIError('Desative antes de mudar a política','busy',409)
                try:
                    server=APIServer(self,self.port)
                except OSError as problem:
                    # Antes, uma porta ocupada virava "não foi possível
                    # iniciar" sem dizer nada: a pessoa autorizava e o curl
                    # continuava recusando a conexão.
                    if getattr(problem,'errno',None)==errno.EADDRINUSE:
                        raise APIError(f'A porta {self.port} já está em uso por outro programa. '
                                       'Feche-o (ou reinicie o computador) e autorize de novo. '
                                       'Nenhuma porta foi aberta pela API.','port_busy',409) from problem
                    raise APIError(f'Não foi possível abrir a porta {self.port} para a API '
                                   f'({type(problem).__name__}). Nada foi ativado.','port_unavailable',409) from problem
                policy={key:value.get(key,False) for key in ('headless','lightweight','retrieval','fallback','personal_consent','remember')}
                self.state.update(policy,names=list(names),enabled=True)
                # Tetos de janela: ficam gravados com a política, não em cada envio.
                self.state.update(limits.as_dict())
                try:
                    ConfigStore.write_json(self.path,self.state)
                except BaseException:
                    server.server_close()
                    self.state['enabled']=False
                    raise
                self.cache.clear()
                self.server=server
                self.thread=threading.Thread(target=server.serve_forever,daemon=True)
                self.thread.start()
                self.notice='Ativa: a chave autoriza envios sem perguntar Sim a cada chamada. Login/modelo continuam manuais.'
                # Autorizar sem conferir deixava a pessoa com a porta fechada e
                # nenhuma pista. Aqui a API se testa pelo mesmo caminho do agente.
                check=self.probe()
                if not check['ok']:
                    self.close()
                    self.state['enabled']=False
                    ConfigStore.write_json(self.path,self.state)
                    raise APIError('A API não respondeu em 127.0.0.1:%d. %s Nada ficou ativo.'
                                   % (self.port,check['message']),'port_unreachable',409)

    def probe(self,timeout=3.0):
        """Confere a porta como um agente faria: loopback + chave.

        Não abre navegador, não envia mensagem e não troca o modelo: é só o
        caminho de rede até ``/v1/models``.
        """
        with self.lock:
            server=self.server
            key=self.state['key']
            names=list(self.state.get('names',[]))
        if server is None:
            return {'ok':False,'port':None,'message':'API desativada: nada está escutando. '
                    'Clique em “Autorizar e iniciar API” e mantenha esta janela aberta.'}
        port=server.server_port
        connection=None
        try:
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=timeout)
            connection.request('GET','/v1/models',headers={'Authorization':'Bearer '+key})
            response=connection.getresponse()
            raw=response.read()
            if response.status!=200:
                return {'ok':False,'port':port,'status':response.status,
                        'message':f'A porta {port} respondeu HTTP {response.status}. '
                                  'Confira a chave exibida no painel e tente de novo.'}
            data=json.loads(raw.decode() or '{}')
            models=[item.get('id') for item in data.get('data',[]) if isinstance(item,dict)]
            return {'ok':True,'port':port,'models':models,'status':200,
                    'message':f'Respondendo em 127.0.0.1:{port}/v1 · {len(models)-1 if models else len(names)} chat(s) autorizado(s).'}
        except (OSError,ValueError) as problem:
            return {'ok':False,'port':port,
                    'message':f'A porta {port} está aberta no programa, mas não respondeu ({type(problem).__name__}). '
                              'A API só existe enquanto esta janela estiver aberta.'}
        finally:
            if connection is not None:
                try: connection.close()
                except Exception: pass

    def busy(self):
        with self.lock:
            return self.active>0

    def close(self):
        with self.lock:
            server,self.server=self.server,None
            self.notice='API desativada. Requisições já aceitas não são desfeitas.'
        if server:
            server.shutdown()
            server.server_close()

    def complete(self,job):
        with self.lock:
            job.completed_at=time.time()
            if job.scope and job.result and job.result.status=='success' and not job.error:
                try:
                    self.history.append(job.scope,job.question,job.result.answer,job.documents)
                    job.context['history_saved']=True
                except Exception:
                    job.context['history_saved']=False
            job.question=''
            job.documents=[]
            entry=self.ledger.get(job.cache_key)
            if entry:
                safe=bool(job.result and (job.result.status=='success' or job.result.send_state=='not_sent'))
                entry.update(at=job.completed_at,done=safe)
                try:
                    ConfigStore.write_json(self.ledger_path,self.ledger)
                except OSError:
                    # Registro pendente em disco continua impedindo replay.
                    pass

    def submit(self,payload,key):
        allowed={'model','messages','stream','documents','conversation_id','tools','tool_choice',
                 'ignored','kind'}
        if not isinstance(payload,dict) or set(payload)-allowed:
            raise APIError('Parâmetro não suportado: o corpo precisa ser normalizado antes do envio')
        if type(payload.get('stream',False)) is not bool:
            raise APIError('stream deve ser booleano')
        if not isinstance(key,str) or len(key)>128 or any(ord(c)<33 or ord(c)>126 for c in key):
            raise APIError('Idempotency-Key inválida')
        automatic=not bool(key)
        intent={k:v for k,v in payload.items() if k!='stream'}
        digest=hashlib.sha256(json.dumps(intent,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        key=hashlib.sha256((self.state['key']+'\0'+('client:'+key if key else 'body:'+digest)).encode()).hexdigest()
        with self.lock:
            if not self.state.get('enabled') or not self.server:
                raise APIError('API desativada','disabled',503)
            if key in self.cache and automatic:
                _,old=self.cache[key]
                entry=self.ledger.get(key,{})
                if old.done.is_set() and entry.get('done') and time.time()-old.completed_at>60:
                    self.cache.pop(key,None)
            if key in self.cache:
                old_digest,job=self.cache[key]
                if digest!=old_digest:
                    raise APIError('Chave de idempotência já usada com outro corpo','idempotency_conflict',409)
                return job
            previous=self.ledger.get(key)
            if previous and (not automatic or not previous['done'] or time.time()-previous['at']<=60):
                if previous['digest']!=digest:
                    raise APIError('Identidade anterior tem outro corpo','idempotency_conflict',409)
                raise APIError('Pedido já registrado; resultado não está nesta memória. Confira a página antes de usar outra chave','previous_request',409)
            model=payload.get('model')
            names=list(self.state['names'])
            if model!='auto' and model not in names:
                raise APIError('Modelo não autorizado','model_not_found',404)
            if model!='auto':
                names=[model]
            messages=payload.get('messages')
            documents=payload.get('documents')
            scope=''
            if documents is not None and (not isinstance(documents,list) or len(documents)>100):
                raise APIError('Documentos devem ser uma lista de textos')
            if self.state.get('remember'):
                scope=self.history.scope(payload.get('conversation_id'))
                prior=self.history.read(scope)
                recent_indices=[]
                if isinstance(messages,list) and len(messages)==1:
                    recent_indices=[i for i,(r,_) in enumerate(prior) if r!='document'][-4:]
                    messages=[{'role':prior[i][0],'content':prior[i][1]} for i in recent_indices]+messages
                cold='\n\n'.join(f'[histórico registro {i+1} ({r})]\n{t}' for i,(r,t) in enumerate(prior) if i not in recent_indices)
                documents=([cold] if cold else [])+(documents or [])
            # CLI de agente manda prompt grande (instruções + esquemas de
            # ferramentas). Recusar por orçamento fixo quebrava o uso; o teto
            # agora acompanha o pedido e continua explícito no relatório.
            limits=windows.Limits.from_state(self.state)
            tools=payload.get('tools') or []
            choice=payload.get('tool_choice')
            protocol=reminder=''
            if tools and choice not in ('none',{'type':'none'}):
                protocol=tools_mod.protocol_prompt(tools,choice)
                reminder=tools_mod.protocol_reminder(tools,choice)
            # Dois caminhos, de propósito:
            # * documentos/recuperação local -> planejador lexical, pedido
            #   autossuficiente (comportamento anterior preservado);
            # * agente (histórico completo no cliente) -> janelas: início em
            #   blocos, delta por turno, retomada quando a conversa enche.
            stateless={
                'input_characters':sum(len(item['content']) for item in messages)+sum(map(len,documents or [])),
                'budget_characters':None,'token_count':None,'retrieved_chunks':0,
                'reduced':False,'history_persisted':False}
            if documents or self.state.get('retrieval'):
                room=limits.max_parts*(limits.message_chars-300)
                budget=max(24_000,min(160_000,room,
                    sum(len(item['content']) for item in messages)+sum(map(len,documents or []))+4_000))
                text,stateless=plan(messages,documents,retrieve=self.state.get('retrieval',False),
                                    budget=budget)
                messages=[{'role':'user','content':text}]
            delivered=self.delivered.get(names[0]) if not (documents or self.state.get('retrieval')) else None
            total_chars=sum(len(item['content']) for item in messages)+len(protocol)
            try:
                turn=windows.plan_turn(messages,delivered=delivered,limits=limits,
                                       protocol=protocol,reminder=reminder,
                                       stateless=bool(documents or self.state.get('retrieval')))
            except windows.WindowError as problem:
                # Erro no vocabulário do cliente (context_length_exceeded /
                # prompt is too long), só depois de tentar os blocos.
                failure=APIError(str(problem),problem.code,problem.http)
                failure.payload=windows.dialect_error(payload.get('kind','openai-chat'),
                                                      total_chars,limits)
                raise failure from None
            except ValueError as problem:
                raise APIError(str(problem)) from None
            report=dict(stateless)|dict(turn.report)
            report.update(history_persisted=bool(scope),
                          history_limit_characters=self.history.limit if scope else None,
                          description=windows.describe(turn,limits))
            if tools:
                report['tools_emulated']=len(tools)
                report['tools_prompt_characters']=len(protocol)
            options={k:self.state.get(k,False) for k in ('headless','lightweight','retrieval','fallback')}
            job=Job(turn.sends[-1],names,options,report,owner=self,cache_key=key,scope=scope,
                    question=payload['messages'][-1]['content'] if scope else '',
                    documents=(payload.get('documents') or []) if scope else [],
                    sends=list(turn.sends),rotate=turn.rotate,limits=limits,tools=tools,
                    plan_report=dict(report)|{'mode':turn.mode,
                                              'tools_prompt_characters':len(protocol)},
                    characters=turn.characters)
            if turn.mode=='delta':
                # Se a página estiver vazia (recarregou, aba trocada), mandar só
                # o delta seria conversa sem começo: existe um plano de retomada.
                try:
                    job.fallback_sends=list(windows.plan_turn(
                        messages,delivered=None,limits=limits,protocol=protocol).sends)
                except windows.WindowError:
                    # O plano autossuficiente não cabe inteiro: a retomada
                    # compactada é o que cabe por construção.
                    job.fallback_sends=list(windows.plan_restore(
                        messages,limits=limits,protocol=protocol).sends)
            target=names[0]
            def commit(conversation_id='',shared=False,turn=turn,model=target):
                if getattr(job_holder,'committed',False):
                    return
                job_holder.committed=True
                with self.lock:
                    previous=self.delivered.get(model)
                    turns=(previous.turns if previous and turn.mode=='delta' else 0)+1
                    self.delivered[model]=windows.Delivered(
                        hashes=list(turn.hashes),characters=turn.characters,
                        conversation=conversation_id or (previous.conversation if previous else ''),
                        bootstrap=True,turns=turns)
            job_holder=job
            job.commit=commit
            self.ledger.pop(key,None)
            self.ledger[key]={'digest':digest,'at':time.time(),'done':False}
            while len(self.ledger)>128:
                self.ledger.pop(next(iter(self.ledger)))
            try:
                ConfigStore.write_json(self.ledger_path,self.ledger)
            except OSError:
                self.ledger.pop(key,None)
                raise APIError('Falha ao registrar pedido; nenhum envio foi iniciado','storage_unavailable',503)
            # Só um job em execução. Cache limitado a 16 respostas; sem prompts.
            if key:
                self.cache[key]=(digest,job)
                while len(self.cache)>16:
                    self.cache.popitem(last=False)
        try:
            self.panel.submit_api(job)
        except Exception:
            with self.lock:
                if key and self.cache.get(key,(None,None))[1] is job:
                    self.cache.pop(key,None)
                self.ledger.pop(key,None)
                ConfigStore.write_json(self.ledger_path,self.ledger)
                job.error=APIError('Uma tarefa já está ativa ou a API não está pronta','busy',409)
                job.prompt=''
                job.done.set()
            raise job.error
        return job


class APIServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,service,port):
        self.service=service
        super().__init__(('127.0.0.1',port),APIHandler)


class APIHandler(BaseHTTPRequestHandler):
    # Rotas e o dialeto que cada uma fala. Ter todas é o que permite uma CLI
    # (Claude Code fala Anthropic) apontar para cá sem adaptador.
    ROUTES={'/v1/chat/completions':'openai-chat','/v1/messages':'anthropic',
            '/v1/completions':'openai-completions','/v1/responses':'openai-responses'}

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self,*args):
        pass

    def send_json(self,status,body):
        raw=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        # Quem só vê cabeçalho (log de CLI) descobre aqui o que foi ignorado.
        if getattr(self,'_ignored',''):
            self.send_header('X-BrowserAPI-Ignored',self._ignored)
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_events(self,raw):
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Accel-Buffering','no')
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def supplied_key(self):
        """Aceita ``Authorization: Bearer`` e ``x-api-key`` (Anthropic SDK)."""
        bearer=(self.headers.get('Authorization','') or '').strip()
        if bearer.lower().startswith('bearer '):
            return bearer[7:].strip()
        return (self.headers.get('x-api-key','') or '').strip()

    def authorized(self):
        port=self.server.server_port
        supplied=self.supplied_key()
        expected=self.server.service.state['key']
        return (self.headers.get('Host') in (f'127.0.0.1:{port}',f'localhost:{port}')
                and self.headers.get('Origin',f'http://127.0.0.1:{port}')==f'http://127.0.0.1:{port}'
                and secrets.compare_digest(supplied.encode(),expected.encode()))

    def missing_key(self):
        return not self.supplied_key()

    def route(self):
        return self.path.split('?')[0].rstrip('/') or '/'

    def do_GET(self):
        if not self.authorized():
            if self.missing_key():
                return self.send_json(401,{'error':{'message':'Falta a chave: envie Authorization: Bearer <chave do painel> ou x-api-key','type':'authentication_error','code':'missing_api_key'}})
            return self.send_json(401,{'error':{'message':'Unauthorized','type':'authentication_error','code':'invalid_api_key'}})
        route=self.route()
        if route=='/':
            return self.send_json(404,{'error':{'message':'A API não tem página inicial. Use '
                                                '/v1/messages (Claude Code) ou /v1/chat/completions '
                                                '(OpenAI). Também há /v1/responses e /v1/models.',
                                                'code':'not_found','endpoints':sorted(self.ROUTES)}})
        if route=='/v1':
            return self.send_json(200,{'object':'browserapi.index','endpoints':sorted(self.ROUTES),
                                       'extra':['/v1/models','/v1/messages/count_tokens'],
                                       'note':'Chave em Authorization: Bearer ou x-api-key. Só loopback.'})
        if route=='/v1/models':
            names=self.server.service.state['names']
            return self.send_json(200,{'object':'list','data':[{'id':n,'object':'model','created':0,
                                                               'owned_by':'browserapi-local-alias'} for n in [*names,'auto']]})
        return self.send_json(404,{'error':{'message':'Not found','code':'not_found'}})

    def read_payload(self):
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=16_000_000:
            raise APIError('Corpo excede limite de 16 MB','request_too_large',413)
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':
            raise APIError('Use application/json','invalid_content_type',415)
        raw=self.rfile.read(length)
        if (self.headers.get('Content-Encoding') or '').lower()=='gzip':
            import gzip
            try:
                raw=gzip.decompress(raw)
            except OSError:
                raise APIError('Corpo gzip inválido','invalid_encoding',400) from None
        return json.loads(raw)

    def do_POST(self):
        service=self.server.service
        if not self.authorized():
            return self.send_json(401,{'error':{'message':'Unauthorized','type':'authentication_error','code':'invalid_api_key'}})
        route=self.route()
        style=self.ROUTES.get(route)
        if route=='/v1/messages/count_tokens':
            # A CLI usa isto para aprender o tamanho do contexto. Zero fazia o
            # medidor nunca encher; a estimativa é rotulada como estimativa.
            try:
                payload=self.read_payload()
                # Mede o que iria ao chat: texto das mensagens + system + o
                # bloco de ferramentas (o resto é sintaxe do protocolo).
                normalized=normalize_request('anthropic',payload)
                characters=sum(len(item['content']) for item in normalized['messages'])
                characters+=len(tools_mod.protocol_prompt(normalized['tools']))
            except Exception:
                characters=0
            limits=windows.Limits.from_state(service.state)
            return self.send_json(200,{'input_tokens':windows.estimate_tokens(characters),
                                       'browserapi':{
                'estimated':True,'characters':characters,
                'window_characters':limits.conversation_chars,
                'note':'Estimativa por caracteres (4:1); o site não informa tokens.'}})
        if route in ('/v1/embeddings','/v1/audio/transcriptions','/v1/images/generations'):
            return self.send_json(501,{'error':{'message':'A API local só faz conversa em texto; '
                                                          'este endpoint não é emulado.',
                                                'type':'not_supported','code':'not_supported'}})
        if style is None:
            return self.send_json(404,{'error':{'message':'Not found. Rotas: '+', '.join(sorted(self.ROUTES)),
                                                'code':'not_found'}})
        with service.lock:
            if service.active>=4:
                return self.send_json(429,{'error':{'message':'Capacidade local ocupada','code':'local_capacity'}})
            service.active+=1
        # A chamada termina quando o worker termina, não quando o socket é
        # escrito: sem isso, "apagar histórico/revogar" feito logo depois de uma
        # resposta podia ser recusado como "tarefa em andamento".
        released=[False]
        def release():
            if not released[0]:
                released[0]=True
                with service.lock:
                    service.active-=1
        try:
            payload=self.read_payload()
            request=normalize_request(style,payload)
            job=service.submit(request,self.headers.get('Idempotency-Key',''))
            if not job.done.wait(600):
                raise APIError('Prazo local excedido; envio pode ter sido aceito, não repita sem conferir','request_pending',504)
            if job.error:
                raise job.error
            if job.result is None:
                # Worker morreu sem resultado: antes isso derrubava a conexão
                # sem resposta nenhuma e a CLI só via "connection reset".
                raise APIError('A execução terminou sem resposta; confira o painel e o navegador',
                               'execution_failed',502)
            result=job.result
            if result.status!='success':
                code=windows.http_for_status(result.status,result.send_state)
                sent=result.send_state!='not_sent'
                message=('A página não estava pronta e nada foi digitado; pode repetir' if code==503
                         else 'A fonte não confirmou a resposta; confira o navegador antes de repetir')
                raise APIError(message,result.status,code)
            if callable(job.commit):
                job.commit(conversation_id=job.conversation,shared=job.conversation_shared)
            parsed=tool_calls.parse(result.answer or '',request['tools'])
            if request['stream']:
                raw=reply_sse(style,request,job,parsed)
                release()
                return self.send_events(raw)
            reply=reply_body(style,request,job,parsed)
            release()
            if request.get('ignored'):
                # Cabeçalho para quem não lê o corpo (logs de CLI, por exemplo).
                self._ignored=','.join(request['ignored'])
            return self.send_json(200,reply)
        except (ContextError,ValueError,TypeError,KeyError,RecursionError) as error:
            release()
            if not isinstance(error,APIError):
                error=APIError(str(error) if isinstance(error,ContextError) else 'Solicitação inválida')
            try:
                body=getattr(error,'payload',None)
                if body is None:
                    body={'error':{'message':str(error),'type':'invalid_request_error','code':error.code}}
                self.send_json(error.http,body)
            except OSError:
                pass
        except OSError:
            pass
        except Exception:
            # Nunca derrubar o socket sem resposta: uma CLI só mostra "erro de
            # rede" e não há como diagnosticar. Sem detalhes internos na saída.
            release()
            try:
                self.send_json(500,{'error':{'message':'Falha interna ao montar a resposta; '
                                                       'nada foi reenviado. Confira o painel.',
                                             'type':'api_error','code':'internal_error'}})
            except OSError:
                pass
        finally:
            release()
