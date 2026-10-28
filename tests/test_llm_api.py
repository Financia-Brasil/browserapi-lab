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
from browserapi_lab.llm_api import (APIService, APIError, WarmBrowser, Job,
                                    diagnose_endpoint, endpoint_example)
from browserapi_lab.setup import HYPOTHESES


class FakeWarm:
    calls=0
    prompts=[]
    answer='fixture-answer'
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
        job.result=ChatResult('success',True,answer=type(self).answer,send_state='confirmed')
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
        FakeWarm.answer='fixture-answer'
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
        # CLI de agente manda temperature/max_tokens: aceitar e registrar como
        # ignorado é o que faz o agente funcionar; recusar quebrava a chamada.
        code,value=self.request(body=self.body(temperature=.2,max_tokens=64))
        self.assertEqual(code,200)
        self.assertIn('temperature',value['browserapi']['ignored'])
        self.assertIn('max_tokens',value['browserapi']['ignored'])
        # Campo desconhecido de verdade continua sendo erro, com o nome do campo.
        code,value=self.request(body=self.body(whatever=1))
        self.assertEqual(code,400)
        self.assertIn('whatever',value['error']['message'])
        self.assertEqual(self.service.server.server_address[0],'127.0.0.1')

    def test_root_and_missing_key_explain_what_to_use_instead(self):
        """O relato: `curl` na raiz recebia "not found" e parecia API fora do ar."""
        code,value=self.request('/')
        self.assertEqual(code,404)
        self.assertIn('/v1/models',value['error']['message'])
        connection=http.client.HTTPConnection('127.0.0.1',self.service.server.server_port,timeout=8)
        connection.request('GET','/v1/models')
        response=connection.getresponse();body=json.loads(response.read())
        connection.close()
        self.assertEqual(response.status,401)
        self.assertEqual(body['error']['code'],'missing_api_key')
        self.assertIn('Authorization: Bearer',body['error']['message'])

    def test_probe_tests_the_real_socket_and_explains_when_it_is_off(self):
        result=self.service.probe()
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['port'],self.service.server.server_port)
        self.assertIn('Respondendo em 127.0.0.1',result['message'])
        self.assertIn('saved',result['models'])
        self.service.configure({'enabled':False})
        off=self.service.probe()
        self.assertFalse(off['ok'])
        self.assertIn('API desativada',off['message'])

    def test_json_sse_idempotency_and_private_prompt_not_cached_or_logged(self):
        headers={'Idempotency-Key':'operation-1'}
        code,value=self.request(body=self.body(),headers=headers)
        # usage não é inventado: zeros + explicação de que o site não informa.
        self.assertEqual(code,200)
        self.assertEqual(value['usage']['total_tokens'],0)
        self.assertIn('não informa tokens',value['usage']['browserapi']['note'])
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

    def test_clear_history_right_after_a_response_is_not_rejected_as_busy(self):
        """Regressão: o contador caía só depois de escrever o socket.

        Quem chama "apagar histórico/revogar" imediatamente após uma resposta
        recebia "Aguarde a tarefa"; o trabalho do navegador já havia terminado.
        """
        self.service.configure({'enabled':False})
        self.service.configure({'enabled':True,'names':['saved'],'retrieval':True,'remember':True})
        body = self.body(); body['conversation_id'] = 'session-one'
        self.assertEqual(self.request(body=body)[0], 200)
        self.assertFalse(self.service.busy())
        # Sem espera alguma: o estado precisa refletir o fim da chamada.
        self.service.configure({'enabled':False,'clear_history':True})
        self.assertEqual(self.service.history.stats()['records'], 0)
        self.assertIsNone(self.service.server)

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


class TestLocalAPIPort(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=ConfigStore(Path(self.tmp.name)/'config')
        self.config_=ChatConfig('saved','https://example.com',**HYPOTHESES['fixture'])
        self.store.save(self.config_)
        self.store.save_status('saved',ChatResult('success',True).receipt(self.config_))
        self.panel=Panel(self.store,Path(self.tmp.name)/'data')

    def tearDown(self):
        self.panel.close();self.tmp.cleanup()

    def test_busy_port_says_so_instead_of_failing_silently(self):
        import socket
        holder=socket.socket();holder.bind(('127.0.0.1',0));holder.listen(1)
        try:
            port=holder.getsockname()[1]
            service=APIService(self.panel,port=port);self.panel.api_service=service
            with self.assertRaises(APIError) as caught:
                service.configure({'enabled':True,'names':['saved']})
            self.assertEqual(caught.exception.code,'port_busy')
            self.assertIn('já está em uso',str(caught.exception))
            self.assertFalse(service.snapshot()['enabled'])
            # Nada ficou pela metade: nenhuma política foi gravada como ativa.
            self.assertFalse(service.path.exists() and json.loads(service.path.read_text())['enabled'])
        finally:
            holder.close()
            try: service.close()
            except Exception: pass


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

    def test_personal_chrome_never_matches_same_origin_tab_from_another_profile(self):
        """O Playwright junta abas de todos os perfis; só a sessão verificada escolhe."""
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            store=ConfigStore(tmp)
            store.save(ChatConfig('personal','https://chat.example',browser='chrome',session_mode='existing_chrome',
                                  personal_profile='Profile 1',**HYPOTHESES['fixture']))
            created=[]
            def tab(url):
                return SimpleNamespace(url=url,is_closed=lambda:False,wait_for_load_state=lambda *a,**kw:None)
            class Session:
                def __init__(self,config):
                    self.other_profile=tab('https://chat.example/another-account')
                    self.chosen_profile=tab('https://chat.example/chosen-account')
                    self.context=SimpleNamespace(pages=[self.other_profile])
                    created.append(self)
                def start(self):pass
                def page(self,url):return self.chosen_profile
                def close(self):pass
            job=Job('prompt',['personal'],{'headless':False,'lightweight':False,'fallback':False},{})
            browser=WarmBrowser(store,Session)
            with patch('browserapi_lab.llm_api.exchange',return_value=ChatResult('success',True,answer='ok',send_state='confirmed')) as send:
                browser.run(job,lambda:False)
            self.assertIs(send.call_args.args[0],created[0].chosen_profile)
            self.assertIsNot(send.call_args.args[0],created[0].other_profile)
            browser.close()


class TestEndpointDiagnosis(unittest.TestCase):
    """Três erros de uso com a mesma cara: IP incompleto, rota ausente, porta errada.

    Cada frase precisa dizer o que corrigir — foi o que faltou no relato
    ("Failed to connect to 127.0.0", "Not found", `composer_missing`).
    """

    def test_truncated_ip(self):
        for text in ('http://127.0.0', '127.0.0:8765', '127.0.0'):
            result = diagnose_endpoint(text)
            self.assertFalse(result['ok'], text)
            self.assertIn('127.0.0.1', result['message'])
            self.assertIn('incompleto', result['message'])

    def test_missing_route(self):
        result = diagnose_endpoint('http://127.0.0.1:8765')
        self.assertFalse(result['ok'])
        self.assertIn('/v1/chat/completions', result['message'])
        self.assertIn('Not found', result['message'])
        self.assertFalse(diagnose_endpoint('http://127.0.0.1:8765/v1')['ok'])

    def test_complete_route_passes(self):
        result = diagnose_endpoint('http://127.0.0.1:8765/v1/chat/completions')
        self.assertTrue(result['ok'])
        self.assertIn('POST', result['message'])

    def test_wrong_port_and_host_are_named(self):
        self.assertIn('9999', diagnose_endpoint('http://127.0.0.1:9999/v1/chat/completions')['message'])
        self.assertIn('este computador', diagnose_endpoint('http://example.com/v1/chat/completions')['message'])
        self.assertIn('porta', diagnose_endpoint('http://127.0.0.1')['message'])

    def test_empty_or_garbage_does_not_raise(self):
        self.assertFalse(diagnose_endpoint('')['ok'])
        self.assertFalse(diagnose_endpoint('não é um endereço')['ok'])
        self.assertFalse(diagnose_endpoint(None)['ok'])

    def test_example_keeps_the_key_out_of_the_text(self):
        example = endpoint_example(8765, 'meu-gemini')
        self.assertIn('/v1/chat/completions', example)
        self.assertIn('BROWSERAPI_KEY', example)
        self.assertIn('meu-gemini', example)
        self.assertNotIn('Bearer sk-', example)


class TestAgentProtocols(unittest.TestCase):
    """O que uma CLI precisa: /v1/messages (Anthropic), tools e parâmetros tolerados.

    Relato do uso real: o agente recebeu "Parâmetro não suportado;
    tools/temperature/limites nativos não são simulados" e parou.
    """

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=ConfigStore(Path(self.tmp.name)/'config')
        self.config=ChatConfig('saved','https://example.com',**HYPOTHESES['fixture'])
        self.store.save(self.config)
        self.store.save_status('saved',ChatResult('success',True).receipt(self.config))
        self.panel=Panel(self.store,Path(self.tmp.name)/'data')
        self.patch=patch('browserapi_lab.llm_api.WarmBrowser',FakeWarm);self.patch.start()
        FakeWarm.calls=0;FakeWarm.prompts=[];FakeWarm.block=FakeWarm.entered=None
        FakeWarm.answer='fixture-answer'
        self.service=APIService(self.panel,port=0);self.panel.api_service=self.service
        self.service.configure({'enabled':True,'names':['saved']})
        self.key=self.service.state['key']

    def tearDown(self):
        self.service.close();self.panel.close();self.patch.stop();self.tmp.cleanup()

    def call(self,path,body,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.service.server.server_port,timeout=8)
        values={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'}
        values.update(headers or {})
        connection.request('POST',path,json.dumps(body),values)
        response=connection.getresponse();raw=response.read()
        mime=response.getheader('Content-Type')
        connection.close()
        return response.status,(raw.decode() if mime=='text/event-stream' else json.loads(raw)),response

    def anthropic(self,**extra):
        body={'model':'saved','max_tokens':1024,'temperature':0.2,
              'system':[{'type':'text','text':'Você é um agente de terminal.'}],
              'messages':[{'role':'user','content':[{'type':'text','text':'quais arquivos existem?'}]}]}
        body.update(extra)
        return body

    def test_messages_endpoint_accepts_what_claude_code_sends(self):
        status,value,response=self.call('/v1/messages',self.anthropic())
        self.assertEqual(status,200,value)
        self.assertEqual(value['type'],'message')
        self.assertEqual(value['role'],'assistant')
        self.assertEqual(value['content'][0]['text'],'fixture-answer')
        self.assertEqual(value['stop_reason'],'end_turn')
        self.assertEqual(value['usage']['output_tokens'],0)
        # O que o navegador não tem é dito, não fingido.
        self.assertIn('temperature',value['browserapi']['ignored'])
        self.assertIn('max_tokens',value['browserapi']['ignored'])
        self.assertIn('temperature',response.getheader('X-BrowserAPI-Ignored') or '')
        self.assertEqual(FakeWarm.calls,1)

    def test_x_api_key_header_is_enough_for_anthropic_sdk(self):
        status,value,_=self.call('/v1/messages',self.anthropic(),
                                 headers={'Authorization':'','x-api-key':self.key,
                                          'anthropic-version':'2023-06-01'})
        self.assertEqual(status,200,value)

    def test_tool_call_comes_back_as_tool_use_block(self):
        FakeWarm.answer='```json\n{"tool_calls":[{"name":"Read","arguments":{"path":"a.txt"}}]}\n```'
        tools=[{'name':'Read','description':'lê arquivo',
                'input_schema':{'type':'object','properties':{'path':{'type':'string'}}}}]
        status,value,_=self.call('/v1/messages',self.anthropic(tools=tools))
        self.assertEqual(status,200,value)
        self.assertEqual(value['stop_reason'],'tool_use')
        block=value['content'][0]
        self.assertEqual(block['type'],'tool_use')
        self.assertEqual(block['name'],'Read')
        self.assertEqual(block['input'],{'path':'a.txt'})
        self.assertEqual(value['browserapi']['tools'],'emulated')
        # O protocolo foi para o chat: a lista de ferramentas foi digitada lá.
        self.assertIn('FERRAMENTAS DISPONÍVEIS',FakeWarm.prompts[-1])
        self.assertIn('Read',FakeWarm.prompts[-1])

    def test_tool_result_turn_is_read_back_as_text(self):
        body=self.anthropic(messages=[
            {'role':'user','content':[{'type':'text','text':'liste'}]},
            {'role':'assistant','content':[{'type':'tool_use','id':'toolu_1','name':'Bash',
                                            'input':{'command':'ls'}}]},
            {'role':'user','content':[{'type':'tool_result','tool_use_id':'toolu_1',
                                       'content':[{'type':'text','text':'a.txt'}]}]}])
        status,value,_=self.call('/v1/messages',body)
        self.assertEqual(status,200,value)
        prompt=FakeWarm.prompts[-1]
        self.assertIn('chamada de ferramenta Bash',prompt)
        self.assertIn('resultado da ferramenta',prompt)
        self.assertIn('a.txt',prompt)

    def test_streaming_messages_uses_anthropic_event_names(self):
        FakeWarm.answer='```json\n{"tool_calls":[{"name":"Bash","arguments":{"command":"ls"}}]}\n```'
        tools=[{'name':'Bash','description':'roda comando','input_schema':{'type':'object'}}]
        status,text,_=self.call('/v1/messages',self.anthropic(stream=True,tools=tools))
        self.assertEqual(status,200,text[:200])
        for event in ('message_start','content_block_start','input_json_delta',
                      'content_block_stop','message_delta','message_stop'):
            self.assertIn(event,text)
        self.assertIn('"stop_reason": "tool_use"',text)

    def test_count_tokens_embeddings_and_responses_routes(self):
        status,value,_=self.call('/v1/messages/count_tokens',{'model':'saved','messages':[]})
        self.assertEqual(status,200);self.assertEqual(value['input_tokens'],0)
        self.assertIn('tokens',value['browserapi']['usage'])
        status,value,_=self.call('/v1/embeddings',{'model':'saved','input':'x'})
        self.assertEqual(status,501)
        self.assertEqual(value['error']['code'],'not_supported')
        status,value,_=self.call('/v1/responses',{'model':'saved','input':'oi',
                                                  'max_output_tokens':10})
        self.assertEqual(status,200,value)
        self.assertEqual(value['output'][0]['content'][0]['text'],'fixture-answer')
        self.assertIn('max_output_tokens',value['browserapi']['ignored'])

    def test_unknown_parameter_is_named_and_kept_as_error(self):
        status,value,_=self.call('/v1/messages',self.anthropic(whatever=1))
        self.assertEqual(status,400)
        self.assertIn('whatever',value['error']['message'])
        self.assertEqual(FakeWarm.calls,0)
