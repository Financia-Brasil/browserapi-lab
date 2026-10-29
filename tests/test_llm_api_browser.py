"""Cliente HTTP → worker único → Chromium real → fixture, sem contas reais."""
import base64
import http.client
import json
from pathlib import Path
import tempfile
import time
import statistics
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from _harness import BrowserTestCase, FixtureServer, REPO_ROOT
from browserapi_lab.browser import BrowserSession
from browserapi_lab.chat import ChatResult
from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.gui import Panel
from browserapi_lab.llm_api import APIService, WarmBrowser, Job
from browserapi_lab.setup import HYPOTHESES


class TestLLMAPIChromium(BrowserTestCase):
    def test_http_warm_page_idempotency_and_opt_in_resource_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);fixture=tmp/'fixture';fixture.mkdir()
            source=(REPO_ROOT/'fixtures/fake_chat.html').read_text()
            before,after=source.rsplit('</body>',1)
            (fixture/'fake_chat.html').write_text(before+'<img src="/pixel.png"><script>FakeChat.config({mode:"normal",delay:1});</script></body>'+after)
            (fixture/'pixel.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jk1cAAAAASUVORK5CYII='))
            server=FixtureServer(fixture).start()
            store=ConfigStore(tmp/'config')
            config=ChatConfig('saved',server.url(),provider='fixture',timeout_ms=8000,stability_ms=400,**HYPOTHESES['fixture'])
            store.save(config);store.save_status('saved',ChatResult('success',True).receipt(config))
            audit=[];failed=[]
            class AuditedSession(BrowserSession):
                def start(self):
                    result=super().start()
                    self.context.on('requestfailed',lambda request:failed.append(request.resource_type))
                    return result
            class AuditedWarm(WarmBrowser):
                def __init__(self,store):super().__init__(store,AuditedSession)
                def run(self,job,cancelled):
                    super().run(job,cancelled)
                    audit.append({'messages':self.page.evaluate('FakeChat.state().user_messages'),
                                  'reused':job.attempts[-1]['browser_reused'],'url_path':self.page.url.rsplit('/',1)[-1]})
                    if len(audit)==1:
                        self.page.evaluate("history.replaceState(null,'','/conversation-existing')")
            panel=Panel(store,tmp/'data');api=APIService(panel,port=0);panel.api_service=api
            def request(text,key,stream=False):
                connection=http.client.HTTPConnection('127.0.0.1',api.server.server_port,timeout=30)
                connection.request('POST','/v1/chat/completions',json.dumps({'model':'saved','messages':[{'role':'user','content':text}],'stream':stream}),
                                   {'Authorization':'Bearer '+api.state['key'],'Content-Type':'application/json','Idempotency-Key':key})
                response=connection.getresponse();raw=response.read().decode();code=response.status;connection.close()
                return code,raw
            try:
                with patch('browserapi_lab.llm_api.WarmBrowser',AuditedWarm):
                    api.configure({'enabled':True,'names':['saved'],'headless':True,'lightweight':True})
                    code,raw=request('primeira pergunta','first')
                    self.assertEqual(code,200,raw)
                    value=json.loads(raw)
                    self.assertTrue(value['choices'][0]['message']['content'])
                    # usage é estimativa rotulada (nunca zero nem inventado):
                    # zero fazia o agente nunca compactar.
                    self.assertGreater(value['usage']['total_tokens'],0)
                    self.assertTrue(value['usage']['browserapi']['estimated'])
                    self.assertIn('estimativa',value['usage']['browserapi']['note'].lower())
                    self.assertEqual(request('primeira pergunta','first')[1],raw)
                    code,sse=request('segunda pergunta','second',stream=True)
                    self.assertEqual(code,200,sse);self.assertIn('data: [DONE]',sse)
                    self.assertEqual([a['messages'] for a in audit],[1,2])
                    self.assertEqual([a['reused'] for a in audit],[False,True])
                    self.assertEqual(audit[1]['url_path'],'conversation-existing')
                    self.assertIn('image',failed)
                    self.assertEqual(panel.snapshot()['telemetry']['requests'],2)
                    destination=REPO_ROOT/'results/ci/llm-api-flow.json'
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    destination.write_text(json.dumps({'scope':'synthetic_http_api_real_chromium','audit':audit,
                        'idempotency_verified':True,'buffered_sse':True,'image_block_opt_in':True,
                        'usage':'estimated_plus_note'},indent=2)+'\n')
            finally:
                api.close();panel.close();server.stop()

    def test_measure_resource_modes_without_claiming_universal_speedup(self):
        measurements=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=root/'fixture';fixture.mkdir()
            source=(REPO_ROOT/'fixtures/fake_chat.html').read_text()
            before,after=source.rsplit('</body>',1)
            (fixture/'fake_chat.html').write_text(before+
                '<script>FakeChat.config({mode:"normal",delay:1});</script></body>'+after)
            server=FixtureServer(fixture).start()
            store=ConfigStore(root/'config')
            config=ChatConfig('saved',server.url(),provider='fixture',timeout_ms=8000,stability_ms=400,**HYPOTHESES['fixture'])
            store.save(config)
            try:
                # O harness já tem Playwright no thread principal. Assim como
                # no app, todos os modos medidos pertencem a um único worker.
                def measure():
                    for label,headless,light in [('visible',False,False),('headless',True,False),('headless_light',True,True)]:
                        warm=WarmBrowser(store)
                        samples=[]
                        try:
                            for i in range(3):
                                job=Job('pergunta sintética '+str(i),['saved'],{'headless':headless,'lightweight':light}, {})
                                start=time.perf_counter();warm.run(job,lambda:False)
                                elapsed=(time.perf_counter()-start)*1000
                                self.assertEqual(job.result.status,'success',f'{label}, sample {i}, attempts {job.attempts}')
                                self.assertEqual(job.result.send_state,'confirmed')
                                samples.append({'elapsed_ms':round(elapsed,3),'timings':job.result.timings,
                                                'reused':job.attempts[-1]['browser_reused']})
                            measurements.append({'mode':label,'samples':samples,
                                'warm_median_ms':round(statistics.median(s['elapsed_ms'] for s in samples[1:]),3)})
                        finally:
                            warm.close()
                with ThreadPoolExecutor(max_workers=1) as worker:
                    worker.submit(measure).result(timeout=90)
            finally:
                server.stop()
        destination=REPO_ROOT/'results/ci/resource-modes.json'
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps({'scope':'synthetic_chromium_only','samples_per_mode':3,
            'limitations':'No real site, memory/CPU measurement, statistical speedup or 4GB/24x7 claim',
            'measurements':measurements},indent=2)+'\n')

    def test_anthropic_messages_route_end_to_end_with_real_browser(self):
        """Claude Code fala /v1/messages: cabeçalho x-api-key, stream e tools.

        O modelo aqui é a fixture local; o que se prova é o caminho inteiro
        (HTTP → worker → Chromium → resposta no dialeto Anthropic), sem conta real.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=root/'fixture';fixture.mkdir()
            source=(REPO_ROOT/'fixtures/fake_chat.html').read_text()
            before,after=source.rsplit('</body>',1)
            (fixture/'fake_chat.html').write_text(before+'<script>FakeChat.config({mode:"normal",delay:1});</script></body>'+after)
            server=FixtureServer(fixture).start()
            store=ConfigStore(root/'config')
            config=ChatConfig('saved',server.url(),provider='fixture',timeout_ms=8000,stability_ms=400,**HYPOTHESES['fixture'])
            store.save(config);store.save_status('saved',ChatResult('success',True).receipt(config))
            panel=Panel(store,root/'data');api=APIService(panel,port=0);panel.api_service=api
            def call(path,body,headers):
                connection=http.client.HTTPConnection('127.0.0.1',api.server.server_port,timeout=30)
                values={'x-api-key':api.state['key'],'Content-Type':'application/json',
                        'anthropic-version':'2023-06-01'}
                values.update(headers)
                connection.request('POST',path,json.dumps(body),values)
                response=connection.getresponse();raw=response.read().decode()
                code,mime=response.status,response.getheader('Content-Type');connection.close()
                return code,raw,mime
            tools=[{'name':'Bash','description':'executa um comando no terminal',
                    'input_schema':{'type':'object','properties':{'command':{'type':'string'}}}}]
            try:
                api.configure({'enabled':True,'names':['saved'],'headless':True})
                body={'model':'saved','max_tokens':512,'temperature':0.3,
                      'system':'Você é um agente de terminal.',
                      'messages':[{'role':'user','content':[{'type':'text','text':'diga olá'}]}],
                      'tools':tools}
                code,raw,mime=call('/v1/messages',body,{})
                self.assertEqual(code,200,raw)
                value=json.loads(raw)
                self.assertEqual(value['type'],'message')
                self.assertEqual(value['role'],'assistant')
                self.assertEqual(value['stop_reason'],'end_turn')
                self.assertTrue(value['content'][0]['text'])
                self.assertIn('temperature',value['browserapi']['ignored'])
                self.assertEqual(value['browserapi']['tools'],'emulated')
                # Streaming: a sequência de eventos que o SDK Anthropic exige.
                body['stream']=True;body['messages'][0]['content']='outra pergunta'
                code,sse,mime=call('/v1/messages',body,{})
                self.assertEqual(code,200,sse[:200])
                self.assertEqual(mime,'text/event-stream')
                for event in ('message_start','content_block_delta','message_stop'):
                    self.assertIn(event,sse)
                # O worker é único: nada foi enviado em paralelo.
                self.assertEqual(panel.snapshot()['telemetry']['requests'],2)
                destination=REPO_ROOT/'results/ci/anthropic-flow.json'
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_text(json.dumps({'scope':'synthetic_http_api_real_chromium',
                    'route':'/v1/messages','x_api_key':True,'stream_events':True,
                    'tools':'emulated_prompt_only','ignored_params':value['browserapi']['ignored']},indent=2)+'\n')
            finally:
                api.close();panel.close();server.stop()
