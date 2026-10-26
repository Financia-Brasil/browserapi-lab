"""API loopback opt-in; jobs no worker do painel, sem segundo browser/driver.

Subconjunto textual OpenAI: modelos são aliases locais, usage desconhecido,
SSE é bufferizado. Histórico/documentos recuperados somente em memória.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
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
from .chat import ChatResult, browser_config, config_fingerprint, exchange
from .browser import BrowserSession
from .setup import status
from .history import History


class APIError(ValueError):
    def __init__(self,message,code='invalid_request',http=400):
        super().__init__(message)
        self.code,self.http=code,http


@dataclass
class Job:
    prompt: str
    names: list
    options: dict
    context: dict
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
    def __init__(self,store,factory=BrowserSession):
        self.store,self.factory=store,factory
        self.session=self.page=self.key=None

    def close(self):
        try:
            if self.session:
                self.session.close()
        finally:
            self.session=self.page=self.key=None

    def run(self,job,cancelled):
        visited=set()
        for name in job.names:
            config=self.store.load(name)
            target=origin(config.url)
            if target in visited:
                continue  # Não trocar contas do mesmo provedor para contornar quota.
            visited.add(target)
            if job.observe:
                job.observe(name)
            headless=job.options['headless']
            light=job.options['lightweight']
            if config.session_mode=='existing_chrome' and (headless or light):
                raise APIError('Não alteramos modo/recursos do navegador pessoal','personal_browser_policy',409)
            key=(config_fingerprint(config),headless,light)
            reused=self.key==key and self.page is not None and not self.page.is_closed()
            browser_ms=page_ms=0.0
            if not reused:
                self.close()
                if cancelled():
                    raise EOFError()
                try:
                    self.session=self.factory(browser_config(config,self.store.root,headless=headless))
                    opened=time.perf_counter()
                    self.session.start()
                    browser_ms=(time.perf_counter()-opened)*1000
                    opened=time.perf_counter()
                    if light:
                        self.session.context.route('**/*',lambda route:route.abort() if route.request.resource_type in ('image','media','font') else route.continue_())
                    matches=[p for p in self.session.context.pages if p.url.startswith(('http:','https:')) and origin(p.url)==target]
                    if len(matches)>1:
                        raise APIError('Deixe somente uma aba do chat aberta','ambiguous_tabs',409)
                    self.page=matches[0] if matches else self.session.page(config.url)
                    self.key=key
                    page_ms=(time.perf_counter()-opened)*1000
                except (EOFError,KeyboardInterrupt):
                    self.close()
                    raise
                except Exception:
                    self.close()
                    job.result=ChatResult('browser_unavailable')
                    job.config=config
                    job.attempts.append({'model':name,'status':'browser_unavailable','send_state':'not_sent','browser_reused':False})
                    if job.options.get('fallback'):
                        continue
                    return
            result=exchange(self.page,config,job.prompt,authorized=True,cancelled=cancelled)
            result.timings.update(browser_start_ms=round(browser_ms,3),page_open_ms=round(page_ms,3))
            job.result,job.config=result,config
            job.attempts.append({'model':name,'status':result.status,'send_state':result.send_state,'browser_reused':reused})
            if result.status=='success':
                return
            # Somente antes de qualquer ativação; nunca timeout/aceito/ambíguo.
            if result.send_state!='not_sent' or result.status not in (
                    'not_configured','wrong_origin','composer_missing','draft_present',
                    'send_missing','send_is_microphone','browser_unavailable','page_unavailable','rate_limit'):
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
            return {'available':True,'enabled':self.server is not None,'key':self.state['key'],
                    'url':f'http://127.0.0.1:{self.server.server_port if self.server else self.port}/v1',
                    'names':self.state.get('names',[]),'headless':self.state.get('headless',False),
                    'lightweight':self.state.get('lightweight',False),'retrieval':self.state.get('retrieval',False),
                    'fallback':self.state.get('fallback',False),'remember':self.state.get('remember',False),'personal_consent':self.state.get('personal_consent',False),'message':self.notice}

    def configure(self,value):
        if type(value.get('enabled')) is not bool:
            raise APIError('Escolha ativar ou desativar')
        if not value['enabled']:
            if value.get('clear_history'):
                with self.panel.lock:
                    if self.busy() or self.panel.phase in ('running','waiting','updating'):
                        raise APIError('Aguarde a tarefa antes de apagar histórico','busy',409)
                self.history.clear()
            if value.get('rotate'):
                with self.panel.lock:
                    if self.busy() or self.panel.phase in ('running','waiting','updating'):
                        raise APIError('Aguarde a tarefa antes de revogar a chave','busy',409)
                with self.lock:
                    self.state['key']=secrets.token_urlsafe(32)
                    self.ledger={}
                    ConfigStore.write_json(self.ledger_path,self.ledger)
                    self.ledger_error=False
            with self.lock:
                self.state['enabled']=False
                self.cache.clear()
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
                server=APIServer(self,self.port)
                policy={key:value.get(key,False) for key in ('headless','lightweight','retrieval','fallback','personal_consent','remember')}
                self.state.update(policy,names=list(names),enabled=True)
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
        allowed={'model','messages','stream','documents','conversation_id'}
        if not isinstance(payload,dict) or set(payload)-allowed:
            raise APIError('Parâmetro não suportado; tools/temperature/limites nativos não são simulados')
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
            if documents is not None and not isinstance(documents,list):
                raise APIError('Documentos devem ser uma lista de textos')
            if self.state.get('remember'):
                scope=self.history.scope(payload.get('conversation_id'))
                prior=self.history.read(scope)
                if isinstance(messages,list) and len(messages)==1:
                    messages=[{'role':r,'content':t} for r,t in prior if r!='document']+messages
                documents=([t for r,t in prior if r=='document'] if prior else [])+(documents if isinstance(documents,list) else [])
            text,report=plan(messages,documents,retrieve=self.state.get('retrieval',False))
            report.update(history_persisted=bool(scope),history_limit_characters=self.history.limit if scope else None)
            options={k:self.state.get(k,False) for k in ('headless','lightweight','retrieval','fallback')}
            job=Job(text,names,options,report,owner=self,cache_key=key,scope=scope,
                    question=payload['messages'][-1]['content'] if scope else '',
                    documents=(payload.get('documents') or []) if scope else [])
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
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        port=self.server.server_port
        supplied=self.headers.get('Authorization','')
        return (self.headers.get('Host') in (f'127.0.0.1:{port}',f'localhost:{port}')
                and self.headers.get('Origin',f'http://127.0.0.1:{port}')==f'http://127.0.0.1:{port}'
                and secrets.compare_digest(supplied.encode(),('Bearer '+self.server.service.state['key']).encode()))

    def do_GET(self):
        if not self.authorized():
            return self.send_json(401,{'error':{'message':'Unauthorized','type':'authentication_error','code':'invalid_api_key'}})
        if self.path!='/v1/models':
            return self.send_json(404,{'error':{'message':'Not found','code':'not_found'}})
        names=self.server.service.state['names']
        return self.send_json(200,{'object':'list','data':[{'id':n,'object':'model','created':0,'owned_by':'browserapi-local-alias'} for n in [*names,'auto']]})

    def do_POST(self):
        service=self.server.service
        if not self.authorized():
            return self.send_json(401,{'error':{'message':'Unauthorized','type':'authentication_error','code':'invalid_api_key'}})
        if self.path!='/v1/chat/completions':
            return self.send_json(404,{'error':{'message':'Not found','code':'not_found'}})
        with service.lock:
            if service.active>=4:
                return self.send_json(429,{'error':{'message':'Capacidade local ocupada','code':'local_capacity'}})
            service.active+=1
        try:
            self.connection.settimeout(15)
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16_000_000:
                raise APIError('Corpo excede limite de 16 MB','request_too_large',413)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                raise APIError('Use application/json','invalid_content_type',415)
            payload=json.loads(self.rfile.read(length))
            job=service.submit(payload,self.headers.get('Idempotency-Key',''))
            if not job.done.wait(600):
                raise APIError('Prazo local excedido; envio pode ter sido aceito, não repita sem conferir','request_pending',504)
            if job.error:
                raise job.error
            result=job.result
            if result.status!='success':
                code=504 if result.status=='timeout' else 429 if result.status=='rate_limit' else 409
                raise APIError('A fonte não confirmou a resposta; confira o navegador antes de repetir',result.status,code)
            body={'id':job.identifier,'object':'chat.completion','created':int(job.created_at),'model':job.config.name,
                  'choices':[{'index':0,'message':{'role':'assistant','content':result.answer},'finish_reason':'stop'}],
                  'usage':None,'browserapi':{'context':job.context,'attempts':job.attempts,'streaming':'buffered'}}
            if not payload.get('stream'):
                return self.send_json(200,body)
            chunk={'id':body['id'],'object':'chat.completion.chunk','created':body['created'],'model':body['model'],
                   'choices':[{'index':0,'delta':{'role':'assistant','content':result.answer},'finish_reason':None}]}
            end=dict(chunk,choices=[{'index':0,'delta':{},'finish_reason':'stop'}])
            raw=('data: '+json.dumps(chunk,ensure_ascii=False)+'\n\ndata: '+json.dumps(end)+'\n\ndata: [DONE]\n\n').encode()
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (ContextError,ValueError,TypeError,KeyError,RecursionError) as error:
            if not isinstance(error,APIError):
                error=APIError(str(error) if isinstance(error,ContextError) else 'Solicitação inválida')
            try:
                self.send_json(error.http,{'error':{'message':str(error),'type':'invalid_request_error','code':error.code}})
            except OSError:
                pass
        except OSError:
            pass
        finally:
            with service.lock:
                service.active-=1
