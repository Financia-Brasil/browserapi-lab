"""Cliente HTTP → worker único → Chromium real → fixture, sem contas reais."""
import base64
import http.client
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from _harness import BrowserTestCase, FixtureServer, REPO_ROOT
from browserapi_lab.browser import BrowserSession
from browserapi_lab.chat import ChatResult
from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.gui import Panel
from browserapi_lab.llm_api import APIService, WarmBrowser
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
                    self.assertIsNone(value['usage'])
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
                        'idempotency_verified':True,'buffered_sse':True,'image_block_opt_in':True,'usage':None},indent=2)+'\n')
            finally:
                api.close();panel.close();server.stop()
