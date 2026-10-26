import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.chat import ChatResult
from browserapi_lab.gui import Panel
from browserapi_lab.llm_api import APIService, APIError, WarmBrowser, Job
from browserapi_lab.setup import HYPOTHESES


class FakeWarm:
    calls=0
    prompts=[]
    block=None
    entered=None
    def __init__(self,store):self.store=store
    def close(self):pass
    def run(self,job,cancelled):
        type(self).calls+=1
        type(self).prompts.append(job.prompt)
        if self.entered:self.entered.set()
        if self.block:self.block.wait(5)
        job.config=self.store.load(job.names[0])
        job.result=ChatResult('success',True,answer='fixture-answer',send_state='confirmed')
        job.attempts=[{'model':job.config.name,'status':'success','send_state':'confirmed'}]


class TestLocalAPI(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=ConfigStore(Path(self.tmp.name)/'config')
        self.config=ChatConfig('saved','https://example.com',**HYPOTHESES['fixture'])
        self.store.save(self.config)
        self.store.save_status('saved',ChatResult('success',True).receipt(self.config))
        self.panel=Panel(self.store,Path(self.tmp.name)/'data')
        self.patch=patch('browserapi_lab.llm_api.WarmBrowser',FakeWarm);self.patch.start()
        FakeWarm.calls=0;FakeWarm.prompts=[];FakeWarm.block=FakeWarm.entered=None
        self.service=APIService(self.panel,port=0);self.panel.api_service=self.service
        self.service.configure({'enabled':True,'names':['saved']})
        self.key=self.service.state['key']

    def tearDown(self):
        if FakeWarm.block:FakeWarm.block.set()
        self.service.close();self.panel.close();self.patch.stop();self.tmp.cleanup()

    def request(self,path='/v1/chat/completions',body=None,token=True,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.service.server.server_port,timeout=8)
        values={'Authorization':'Bearer '+(self.key if token else 'wrong'),'Content-Type':'application/json'}
        values.update(headers or {})
        connection.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,values)
        response=connection.getresponse();raw=response.read();mime=response.getheader('Content-Type')
        result=response.status,raw.decode() if mime=='text/event-stream' else json.loads(raw)
        connection.close();return result

    def body(self,**extra):
        return dict(model='saved',messages=[{'role':'user','content':'SECRET private prompt'}],**extra)

    def test_auth_host_origin_models_and_unknown_parameters(self):
        self.assertEqual(self.request('/v1/models',token=False)[0],401)
        self.assertEqual(self.request('/v1/models',headers={'Host':'evil.example'})[0],401)
        self.assertEqual(self.request('/v1/models',headers={'Origin':'https://evil.example'})[0],401)
        code,value=self.request('/v1/models')
        self.assertEqual(code,200);self.assertEqual(value['data'][0]['id'],'saved')
        self.assertEqual(self.request(body=self.body(temperature=.2))[0],400)
        self.assertEqual(FakeWarm.calls,0)
        self.assertEqual(self.service.server.server_address[0],'127.0.0.1')

    def test_json_sse_idempotency_and_private_prompt_not_cached_or_logged(self):
        headers={'Idempotency-Key':'operation-1'}
        code,value=self.request(body=self.body(),headers=headers)
        self.assertEqual(code,200);self.assertIsNone(value['usage'])
        self.assertEqual(value['choices'][0]['message']['content'],'fixture-answer')
        self.assertEqual(self.request(body=self.body(),headers=headers)[1]['id'],value['id'])
        self.assertEqual(FakeWarm.calls,1)
        changed=self.body();changed['messages'][0]['content']='different'
        self.assertEqual(self.request(body=changed,headers=headers)[0],409)
        self.assertEqual(next(iter(self.service.cache.values()))[1].prompt,'')
        self.assertNotIn('SECRET',json.dumps(self.panel.snapshot()['telemetry']))
        self.assertNotIn('SECRET',self.service.path.read_text())
        self.assertNotIn('SECRET',' '.join(self.panel.messages))
        stream_body=self.body(stream=True);stream_body['messages'][0]['content']='another SSE request'
        code,sse=self.request(body=stream_body)
        self.assertEqual(code,200);self.assertIn('chat.completion.chunk',sse)
        self.assertTrue(sse.endswith('data: [DONE]\n\n'))
        self.assertEqual(FakeWarm.calls,2)

    def test_implicit_duplicate_and_restart_ledger_prevent_resending(self):
        first=self.request(body=self.body())
        second=self.request(body=self.body(stream=True))
        self.assertEqual(first[0],200);self.assertEqual(second[0],200)
        self.assertEqual(FakeWarm.calls,1)
        self.assertNotIn('SECRET',self.service.ledger_path.read_text())
        self.service.close()
        self.service=APIService(self.panel,port=0);self.panel.api_service=self.service
        self.assertEqual(self.request(body=self.body())[0],409)
        self.assertEqual(FakeWarm.calls,1)
        # Uma identidade nova, deliberada, permite outra intenção.
        self.assertEqual(self.request(body=self.body(),headers={'Idempotency-Key':'new-intent'})[0],200)
        self.assertEqual(FakeWarm.calls,2)

    def test_persistent_history_requires_opt_in_and_conversation_id(self):
        self.assertFalse(self.service.history.path.exists())
        self.service.configure({'enabled':False})
        self.service.configure({'enabled':True,'names':['saved'],'retrieval':True,'remember':True})
        self.assertEqual(self.request(body=self.body())[0],400)
        body=self.body();body['conversation_id']='session-one'
        body['messages'][0]['content']='história anterior do projeto'
        self.assertEqual(self.request(body=body)[0],200)
        self.assertEqual(self.service.history.stats()['records'],2)
        body['messages'][0]['content']='qual foi o projeto?'
        self.assertEqual(self.request(body=body)[0],200)
        self.assertIn('história anterior do projeto',FakeWarm.prompts[-1])
        self.service.configure({'enabled':False,'clear_history':True})
        self.assertEqual(self.service.history.stats()['records'],0)
        self.assertEqual(len(self.service.cache),0)

    def test_large_persisted_corpus_is_searched_after_another_request(self):
        self.service.configure({'enabled':False})
        self.service.configure({'enabled':True,'names':['saved'],'retrieval':True,'remember':True})
        self.service.history.append('large','arquivo antigo','registrado',[
            'ruido '*1_000_000+' Projeto jabuticaba: orçamento 123 reais.'])
        with self.service.history.lock:
            self.service.history._write(self.service.history._read()+[['large','assistant','noise']]*2100)
        body=self.body();body['conversation_id']='large'
        body['messages'][0]['content']='Qual o orçamento do projeto jabuticaba?'
        code,raw=self.request(body=body)
        self.assertEqual(code,200,raw)
        self.assertIn('123 reais',FakeWarm.prompts[-1])
        self.assertLessEqual(len(FakeWarm.prompts[-1]),24000)

    def test_one_worker_and_busy_rejection_without_second_send(self):
        FakeWarm.entered=threading.Event();FakeWarm.block=threading.Event()
        first=[]
        thread=threading.Thread(target=lambda:first.append(self.request(body=self.body())))
        thread.start();self.assertTrue(FakeWarm.entered.wait(3))
        other=self.body();other['messages'][0]['content']='different job'
        self.assertEqual(self.request(body=other)[0],409)
        with self.assertRaises(ValueError):self.panel.submit({'operation':'doctor'})
        self.assertEqual(FakeWarm.calls,1)
        FakeWarm.block.set();thread.join(5)
        self.assertEqual(first[0][0],200)

    def test_policy_disable_persists_key_and_invalid_alias_not_sent(self):
        body=self.body();body['model']='unauthorized'
        self.assertEqual(self.request(body=body)[0],404)
        self.assertEqual(FakeWarm.calls,0)
        self.service.configure({'enabled':False})
        value=json.loads(self.service.path.read_text())
        self.assertFalse(value['enabled']);self.assertEqual(value['key'],self.key)
        self.assertEqual(self.service.path.stat().st_mode & 0o777,0o600)

    def test_long_context_rejected_by_default_and_retrieval_opt_in(self):
        body=self.body(documents=['SECRET document '*10000])
        self.assertEqual(self.request(body=body)[0],400)
        self.assertEqual(FakeWarm.calls,0)
        self.service.configure({'enabled':False})
        self.service.configure({'enabled':True,'names':['saved'],'retrieval':True})
        code,value=self.request(body=body)
        self.assertEqual(code,200);self.assertTrue(value['browserapi']['context']['reduced'])
        self.assertEqual(FakeWarm.calls,1)


class TestWarmRouting(unittest.TestCase):
    def test_no_fallback_after_unknown_or_confirmed_send_even_timeout_429(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            store=ConfigStore(tmp)
            for name,url in [('one','https://one.example'),('two','https://two.example')]:
                store.save(ChatConfig(name,url,**HYPOTHESES['fixture']))
            class Page:
                url='https://one.example/thread'
                def is_closed(self):return False
                def wait_for_load_state(self,*args,**kwargs):pass
            class Session:
                def __init__(self,config):
                    self.context=SimpleNamespace(pages=[Page()]);self.context.pages[0].url='https://'+('one' if config.profile=='one' else 'two')+'.example/thread'
                def start(self):pass
                def close(self):pass
            for status,state in [('timeout','confirmed'),('rate_limit','confirmed'),('send_unconfirmed','unknown')]:
                browser=WarmBrowser(store,Session)
                job=Job('prompt',['one','two'],{'headless':False,'lightweight':False,'fallback':True},{})
                with patch('browserapi_lab.llm_api.exchange',return_value=ChatResult(status,send_state=state)) as send:
                    browser.run(job,lambda:False)
                self.assertEqual(send.call_count,1)
                self.assertEqual(len(job.attempts),1)
                browser.close()

    def test_pre_send_failure_can_fallback_to_distinct_authorized_origin(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            store=ConfigStore(tmp)
            for name,url in [('one','https://one.example'),('same','https://one.example'),('two','https://two.example')]:
                store.save(ChatConfig(name,url,**HYPOTHESES['fixture']))
            class Session:
                def __init__(self,config):
                    p=SimpleNamespace(url=store.load(config.profile).url,is_closed=lambda:False,wait_for_load_state=lambda *a,**kw:None)
                    self.context=SimpleNamespace(pages=[p])
                def start(self):pass
                def close(self):pass
            job=Job('prompt',['one','same','two'],{'headless':False,'lightweight':False,'fallback':True},{})
            browser=WarmBrowser(store,Session)
            with patch('browserapi_lab.llm_api.exchange',side_effect=[ChatResult('rate_limit'),ChatResult('success',True,answer='ok',send_state='confirmed')]) as send:
                browser.run(job,lambda:False)
            self.assertEqual(send.call_count,2)
            self.assertEqual(job.config.name,'two')
            self.assertEqual([a['model'] for a in job.attempts],['one','two'])
            browser.close()
