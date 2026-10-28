"""Observabilidade local limitada; não persiste conteúdo, cookies, seletores ou tokens."""
from collections import deque
import copy
import json
import math
import os
from pathlib import Path
import threading
import time

from .chat import REMEDIES
from .config import safe_name

TIMING_KEYS = frozenset(('total_ms', 'browser_start_ms', 'page_open_ms', 'preflight_ms',
    'send_pipeline_ms', 'fill_ms', 'send_ms', 'response_wait_ms', 'parse_ms',
    'ttft_dom_ms', 'capture_overhead_ms', 'operation_wall_ms', 'manual_wait_ms'))
OPERATIONS = frozenset(('configure','repair','check','ask','prepare','doctor','point_voice','point_send','use_existing','api'))
STATUS = frozenset(REMEDIES) | {'success'}
HEALTH = {'success':'online', 'login_required':'login_required', 'google_login_blocked':'auth_blocked',
          'rate_limit':'rate_limited', 'captcha':'human_required', 'timeout':'degraded',
          'page_unavailable':'unavailable', 'browser_unavailable':'unavailable'}


def numeric(value):
    return type(value) in (float, int) and 0 <= value <= 86400000 and math.isfinite(value)


def clean_timings(values):
    if not isinstance(values, dict):
        return {}
    return {key: round(float(value), 3) for key, value in values.items() if key in TIMING_KEYS and numeric(value)}


SCHEMA_VERSION = 1
PHASES = ('done', 'error', 'cancelled')


class Telemetry:
    """Histórico agregado da janela limitada, opcionalmente persistido.

    O que vai para o disco é só o que já passa pela lista branca: operação,
    nome da conexão, estado, tempos, contagens de caracteres e tentativas. Nunca
    prompt, resposta, URL, seletor, cookie ou token. Sem caminho, o
    comportamento é o antigo (memória pura); com caminho, a atualização do
    aplicativo deixa de apagar a aba Atividade.
    """

    def __init__(self, limit=100, clock=time.monotonic, path=None):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Limite de histórico inválido')
        self.limit = limit
        self.clock = clock
        self.records = deque(maxlen=limit)
        self.lock = threading.RLock()
        self.sequence = 0
        self.active = None
        self.path = Path(path) if path is not None else None
        self.persisted = False
        if self.path is not None:
            self._load()

    # --- persistência (agregado, nunca conteúdo) -------------------------
    def _clean_record(self, value, now_epoch):
        """Aceita do disco só o que a lista branca já permitiria hoje."""
        if not isinstance(value, dict):
            return None
        record_id = value.get('id')
        operation = value.get('operation')
        phase = value.get('phase')
        status = value.get('status')
        at = value.get('at')
        if type(record_id) is not int or record_id < 1:
            return None
        if operation not in OPERATIONS or phase not in PHASES:
            return None
        if status is not None and status not in STATUS:
            return None
        if not isinstance(at, str) or len(at) != 20:
            return None
        name = value.get('name')
        if name is not None:
            try:
                name = safe_name(name)
            except ValueError:
                return None
        saved = value.get('saved_at')
        saved = saved if numeric(saved) else now_epoch
        age_ms = max(0.0, (now_epoch - saved) * 1000.0)
        attempts = []
        for item in value.get('attempts') or []:
            if not isinstance(item, dict) or item.get('status') not in STATUS:
                continue
            try:
                attempts.append({'name': safe_name(item.get('name')), 'status': item['status']})
            except ValueError:
                continue
        prompt_chars = value.get('prompt_chars')
        response_chars = value.get('response_chars')
        return {'id': record_id, 'operation': operation, 'name': name, 'phase': phase,
                'status': status, 'timings': clean_timings(value.get('timings')),
                'prompt_chars': prompt_chars if numeric(prompt_chars) else None,
                'response_chars': response_chars if numeric(response_chars) else None,
                'at': at, 'attempts': attempts[:8],
                'observed': self.clock() - age_ms / 1000.0}

    def _load(self):
        try:
            if not self.path.is_file() or self.path.stat().st_size > 2_000_000:
                return
            value = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeDecodeError):
            return
        if not isinstance(value, dict) or value.get('schema_version') != SCHEMA_VERSION:
            return
        now_epoch = time.time()
        records = value.get('records')
        if not isinstance(records, list):
            return
        loaded = []
        for item in records[-self.limit:]:
            clean = self._clean_record(item, now_epoch)
            if clean is not None:
                loaded.append(clean)
        with self.lock:
            for record in loaded:
                self.records.append(record)
                self.sequence = max(self.sequence, record['id'])
        self.persisted = bool(loaded)

    def _save(self):
        if self.path is None:
            return
        with self.lock:
            records = [{key: value for key, value in copy.deepcopy(record).items() if key != 'observed'}
                       for record in self.records]
            saved_at = time.time()
            payload = {'schema_version': SCHEMA_VERSION, 'saved_at': saved_at,
                       'sequence': self.sequence,
                       'records': [{**record, 'saved_at': saved_at} for record in records]}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding='utf-8')
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            self.persisted = True
        except OSError:
            # Disco cheio ou sem permissão não pode derrubar a operação.
            self.persisted = False

    def begin(self, operation, name=None):
        if operation not in OPERATIONS:
            raise ValueError('Operação desconhecida')
        if name is not None:
            safe_name(name)
        with self.lock:
            self.active = {'operation':operation, 'name':name, 'started':self.clock(), 'manual_wait_ms':0.0,
                           'prompt_chars':0, 'response_chars':0, 'measured_responses':0}

    def source(self,name):
        safe_name(name)
        with self.lock:
            if self.active:
                self.active['name']=name

    def usage(self, prompt_chars, response_chars):
        """Contabilidade medida em caracteres; nunca inventa tokens do provedor."""
        # Medição é do par: meio consumo implausível não entra como verdade.
        if not (numeric(prompt_chars) and numeric(response_chars)):
            return
        with self.lock:
            if self.active:
                self.active['prompt_chars'] += int(prompt_chars)
                self.active['response_chars'] += int(response_chars)
                self.active['measured_responses'] += 1

    def user_wait(self, milliseconds):
        with self.lock:
            if self.active and numeric(milliseconds):
                self.active['manual_wait_ms'] += milliseconds

    def finish(self, receipt=None, phase='done'):
        with self.lock:
            if self.active is None:
                return
            active, self.active = self.active, None
            self.sequence += 1
            receipt = receipt if isinstance(receipt, dict) else {}
            status = receipt.get('status')
            status = status if isinstance(status,str) and status in STATUS else None
            timings = clean_timings(receipt.get('timings'))
            timings.update(operation_wall_ms=round(max(0,self.clock()-active['started'])*1000,3),
                           manual_wait_ms=round(active['manual_wait_ms'],3))
            # A lista branca impede copiar answer/message/URLs/exceções recebidas.
            record = {'id':self.sequence, 'operation':active['operation'], 'name':active['name'],
                      'phase':phase if phase in ('done','error','cancelled') else 'error',
                      'status':status, 'timings':timings,
                      'prompt_chars':active['prompt_chars'] if active['prompt_chars'] else None,
                      'response_chars':active['response_chars'] if active['response_chars'] else None,
                      'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()), 'observed':self.clock()}
            attempts=[]
            if isinstance(receipt.get('attempts'),list):
                for item in receipt['attempts'][:8]:
                    if not isinstance(item,dict) or not isinstance(item.get('status'),str) or item['status'] not in STATUS:
                        continue
                    try:
                        name=safe_name(item.get('name'))
                    except ValueError:
                        continue
                    attempts.append({'name':name,'status':item['status']})
            record['attempts']=attempts
            self.records.append(record)
        self._save()

    def snapshot(self):
        with self.lock:
            records = copy.deepcopy(list(self.records))
            active = copy.deepcopy(self.active)
        # Todas as estatísticas são da janela limitada, não contadores vitalícios.
        requests = [r for r in records if r['status'] not in (None,'not_authorized')]
        successes = sum(r['status']=='success' for r in requests)
        durations = sorted(r['timings']['total_ms'] for r in requests if 'total_ms' in r['timings'])
        sources = {}
        for record in records:
            for attempt in record['attempts']:
                sources[attempt['name']]={'state':HEALTH.get(attempt['status'],'needs_attention'),'at':record['at'],'stale':self.clock()-record['observed']>300}
            if record['name'] is not None and record['status'] not in (None,'not_authorized'):
                sources[record['name']] = {'state':HEALTH.get(record['status'],'needs_attention'),
                    'at':record['at'], 'stale':self.clock()-record['observed'] > 300}
            elif record['name'] is not None and record['phase'] in ('error','cancelled'):
                sources[record['name']] = {'state':'interrupted' if record['phase']=='cancelled' else 'needs_attention', 'at':record['at'],'stale':False}
            elif record['name'] is not None and record['operation'] in ('configure','repair','point_voice','point_send','use_existing'):
                sources[record['name']] = {'state':'not_observed','at':None,'stale':False}
        if active and active['name']:
            sources[active['name']] = {'state':'busy','at':None,'stale':False}
        prompt_chars = sum(r.get('prompt_chars') or 0 for r in requests)
        response_chars = sum(r.get('response_chars') or 0 for r in requests)
        for record in records:
            record.pop('observed')
        scope = 'rolling_window_persisted' if self.persisted else 'current_process_rolling_window'
        return {'scope':scope, 'persisted':self.persisted, 'limit':self.limit, 'history':records,
                'usage':{'prompt_chars':prompt_chars, 'response_chars':response_chars,
                         'total_chars':prompt_chars+response_chars,
                         'measured_responses':sum(1 for r in requests if r.get('response_chars')),
                         'estimated_tokens':None, 'tokens':None, 'token_source':'not_reported',
                         'estimate_note':'Estimativa local só em caracteres; não é cobrança nem usage do provedor.'},
                'operations':len(records), 'requests':len(requests), 'successes':successes,
                'failures':len(requests)-successes,
                'operation_errors':sum(r['phase']=='error' for r in records),
                'cancelled':sum(r['phase']=='cancelled' for r in records),
                'denied':sum(r['status']=='not_authorized' for r in records),
                'success_rate':round(successes/len(requests)*100,1) if requests else None,
                'average_ms':round(sum(durations)/len(durations),1) if durations else None,
                'p95_ms':durations[max(0, math.ceil(.95*len(durations))-1)] if durations else None,
                'timed_requests':len(durations), 'tokens':None, 'token_source':'not_reported',
                'sources':sources, 'active':{'operation':active['operation'],'name':active['name']} if active else None}
