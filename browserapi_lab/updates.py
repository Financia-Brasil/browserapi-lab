"""Atualizações do editor fixo no GitHub; sem root, shell, cookies ou credenciais.

Confiança: HTTPS + controle do repositório/release pelo editor. SHA256 verifica
integridade, não é uma assinatura independente do editor. Somente ABI 1.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zipfile

from .config import ConfigStore

REPO = 'Financia-Brasil/browserapi-lab'
API = 'https://api.github.com/repos/' + REPO
ABI = 1
MAX_BUNDLE = 2_000_000
VERSION = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z')


def version(value):
    if not isinstance(value,str) or not VERSION.fullmatch(value):
        raise ValueError('Versão inválida')
    return tuple(map(int,value.split('.')))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('Redirecionamento não permitido')


def github(path):
    # Caminhos são construídos internamente; nunca aceitar URL de manifesto.
    if not path.startswith('/') or '..' in path or '\\' in path:
        raise ValueError('Caminho inválido')
    request = Request(API+path,headers={'Accept':'application/vnd.github+json','User-Agent':'BrowserAPI-Updater/1'})
    with build_opener(NoRedirect()).open(request,timeout=20) as response:
        raw = response.read(4_000_001)
    if len(raw)>4_000_000:
        raise ValueError('Resposta muito grande')
    return json.loads(raw)


def content(fetch,path,sha):
    data = fetch('/contents/'+path+'?ref='+sha)
    if data.get('encoding')!='base64':
        raise ValueError('Codificação inválida')
    return base64.b64decode(''.join(data['content'].split()),validate=True)


def candidate(fetch=github):
    release = fetch('/releases/latest')
    if release.get('draft') or release.get('prerelease'):
        raise ValueError('Release não estável')
    tag = release['tag_name']
    version(tag.removeprefix('v'))
    if tag != 'v'+tag.removeprefix('v'):
        raise ValueError('Tag inválida')
    ref = fetch('/git/ref/tags/'+tag)['object']
    for _ in range(4):
        if not re.fullmatch('[a-f0-9]{40}',ref['sha']):
            raise ValueError('Commit inválido')
        if ref['type']=='commit':
            break
        if ref['type']!='tag':
            raise ValueError('Referência inválida')
        ref = fetch('/git/tags/'+ref['sha'])['object']
    else:
        raise ValueError('Tag recursiva')
    sha = ref['sha']
    manifest = json.loads(content(fetch,'downloads/update.json',sha))
    if manifest.get('schema')!=1 or manifest.get('abi')!=ABI or manifest.get('version')!=tag[1:]:
        raise ValueError('Manifesto incompatível')
    version(manifest['version'])
    if manifest.get('playwright')!='1.64.1' or manifest.get('python_min')!=[3,11]:
        raise ValueError('Dependências incompatíveis; instalador necessário')
    if type(manifest.get('size')) is not int or not 0<manifest['size']<=MAX_BUNDLE:
        raise ValueError('Tamanho inválido')
    if not re.fullmatch('[a-f0-9]{64}',manifest.get('sha256','')):
        raise ValueError('Hash inválido')
    return manifest,sha


class UpdateStore:
    def __init__(self,data_dir):
        self.root = Path(data_dir)/'updates'
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path = self.root/'state.json'
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            try:
                value = json.loads(self.path.read_text())
                if not isinstance(value,dict) or type(value.get('enabled',True)) is not bool:
                    raise ValueError()
                for key in ('active','previous','pending'):
                    if value.get(key) is not None:
                        version(value[key])
                return value
            except FileNotFoundError:
                return {'enabled':True}
            except (OSError,ValueError,TypeError):
                return {'enabled':False,'notice':'Preferências de atualização inválidas; atualização automática desativada por segurança.'}

    def write(self,**values):
        with self.lock:
            state = self.read()
            state.update(values)
            ConfigStore.write_json(self.path,state)

    def directory(self,value):
        version(value)
        return self.root/value

    def stage(self,manifest,raw):
        target = self.directory(manifest['version'])
        if len(raw)!=manifest['size'] or hashlib.sha256(raw).hexdigest()!=manifest['sha256']:
            raise ValueError('Integridade inválida')
        with tempfile.TemporaryDirectory(prefix='.download-',dir=self.root) as tmp:
            stage = Path(tmp)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                infos = archive.infolist()
                if not 5<=len(infos)<=100 or sum(i.file_size for i in infos)>8_000_000:
                    raise ValueError('Arquivo inválido')
                seen = set()
                for item in infos:
                    name = item.filename
                    if name in seen or stat.S_ISLNK(item.external_attr >> 16) or item.is_dir():
                        raise ValueError('Entrada inválida')
                    seen.add(name)
                    if not re.fullmatch(r'browserapi_lab/(?:[a-z_]+\.py|assets/[a-z_]+\.(?:html|js|css))',name):
                        raise ValueError('Caminho de arquivo inválido')
                    body = archive.read(item)
                    if name.endswith('.py'):
                        compile(body,name,'exec')
                    file = stage/name
                    file.parent.mkdir(parents=True,exist_ok=True)
                    file.write_bytes(body)
            required = ['__init__.py','gui.py','bootstrap.py','updates.py','version.py','assets/panel.html','assets/panel.js','assets/panel.css','assets/picker.js','assets/chat_probe.js','assets/typing_guard.js','assets/voice_control.js','assets/fake_chat.html']
            for name in required:
                if not (stage/'browserapi_lab'/name).is_file():
                    raise ValueError('Arquivo obrigatório ausente')
            identity = "APP_VERSION = '"+manifest['version']+"'"
            if identity not in (stage/'browserapi_lab/version.py').read_text():
                raise ValueError('Versão divergente')
            for name in ('panel.html','panel.js'):
                if manifest['version'] not in (stage/'browserapi_lab/assets'/name).read_text():
                    raise ValueError('Interface divergente')
            if target.exists():
                # Recuperar queda entre rename e gravação do ponteiro, sem
                # sobrescrever arquivos de uma versão possivelmente em uso.
                for file in stage.rglob('*'):
                    if file.is_file():
                        existing = target/file.relative_to(stage)
                        if not existing.is_file() or existing.read_bytes()!=file.read_bytes():
                            raise ValueError('Versão já existe com conteúdo diferente')
            else:
                os.replace(stage,target)
            # TemporaryDirectory tolera a origem já movida.
        self.write(pending=manifest['version'])

    def activate(self):
        state = self.read()
        pending = state.get('pending')
        if pending and state.get('enabled',True):
            self.write(previous=state.get('active'),active=pending,pending=None,trial=pending)
        return self.read().get('active')

    def confirm(self):
        self.write(trial=None)

    def rollback(self):
        state = self.read()
        failed = state.get('trial')
        if failed:
            rejected = list(dict.fromkeys([*state.get('rejected',[]),failed]))[-20:]
            self.write(active=state.get('previous'),previous=None,trial=None,pending=None,rejected=rejected,
                       notice='A nova versão não iniciou. A versão anterior foi restaurada.')


class Updater:
    def __init__(self,store,current,on_ready,fetch=github,interval=21600):
        self.store,self.current,self.on_ready,self.fetch = store,current,on_ready,fetch
        self.interval = interval
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.RLock()
        self.state = {'managed':True,'status':'idle','message':'Atualizações automáticas do repositório oficial.'}
        self.thread = None

    def snapshot(self):
        with self.lock:
            return dict(self.state,enabled=self.store.read().get('enabled',True),rollback_notice=self.store.read().get('notice',''))

    def status(self,status,message):
        with self.lock:
            self.state.update(status=status,message=message)

    def check(self):
        if not self.store.read().get('enabled',True):
            return
        try:
            if self.store.read().get('pending'):
                self.status('ready','Atualização pronta; aguardando terminar a tarefa atual.')
                return
            self.status('checking','Buscando versão estável no GitHub…')
            manifest,sha = candidate(self.fetch)
            newer = version(manifest['version'])>version(self.current)
            if not newer or manifest['version'] in self.store.read().get('rejected',[]):
                self.status('current','Você está na versão disponível para este canal.')
                return
            self.status('downloading','Baixando e verificando atualização…')
            raw = content(self.fetch,'downloads/BrowserAPI-runtime.zip',sha)
            self.store.stage(manifest,raw)
            self.status('ready','Atualização pronta; será aplicada quando o programa estiver livre.')
        except Exception:
            self.status('error','Não foi possível atualizar agora. A versão atual foi preservada; nova tentativa automática mais tarde.')

    def run(self):
        # Não bloquear abertura da interface por rede; uma thread, sem retries rápidos.
        if self.stop.wait(5):
            return
        while not self.stop.is_set():
            self.check()
            deadline = time.monotonic()+self.interval
            while not self.stop.is_set():
                if self.store.read().get('enabled',True) and self.store.read().get('pending'):
                    if self.on_ready():
                        return
                if self.wake.wait(1):
                    self.wake.clear()
                    break
                if time.monotonic()>=deadline:
                    break

    def start(self):
        self.thread = threading.Thread(target=self.run,name='BrowserAPI updates',daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(1)
