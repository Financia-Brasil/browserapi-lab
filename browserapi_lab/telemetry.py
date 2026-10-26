"""Observabilidade local limitada; não persiste conteúdo, cookies, seletores ou tokens."""
from collections import deque
import copy
import math
import threading
import time

from .chat import REMEDIES
from .config import safe_name

TIMING_KEYS = frozenset(('total_ms', 'browser_start_ms', 'page_open_ms', 'preflight_ms',
    'send_pipeline_ms', 'fill_ms', 'send_ms', 'response_wait_ms', 'parse_ms',
    'ttft_dom_ms', 'capture_overhead_ms', 'operation_wall_ms', 'manual_wait_ms'))
OPERATIONS = frozenset(('configure','repair','check','ask','prepare','doctor','point_voice','point_send','use_existing'))
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


class Telemetry:
    def __init__(self, limit=100, clock=time.monotonic):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Limite de histórico inválido')
        self.limit = limit
        self.clock = clock
        self.records = deque(maxlen=limit)
        self.lock = threading.RLock()
        self.sequence = 0
        self.active = None

    def begin(self, operation, name=None):
        if operation not in OPERATIONS:
            raise ValueError('Operação desconhecida')
        if name is not None:
            safe_name(name)
        with self.lock:
            self.active = {'operation':operation, 'name':name, 'started':self.clock(), 'manual_wait_ms':0.0}

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
                      'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()), 'observed':self.clock()}
            self.records.append(record)

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
            if record['name'] is not None and record['status'] not in (None,'not_authorized'):
                sources[record['name']] = {'state':HEALTH.get(record['status'],'needs_attention'),
                    'at':record['at'], 'stale':self.clock()-record['observed'] > 300}
            elif record['name'] is not None and record['phase'] in ('error','cancelled'):
                sources[record['name']] = {'state':'interrupted' if record['phase']=='cancelled' else 'needs_attention', 'at':record['at'],'stale':False}
            elif record['name'] is not None and record['operation'] in ('configure','repair','point_voice','point_send','use_existing'):
                sources[record['name']] = {'state':'not_observed','at':None,'stale':False}
        if active and active['name']:
            sources[active['name']] = {'state':'busy','at':None,'stale':False}
        for record in records:
            record.pop('observed')
        return {'scope':'current_process_rolling_window', 'limit':self.limit, 'history':records,
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
