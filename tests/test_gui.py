"""Painel: autenticação/origem, consentimento serializado e pacote Ubuntu."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.gui import LocalServer, Panel, prepare_runtime


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('Estado esperado não foi alcançado')


class TestPanel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name) / 'configs')
        self.panel = Panel(self.store, Path(self.tmp.name) / 'data')
        self.server = LocalServer(self.panel)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.panel.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.tmp.cleanup()

    def request(self, path='/api/state', *, method='GET', token=True, origin=None, host=None, body=None, raw=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-BrowserAPI-Token'] = self.server.token if token is True else token
        if origin:
            headers['Origin'] = origin
        if host:
            headers['Host'] = host
        data = json.dumps(body).encode() if body is not None else raw
        connection.request(method, path, data, headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_native_profile_open_is_authenticated_allowlisted_and_blocked_while_busy(self):
        body={'profile':'chrome:Default','destination':'chat','provider':'gemini'}
        with patch('browserapi_lab.profiles.open_profile') as native:
            self.assertEqual(self.request('/api/profile',method='POST',body=body,token=False)[0],403)
            native.assert_not_called()
            self.assertEqual(self.request('/api/profile',method='POST',body=body)[0],200)
            native.assert_called_once_with('chrome:Default','https://gemini.google.com/app')
            native.reset_mock()
            body['destination']='arbitrary-command'
            self.assertEqual(self.request('/api/profile',method='POST',body=body)[0],400)
            self.panel.phase='waiting';body['destination']='permission'
            self.assertEqual(self.request('/api/profile',method='POST',body=body)[0],400)
            native.assert_not_called()
            self.panel.phase='idle'
        self.assertEqual(self.request('/inter.ttf',token=False)[0],200)
        self.assertEqual(self.request('/mono.ttf',token=False)[0],200)

    def test_ledger_spacing_and_local_font_contract(self):
        import re
        from browserapi_lab.gui import ASSETS
        css=(ASSETS/'panel.css').read_text()
        for prop,value in re.findall(r'(padding(?:-[a-z]+)?|margin(?:-[a-z]+)?|gap)\s*:\s*([^;}]+)',css):
            if prop=='margin-left' and value in ('232px','200px'):
                continue  # offsets iguais à largura da navegação, não espaçadores
            for number in re.findall(r'(?<![.\d])(\d+)px',value):
                self.assertIn(int(number),(0,4,8,16,24,32,40,48,56,64),(prop,value))
        self.assertNotIn('https://',css)
        self.assertIn('font-weight:450',css)
        self.assertIn('prefers-reduced-motion',css)

    def test_conversation_ui_contract_renders_text_only(self):
        from browserapi_lab.gui import ASSETS
        html = (ASSETS/'panel.html').read_text()
        js = (ASSETS/'panel.js').read_text()
        css = (ASSETS/'panel.css').read_text()
        for identifier in ('conversation-card','conversation','conversation-empty','conversation-copy',
                           'conversation-clear','conversation-scope','conversation-feedback'):
            self.assertIn(f'id="{identifier}"', html)
        self.assertIn('Limpar aqui não apaga a conversa do site', html)
        self.assertIn('somente esta sessão', html.lower())
        # Conteúdo da página entra como texto: sem innerHTML em nenhum lugar.
        for unsafe in ('innerHTML','insertAdjacentHTML','outerHTML','document.write'):
            self.assertNotIn(unsafe, js)
        self.assertIn('body.textContent = message.text', js)
        self.assertIn("api('conversation?name=' + encodeURIComponent(requested))", js)
        self.assertIn("api('conversation/clear',{name:selected})", js)
        self.assertIn('incompatible()', js.split('function conversationControls()')[1].split('}')[0])
        self.assertIn('.conversation-card{grid-column:2}', css)
        self.assertIn('@media(max-width:640px){.conversation-card{grid-column:auto}}', css)

    def test_auto_update_setting_is_authenticated_and_updating_blocks_tasks(self):
        from browserapi_lab.updates import UpdateStore, Updater
        store = UpdateStore(Path(self.tmp.name)/'update-data')
        self.panel.updater = Updater(store,'0.3.0',lambda:False)
        self.assertEqual(self.request('/api/updates',method='POST',token=False,body={'enabled':False})[0],403)
        self.assertTrue(store.read().get('enabled',True))
        self.assertEqual(self.request('/api/updates',method='POST',body={'enabled':False})[0],200)
        self.assertFalse(store.read()['enabled'])
        self.assertEqual(self.request('/api/updates',method='POST',body={'enabled':'false'})[0],400)
        self.assertTrue(json.loads(self.request()[2])['updates']['managed'])
        with self.panel.lock:
            self.panel.phase='updating'
        self.assertEqual(self.request('/api/task',method='POST',body={'operation':'doctor'})[0],400)

    def test_static_is_allowlisted_and_has_security_headers(self):
        code, headers, body = self.request('/', token=False)
        self.assertEqual(code, 200)
        self.assertIn(b'panel.js', body)
        self.assertNotIn(self.server.token.encode(), body)
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(self.request('/../../etc/passwd')[0], 404)
        self.assertEqual(self.request('/panel.css', token=False)[0], 200)
        self.assertEqual(self.server.server_address[0], '127.0.0.1')

    def test_favicon_public_empty_and_runtime_versioned_assets(self):
        from browserapi_lab.version import APP_VERSION
        code, _, data = self.request('/favicon.ico', token=False)
        self.assertEqual((code,data),(204,b''))
        self.assertEqual(json.loads(self.request()[2])['version'],APP_VERSION)
        for path in ('/','/panel.js'):
            body = self.request(path, token=False)[2]
            self.assertIn(APP_VERSION.encode(),body)
            self.assertNotIn(b'__BROWSERAPI_PANEL_VERSION__',body)
        self.assertEqual(self.request('/favicon.ico', host='evil.example')[0],403)

    def test_task_400_explains_reason_without_exposing_paths(self):
        code, _, body = self.request('/api/task',method='POST',body={'operation':'point_send','name':'missing'})
        self.assertEqual(code,400)
        self.assertIn('Chat salvo não encontrado',json.loads(body)['error'])
        self.assertNotIn(self.tmp.name,body.decode())
        self.store.save(ChatConfig('saved','https://example.com'))
        code, _, body = self.request('/api/task',method='POST',body={'operation':'configure','name':'saved','provider':'gemini','browser':'chrome'})
        self.assertEqual(code,400)
        self.assertIn('Nome já salvo',json.loads(body)['error'])
        with self.panel.lock:
            self.panel.phase = 'running'
        code, _, body = self.request('/api/task',method='POST',body={'operation':'doctor'})
        self.assertEqual(code,400)
        self.assertIn('operação já está em andamento',json.loads(body)['error'])

    def test_auth_host_and_origin_rejected(self):
        self.assertEqual(self.request(token=False)[0], 403)
        self.assertEqual(self.request(token='wrong')[0], 403)
        self.assertEqual(self.request(origin='https://evil.example')[0], 403)
        self.assertEqual(self.request(host='evil.example')[0], 403)
        self.assertEqual(self.request(origin=self.server.url)[0], 200)
        self.assertEqual(self.request('/api/cancel', method='POST', token=False, body={})[0], 403)
        self.assertEqual(self.request('/api/task', method='POST', origin='null', body={'operation':'doctor'})[0], 403)

    def test_payload_limits_and_invalid_fields(self):
        self.assertEqual(self.request('/api/task', method='POST', raw=b'x' * 131073)[0], 413)
        self.assertEqual(self.request('/api/task', method='POST', raw=b'not json')[0], 400)
        self.assertEqual(self.request('/api/task', method='POST', body=[])[0], 400)
        self.assertEqual(self.request('/api/task', method='POST', body={'operation':'exec'})[0], 400)
        self.assertEqual(self.request('/api/task', method='POST', body={'operation':'configure','name':'../x'})[0], 400)
        self.assertEqual(self.request('/api/task', method='POST', body={'operation':'configure','name':'x','provider':'gemini','browser':'custom'})[0], 400)
        self.assertEqual(self.request('/api/task', method='POST', body={'operation':'configure','name':'x','provider':'custom','browser':'chromium','url':'https://user:password@example.com'})[0], 400)

    def test_metrics_finish_with_task_not_stale_receipt_or_duplicate_send(self):
        self.store.save(ChatConfig('saved','https://example.com'))
        def check_once(*args, **kwargs):
            kwargs['ask']('Autoriza? [s/N] ')
            return {'status':'success','timings':{'total_ms':123},'answer':'SECRET'}
        with patch('browserapi_lab.gui.check',side_effect=check_once) as check_call:
            self.panel.submit({'operation':'check','name':'saved'})
            until(lambda:self.panel.snapshot()['prompt'])
            self.assertEqual(self.panel.snapshot()['telemetry']['sources']['saved']['state'],'busy')
            self.panel.reply(self.panel.snapshot()['prompt']['id'],'s')
            until(lambda:self.panel.snapshot()['phase']=='done')
            state = self.panel.snapshot()['telemetry']
            self.assertEqual(state['requests'],1)
            self.assertGreater(state['history'][0]['timings']['manual_wait_ms'],0)
            check_call.assert_called_once()
        self.panel.submit({'operation':'doctor'})
        until(lambda:self.panel.snapshot()['phase']=='done')
        state = self.panel.snapshot()['telemetry']
        self.assertEqual(state['operations'],2)
        self.assertEqual(state['requests'],1)
        self.assertIsNone(state['history'][-1]['status'])
        self.assertNotIn('SECRET',json.dumps(state))
        with patch('browserapi_lab.gui.check',side_effect=RuntimeError('SECRET')):
            self.panel.submit({'operation':'check','name':'saved'})
            until(lambda:self.panel.snapshot()['phase']=='error')
        state = self.panel.snapshot()['telemetry']
        self.assertEqual(state['operation_errors'],1)
        self.assertEqual(state['requests'],1)
        self.assertEqual(state['sources']['saved']['state'],'needs_attention')
        self.assertNotIn('SECRET',json.dumps(state))

    def test_prompt_unique_reply_once_and_cancel(self):
        result = []
        worker = threading.Thread(target=lambda: result.append(self.panel.ask('Autoriza? [s/N] ')))
        worker.start()
        until(lambda: self.panel.snapshot()['prompt'])
        identifier = self.panel.snapshot()['prompt']['id']
        self.assertEqual(self.panel.snapshot()['prompt']['kind'], 'yesno')
        with self.assertRaises(ValueError):
            self.panel.reply('old', 's')
        with self.assertRaises(ValueError):
            self.panel.reply(identifier, 'yes')
        self.panel.reply(identifier, 'n')
        worker.join(2)
        self.assertEqual(result, ['n'])
        with self.assertRaises(ValueError):
            self.panel.reply(identifier, 's')
        cancelled = []
        def waiting():
            try:
                self.panel.ask('Continue')
            except EOFError:
                cancelled.append(True)
        worker = threading.Thread(target=waiting)
        worker.start()
        until(lambda: self.panel.snapshot()['prompt'])
        self.panel.cancel()
        worker.join(2)
        self.assertEqual(cancelled, [True])

    def test_prepare_runs_once_off_http_thread_and_cancels(self):
        started = threading.Event()
        finished = threading.Event()
        def installer(_path, tell, cancelled):
            self.assertNotEqual(threading.current_thread(), threading.main_thread())
            started.set()
            until(cancelled)
            finished.set()
            raise EOFError()
        self.panel.installer = installer
        self.panel.submit({'operation':'prepare'})
        self.assertTrue(started.wait(2))
        with self.assertRaises(ValueError):
            self.panel.submit({'operation':'prepare'})
        self.panel.cancel()
        self.assertTrue(finished.wait(2))
        until(lambda: self.panel.phase == 'cancelled')
        self.assertIn('não desfaz', '\n'.join(self.panel.snapshot()['messages']))

    def test_interrupted_operation_says_where_it_stopped(self):
        """"Interrompido" sem motivo não dizia se foi você ou o programa."""
        self.store.save(ChatConfig('chat','https://example.com'))
        with patch('browserapi_lab.gui.check', side_effect=EOFError('Mapeamento cancelado')):
            self.panel.submit({'operation':'check','name':'chat'})
            until(lambda: self.panel.phase == 'cancelled')
        self.assertIn('Mapeamento cancelado', '\n'.join(self.panel.snapshot()['messages']))

    def test_step_unavailable_is_an_error_with_the_reason_not_a_cancel(self):
        from browserapi_lab.setup import StepUnavailable
        self.store.save(ChatConfig('chat','https://example.com'))
        with patch('browserapi_lab.gui.check',
                   side_effect=StepUnavailable('O painel de seleção não abriu nesta página. Nada foi alterado.')):
            self.panel.submit({'operation':'check','name':'chat'})
            until(lambda: self.panel.phase == 'error')
        messages = '\n'.join(self.panel.snapshot()['messages'])
        self.assertIn('O painel de seleção não abriu', messages)
        self.assertNotIn('não desfaz', messages)

    def test_switch_existing_saved_chat_never_launches_and_requires_consent(self):
        self.store.save(ChatConfig('saved','https://example.com'))
        with patch('browserapi_lab.browser.BrowserSession.start') as launch:
            for reply, expected in (('n','dedicated'),('s','existing_chrome')):
                self.panel.submit({'operation':'use_existing','name':'saved'})
                until(lambda: self.panel.snapshot()['prompt'])
                self.panel.reply(self.panel.snapshot()['prompt']['id'],reply)
                until(lambda: self.panel.phase == 'done')
                self.assertEqual(self.store.load('saved').session_mode,expected)
            self.assertEqual(self.store.load('saved').browser,'chrome')
            launch.assert_not_called()

    def test_configure_uses_form_and_rejects_overwrite(self):
        def fake_configure(store, name, **kwargs):
            config = kwargs['initial_config']
            self.assertEqual(config.browser, 'chromium')
            self.assertEqual(config.provider, 'gemini')
            store.save(config)
            return {'compatible_in_this_run':False}
        with patch('browserapi_lab.gui.configure', side_effect=fake_configure):
            self.panel.submit({'operation':'configure','name':'chat','provider':'gemini','browser':'chromium'})
            until(lambda: self.panel.phase == 'done')
        with self.assertRaises(ValueError):
            self.panel.submit({'operation':'configure','name':'chat','provider':'gemini','browser':'chrome'})
        self.assertEqual(self.store.load('chat').browser, 'chromium')

    def test_backend_errors_are_sanitized_and_no_retry(self):
        self.store.save(ChatConfig('chat','https://example.com'))
        with patch('browserapi_lab.gui.check', side_effect=RuntimeError('SECRET password cookie')) as operation:
            self.panel.submit({'operation':'check','name':'chat'})
            until(lambda: self.panel.phase == 'error')
            self.assertEqual(operation.call_count, 1)
        self.assertNotIn('SECRET', json.dumps(self.panel.snapshot()))

    def test_install_refuses_root_and_low_disk_before_spawning(self):
        with patch('browserapi_lab.gui.os.geteuid', return_value=0), patch('browserapi_lab.gui.subprocess.Popen') as spawn:
            with self.assertRaises(RuntimeError):
                prepare_runtime(Path(self.tmp.name) / 'install', lambda _:None, lambda:False)
            spawn.assert_not_called()
        with patch('browserapi_lab.gui.os.geteuid', return_value=1000), patch('browserapi_lab.gui.shutil.disk_usage', return_value=type('Disk', (), {'free':0})()), patch('browserapi_lab.gui.subprocess.Popen') as spawn:
            with self.assertRaises(RuntimeError):
                prepare_runtime(Path(self.tmp.name) / 'install', lambda _:None, lambda:False)
            spawn.assert_not_called()


    def test_delete_chat_requires_auth_and_idle_and_preserves_other_connections(self):
        self.store.save(ChatConfig('remove-me','https://example.com'))
        self.store.save(ChatConfig('keep-me','https://example.com'))
        self.store.save_status('remove-me',{'status':'not_tested'})
        body={'name':'remove-me'}
        self.assertEqual(self.request('/api/chat/delete',method='POST',token=False,body=body)[0],403)
        with self.panel.lock:
            self.panel.phase='waiting'
        self.assertEqual(self.request('/api/chat/delete',method='POST',body=body)[0],400)
        with self.panel.lock:
            self.panel.phase='idle'
        self.assertEqual(self.request('/api/chat/delete',method='POST',body={'name':'../keep-me'})[0],400)
        self.assertEqual(self.request('/api/chat/delete',method='POST',body=body)[0],200)
        self.assertEqual(self.store.names(),['keep-me'])
        self.assertIsNone(self.store.status('remove-me'))


    def test_conversation_endpoint_is_authenticated_scoped_and_private(self):
        self.store.save(ChatConfig('um','https://example.com'))
        self.store.save(ChatConfig('dois','https://example.com'))
        self.panel.transcript.add_exchange('um','pergunta reservada','resposta reservada',total_ms=99)
        self.panel.transcript.add_exchange('dois','outra pergunta','outra resposta')
        for path in ('/api/conversation?name=um','/api/conversation?name=../um'):
            self.assertEqual(self.request(path,token=False)[0],403)
            self.assertEqual(self.request(path,origin='https://evil.example')[0],403)
        self.assertEqual(self.request('/api/conversation')[0],400)
        self.assertEqual(self.request('/api/conversation?name=../um')[0],400)
        self.assertEqual(self.request('/api/conversation?name=nao-existe')[0],404)
        self.assertEqual(self.request('/api/conversation?name=um&name=dois')[0],400)
        code, headers, body = self.request('/api/conversation?name=um')
        self.assertEqual(code,200)
        self.assertEqual(headers['Cache-Control'],'no-store')
        view = json.loads(body)
        self.assertEqual([item['text'] for item in view['messages']],['pergunta reservada','resposta reservada'])
        self.assertEqual(view['revision'],1)
        # A rota de estado informa apenas o resumo, nunca o texto da conversa.
        state = json.loads(self.request()[2])
        summary = {chat['name']:chat.get('conversation') for chat in state['chats']}
        self.assertEqual(summary['um']['turns'],1)
        self.assertEqual(summary['um']['revision'],1)
        self.assertNotIn('pergunta reservada',json.dumps(state))
        self.assertNotIn('resposta reservada',json.dumps(state))

    def test_conversation_clear_needs_auth_idle_and_keeps_other_chats(self):
        self.store.save(ChatConfig('um','https://example.com'))
        self.store.save(ChatConfig('dois','https://example.com'))
        self.panel.transcript.add_exchange('um','q1','a1')
        self.panel.transcript.add_exchange('dois','q2','a2')
        body={'name':'um'}
        self.assertEqual(self.request('/api/conversation/clear',method='POST',token=False,body=body)[0],403)
        with self.panel.lock:
            self.panel.phase='waiting'
        self.assertEqual(self.request('/api/conversation/clear',method='POST',body=body)[0],400)
        with self.panel.lock:
            self.panel.phase='idle'
        self.assertEqual(self.request('/api/conversation/clear',method='POST',body={'name':'../um'})[0],400)
        self.assertEqual(self.request('/api/conversation/clear',method='POST',body=body)[0],200)
        self.assertEqual(json.loads(self.request('/api/conversation?name=um')[2])['messages'],[])
        self.assertEqual(len(json.loads(self.request('/api/conversation?name=dois')[2])['messages']),2)

    def test_deleting_a_connection_forgets_the_text_shown_only_for_it(self):
        self.store.save(ChatConfig('remover','https://example.com'))
        self.store.save(ChatConfig('manter','https://example.com'))
        self.panel.transcript.add_exchange('remover','pergunta privada','resposta privada')
        self.panel.transcript.add_exchange('manter','pergunta mantida','resposta mantida')
        self.assertEqual(self.request('/api/chat/delete',method='POST',body={'name':'remover'})[0],200)
        self.assertNotIn('remover',self.panel.transcript.entries)
        self.assertIn('manter',self.panel.transcript.entries)
        self.assertEqual(self.request('/api/conversation?name=remover')[0],404)
        self.assertEqual(self.request('/api/conversation?name=manter')[0],200)

    def test_ask_records_validated_answer_in_the_panel_and_not_in_the_log(self):
        self.store.save(ChatConfig('chat','https://example.com'))
        def fake_check(store, name, **kwargs):
            self.assertIs(kwargs['show_answer'], False)
            kwargs['record'](name,'minha pergunta','resposta mostrada na conversa',{'timings':{'total_ms':321.4}})
            return {'status':'success','compatible_in_this_run':True,'timings':{'total_ms':321.4}}
        with patch('browserapi_lab.gui.check',side_effect=fake_check):
            self.panel.submit({'operation':'ask','name':'chat','message':'minha pergunta'})
            until(lambda:self.panel.snapshot()['phase']=='done')
        view = json.loads(self.request('/api/conversation?name=chat')[2])
        self.assertEqual([item['text'] for item in view['messages']],
                         ['minha pergunta','resposta mostrada na conversa'])
        self.assertEqual(view['messages'][1]['total_ms'],321.4)
        self.assertNotIn('resposta mostrada na conversa','\n'.join(self.panel.snapshot()['messages']))
        self.assertNotIn('resposta mostrada na conversa',json.dumps(self.panel.snapshot()['telemetry']))
        self.assertNotIn('resposta mostrada na conversa',json.dumps(self.store.status('chat') or {}))

    def test_panel_html_is_valid_and_every_view_is_reachable(self):
        """O HTML é editado à mão: um id sem aspa já quebrou a aba Atividade."""
        from html.parser import HTMLParser
        from browserapi_lab.gui import ASSETS
        source = (ASSETS/'panel.html').read_text()

        class Audit(HTMLParser):
            def __init__(self):
                super().__init__()
                self.views, self.ids, self.broken, self.stack = [], [], [], []
                self.void = {'meta','link','br','hr','img','input','source','area','base','col','embed','track','wbr'}
            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if value is not None and (value.startswith('"') or value.startswith("'")):
                        self.broken.append((tag, key, value))
                values = dict(attrs)
                if values.get('id'):
                    self.ids.append(values['id'])
                if 'view' in (values.get('class') or '').split():
                    self.views.append(values['id'])
                if tag not in self.void:
                    self.stack.append(tag)
            def handle_endtag(self, tag):
                if tag in self.void:
                    return
                if self.stack and self.stack[-1] == tag:
                    self.stack.pop()
                elif tag in self.stack:
                    self.broken.append(('desbalanceado', tag, self.stack[-1]))

        audit = Audit(); audit.feed(source)
        self.assertEqual(audit.broken, [])
        self.assertEqual(audit.stack, [])
        self.assertEqual(audit.views, ['view-connections','view-activity','view-api','view-settings'])
        self.assertEqual(sorted({i for i in audit.ids if audit.ids.count(i) > 1}), [])
        js = (ASSETS/'panel.js').read_text()
        for view in audit.views:
            self.assertIn(view.removeprefix('view-'), js)

    def test_activity_is_graphical_and_usage_is_measured_not_invented(self):
        from browserapi_lab.gui import ASSETS
        js = (ASSETS/'panel.js').read_text()
        html = (ASSETS/'panel.html').read_text()
        for identifier in ('chart-status','chart-latency','chart-usage','chart-stages','chart-success',
                           'status-legend','stage-details','usage-note','source-health'):
            self.assertIn(f'id="{identifier}"', html)
        self.assertNotIn('latency-history', html)
        self.assertNotIn('<table>', html)
        self.assertIn("createElementNS(SVG_NS", js)
        for unsafe in ('innerHTML','insertAdjacentHTML','outerHTML','document.write'):
            self.assertNotIn(unsafe, js)
        # Rótulo textual junto do gráfico e estimativa declarada como grosseira.
        self.assertIn("'aria-label': label", js)
        self.assertIn('estimativa grosseira', js)
        self.assertIn('Não medido', html)

    def test_delete_is_visible_and_asks_with_the_connection_name(self):
        from browserapi_lab.gui import ASSETS
        js = (ASSETS/'panel.js').read_text()
        self.assertIn("remove.className='text-button danger'", js)
        self.assertIn("remove.textContent='Excluir'", js)
        self.assertIn('actions.append(remove)', js)
        self.assertIn('Excluir a conexão "${chat.name}"', js)
        self.assertIn('não são apagados', js)
        # Ações principais primeiro; detalhes técnicos continuam recolhidos.
        self.assertLess(js.index("['Testar agora'"), js.index("['Usar Chrome já aberto'"))

    def test_panel_forwards_step_and_hint_to_the_picker(self):
        """Regressão: o lambda do painel engolia step/hint e o passo morria."""
        from types import SimpleNamespace
        from unittest.mock import patch
        from browserapi_lab.gui import Panel
        panel = object.__new__(Panel)
        panel.cancelled = SimpleNamespace(is_set=lambda: False)
        with patch('browserapi_lab.gui.pick', return_value='#x') as fake:
            value = Panel.picker(panel, None, 'campo de mensagem', step='2 de 5', hint='clique aqui')
        self.assertEqual(value, '#x')
        fake.assert_called_once()
        args, kwargs = fake.call_args
        self.assertEqual(args[1], 'campo de mensagem')
        self.assertEqual(kwargs.get('step'), '2 de 5')
        self.assertEqual(kwargs.get('hint'), 'clique aqui')

    def test_guided_pointing_questions_say_which_element_to_click(self):
        from browserapi_lab.setup import repair_fields
        asked = []
        tells = []
        class Page:
            url = 'https://example.com/app'
            def evaluate(self, *_args, **_kwargs):
                return None
            def bring_to_front(self):
                pass
        config = ChatConfig('chat','https://example.com', composer='#c', send='#s', user='.u', assistant='.a', root='body')
        def ask(text):
            asked.append(text)
            return 'n'
        repair_fields(Page(), config, ask=ask, tell=tells.append, picker=lambda *_a, **_k: None,
                      fields=('user','assistant'))
        self.assertTrue(any('A SUA PERGUNTA JÁ ENVIADA' in text for text in asked))
        self.assertTrue(any('não o campo de digitar' in text for text in asked))
        self.assertTrue(any('A RESPOSTA DO CHAT' in text for text in asked))
        self.assertTrue(any('NÃO é a pergunta já enviada' in text for text in tells))
        self.assertFalse(any('Apontar mensagem do usuário?' == text for text in asked))

@unittest.skipUnless(shutil.which('dpkg-deb'), 'dpkg-deb não disponível')
class TestUbuntuPackage(unittest.TestCase):
    def test_build_extract_assets_and_import_outside_checkout(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'BrowserAPI-Ubuntu.deb'
            subprocess.run([sys.executable, str(root/'scripts/build_deb.py'), '--output', str(target)], check=True, capture_output=True)
            deps = subprocess.check_output(['dpkg-deb','--field',str(target),'Depends'], text=True)
            self.assertIn('python3 (>= 3.11)', deps)
            self.assertIn('python3-venv', deps)
            contents = subprocess.check_output(['dpkg-deb','--ctrl-tarfile',str(target)])
            self.assertNotIn(b'postinst', contents)
            self.assertNotIn(b'preinst', contents)
            destination = Path(tmp) / 'extract'
            subprocess.run(['dpkg-deb','--extract',str(target),str(destination)],check=True)
            share = destination / 'usr/share/browserapi-lab'
            for name in ('panel.html','panel.css','panel.js','picker.js','chat_probe.js'):
                self.assertTrue((share/'browserapi_lab/assets'/name).is_file(), name)
            desktop = (destination/'usr/share/applications/browserapi-lab.desktop').read_text()
            self.assertIn('Terminal=false', desktop)
            self.assertIn('Exec=/usr/bin/browserapi-window', desktop)
            launcher = destination/'usr/bin/browserapi-window'
            self.assertTrue(os.access(launcher, os.X_OK))
            env = dict(os.environ)
            env.pop('PYTHONPATH',None)
            process = subprocess.run([sys.executable, str(share/'open_window.py'), '--help'], cwd=tmp, env=env, text=True, capture_output=True)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertIn('Ubuntu',process.stdout)
