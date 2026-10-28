"""Janela estatística limitada, sem conteúdo e sem sucesso/uso inventado."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from browserapi_lab.telemetry import Telemetry, clean_timings


class TestTelemetry(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.metrics = Telemetry(limit=3, clock=lambda:self.now)

    def record(self, status, duration=None, operation='check', name='chat', phase='done'):
        self.metrics.begin(operation,name)
        self.now += 1
        self.metrics.finish({'status':status,'timings':{'total_ms':duration}},phase)

    def test_empty_is_unknown_not_zero_tokens_or_zero_latency(self):
        value = self.metrics.snapshot()
        self.assertEqual(value['requests'],0)
        self.assertIsNone(value['success_rate'])
        self.assertIsNone(value['average_ms'])
        self.assertIsNone(value['tokens'])
        self.assertEqual(value['token_source'],'not_reported')

    def test_window_and_statistics_are_consistent_not_lifetime(self):
        self.record('success',100)
        self.record('timeout',300)
        self.record('success',200)
        self.record('success',400)
        value = self.metrics.snapshot()
        self.assertEqual([r['id'] for r in value['history']],[2,3,4])
        self.assertEqual(value['requests'],3)
        self.assertEqual(value['successes'],2)
        self.assertEqual(value['failures'],1)
        self.assertEqual(value['success_rate'],66.7)
        self.assertEqual(value['average_ms'],300)
        self.assertEqual(value['p95_ms'],400)

    def test_denials_errors_and_cancellation_do_not_fabricate_request_result(self):
        self.record('not_authorized')
        self.record(None,phase='cancelled')
        self.record(None,phase='error')
        value = self.metrics.snapshot()
        self.assertEqual(value['requests'],0)
        self.assertEqual(value['cancelled'],1)
        self.assertEqual(value['denied'],1)
        self.assertEqual(value['operation_errors'],1)
        self.assertIsNone(value['average_ms'])

    def test_sources_are_last_observation_stale_or_waiting_not_heartbeats(self):
        self.record('success',100)
        self.assertEqual(self.metrics.snapshot()['sources']['chat']['state'],'online')
        self.now += 301
        self.assertTrue(self.metrics.snapshot()['sources']['chat']['stale'])
        self.metrics.begin('check','chat')
        self.assertEqual(self.metrics.snapshot()['sources']['chat']['state'],'busy')
        self.metrics.finish({'status':'rate_limit'})
        self.assertEqual(self.metrics.snapshot()['sources']['chat']['state'],'rate_limited')
        self.record('timeout',900)
        self.assertEqual(self.metrics.snapshot()['sources']['chat']['state'],'degraded')

    def test_repair_and_mode_change_invalidate_old_online_observation(self):
        self.record('success',100)
        self.record(None,operation='use_existing')
        self.assertEqual(self.metrics.snapshot()['sources']['chat']['state'],'not_observed')
        self.record(None,phase='cancelled')
        self.assertEqual(self.metrics.snapshot()['sources']['chat']['state'],'interrupted')

    def test_payload_is_whitelisted_numeric_finite_and_content_free(self):
        self.metrics.begin('ask','chat')
        self.metrics.user_wait(120)
        self.metrics.user_wait(float('nan'))
        self.now += 1
        self.metrics.finish({'status':'success','answer':'SECRET','message':'SECRET','url':'SECRET',
            'cookies':'SECRET','tokens':999,'timings':{'total_ms':300,'parse_ms':2,
            'selector':'SECRET','send_ms':-1,'fill_ms':float('inf'),'preflight_ms':True}})
        value = self.metrics.snapshot()
        text = json.dumps(value,allow_nan=False)
        self.assertNotIn('SECRET',text)
        self.assertEqual(value['history'][0]['timings']['manual_wait_ms'],120)
        self.assertEqual(value['history'][0]['timings']['operation_wall_ms'],1000)
        self.assertNotIn('fill_ms',value['history'][0]['timings'])
        self.assertIsNone(value['tokens'])
        self.assertEqual(clean_timings({'total_ms':None,'foo':100}),{})

    def test_snapshots_do_not_leak_mutable_state_and_inputs_validated(self):
        self.record('success',100)
        view = self.metrics.snapshot()
        view['history'][0]['timings']['total_ms']=999
        self.assertEqual(self.metrics.snapshot()['history'][0]['timings']['total_ms'],100)
        with self.assertRaises(ValueError):
            self.metrics.begin('execute-shell','chat')
        with self.assertRaises(ValueError):
            self.metrics.begin('check','https://private.invalid')
        with self.assertRaises(ValueError):
            Telemetry(limit=0)

    def test_timing_absence_is_not_silently_included_as_zero(self):
        self.record('success',100)
        self.record('google_login_blocked')
        value = self.metrics.snapshot()
        self.assertEqual(value['requests'],2)
        self.assertEqual(value['timed_requests'],1)
        self.assertEqual(value['average_ms'],100)
        self.assertEqual(value['sources']['chat']['state'],'auth_blocked')

    def test_concurrent_snapshots_remain_bounded_and_json_serializable(self):
        errors = []
        done = threading.Event()
        def read():
            while not done.is_set():
                try:
                    value = self.metrics.snapshot()
                    self.assertLessEqual(len(value['history']),3)
                    json.dumps(value,allow_nan=False)
                except BaseException as error:
                    errors.append(error)
                    return
        thread = threading.Thread(target=read)
        thread.start()
        try:
            for _ in range(100):
                self.record('success',10)
        finally:
            done.set()
            thread.join(2)
        self.assertFalse(errors,errors)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.metrics.snapshot()['operations'],3)

    def test_malformed_status_and_huge_numbers_are_not_echoed(self):
        self.assertEqual(clean_timings({'total_ms':10**1000}),{})
        self.record({'private':'SECRET'})
        self.assertNotIn('SECRET',json.dumps(self.metrics.snapshot()))

    def test_usage_counts_measured_characters_only_and_never_invents_tokens(self):
        telemetry = Telemetry()
        telemetry.begin('ask', 'chat')
        telemetry.usage(120, 480)
        telemetry.usage(0, -5)          # inválido: ignorado, não vira consumo
        telemetry.usage(1e12, 3)        # fora do limite: ignorado
        telemetry.finish({'status':'success','timings':{'total_ms':100}}, 'done')
        state = telemetry.snapshot()
        usage = state['usage']
        self.assertEqual(usage['prompt_chars'], 120)
        self.assertEqual(usage['response_chars'], 480)
        self.assertEqual(usage['total_chars'], 600)
        self.assertEqual(usage['measured_responses'], 1)
        self.assertIsNone(usage['tokens'])
        self.assertIsNone(usage['estimated_tokens'])
        self.assertEqual(usage['token_source'], 'not_reported')
        record = state['history'][0]
        self.assertEqual((record['prompt_chars'], record['response_chars']), (120, 480))
        self.assertNotIn('SECRET', json.dumps(state))

    def test_usage_absent_is_none_not_zero_on_records(self):
        telemetry = Telemetry()
        telemetry.begin('doctor')
        telemetry.finish({'status':None}, 'done')
        record = telemetry.snapshot()['history'][0]
        self.assertIsNone(record['prompt_chars'])
        self.assertIsNone(record['response_chars'])
        self.assertEqual(telemetry.snapshot()['usage']['total_chars'], 0)



class TestPersistencia(unittest.TestCase):
    """A atualização do aplicativo reinicia o programa: a Atividade não pode zerar.

    Só o agregado (lista branca) vai para o disco; nada de prompt/resposta/URL.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'telemetry.json'

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, telemetry, status='success', **timings):
        telemetry.begin('check', 'chat')
        telemetry.usage(12, 34)
        telemetry.finish({'status': status, 'timings': timings})

    def test_round_trip_keeps_aggregate_and_not_content(self):
        first = Telemetry(path=self.path)
        self.record(first, total_ms=100)
        second = Telemetry(path=self.path)
        snapshot = second.snapshot()
        self.assertTrue(snapshot['persisted'])
        self.assertEqual(snapshot['scope'], 'rolling_window_persisted')
        self.assertEqual(snapshot['operations'], 1)
        self.assertEqual(snapshot['usage']['total_chars'], 46)
        self.assertEqual(snapshot['history'][0]['timings']['total_ms'], 100)
        raw = self.path.read_text()
        for forbidden in ('"answer"', '"text"', 'seletor', 'http://', 'https://'):
            self.assertNotIn(forbidden, raw)
        # Permissão restrita: é o histórico do usuário, não da rede.
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), '0o600')

    def test_sequence_continues_after_reload(self):
        first = Telemetry(path=self.path)
        self.record(first)
        self.record(first)
        second = Telemetry(path=self.path)
        self.record(second)
        self.assertEqual(second.snapshot()['history'][-1]['id'], 3)

    def test_corrupt_or_foreign_file_is_ignored(self):
        self.path.write_text('{"schema_version": 1, "records": "nada"}')
        self.assertEqual(Telemetry(path=self.path).snapshot()['operations'], 0)
        self.path.write_text('não é json')
        self.assertEqual(Telemetry(path=self.path).snapshot()['operations'], 0)
        self.path.write_text(json.dumps({'schema_version': 99, 'records': []}))
        self.assertEqual(Telemetry(path=self.path).snapshot()['operations'], 0)

    def test_records_with_content_or_unknown_status_are_rejected(self):
        payload = {'schema_version': 1, 'records': [
            {'id': 1, 'operation': 'check', 'name': 'chat', 'phase': 'done', 'status': 'success',
             'timings': {'total_ms': 10}, 'at': '2026-10-28T10:00:00Z', 'prompt': 'segredo'},
            {'id': 2, 'operation': 'check', 'name': 'chat', 'phase': 'done', 'status': 'inventado',
             'timings': {}, 'at': '2026-10-28T10:00:00Z'},
            {'id': 3, 'operation': 'hackear', 'name': 'chat', 'phase': 'done', 'status': 'success',
             'timings': {}, 'at': '2026-10-28T10:00:00Z'},
        ]}
        self.path.write_text(json.dumps(payload))
        snapshot = Telemetry(path=self.path).snapshot()
        self.assertEqual(snapshot['operations'], 1)
        self.assertNotIn('segredo', json.dumps(snapshot))
        self.assertEqual(set(snapshot['history'][0]),
                         {'id', 'operation', 'name', 'phase', 'status', 'timings',
                          'prompt_chars', 'response_chars', 'at', 'attempts'})

    def test_without_path_nothing_is_written(self):
        telemetry = Telemetry()
        self.record(telemetry)
        self.assertFalse(telemetry.snapshot()['persisted'])
        self.assertEqual(telemetry.snapshot()['scope'], 'current_process_rolling_window')

    def test_write_failure_does_not_break_the_operation(self):
        with patch.object(Path, 'write_text', side_effect=OSError('disco cheio')):
            telemetry = Telemetry(path=self.path)
            self.record(telemetry)
        self.assertEqual(telemetry.snapshot()['operations'], 1)
        self.assertFalse(telemetry.snapshot()['persisted'])
