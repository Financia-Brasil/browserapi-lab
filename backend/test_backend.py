import copy,json,os,threading,unittest,urllib.error,urllib.request
from unittest.mock import patch
from farol_backend import Budget,Gateway,GatewayError,clean,validate_request,validate_advice,call_openai

def envelope():
 return {'version':1,'application':'com.ifpa.farol.fixture','question':'Como continuo?','nodes':[{'id':1,'role':'textbox','label':'CPF','filled':False},{'id':2,'role':'button','label':'Continuar','filled':False}],'consent':'cloud-v1'}
class SchemaTests(unittest.TestCase):
 def test_valid(self):self.assertEqual(validate_request(envelope())['nodes'][0]['id'],1)
 def test_requires_consent(self):
  d=envelope();d['consent']='none'
  with self.assertRaises(GatewayError):validate_request(d)
 def test_rejects_field_values(self):
  d=envelope();d['nodes'][0]['value']='super-secret'
  with self.assertRaises(GatewayError):validate_request(d)
 def test_rejects_hidden_extra_fields(self):
  d=envelope();d['screenshot']='data:image/png'
  with self.assertRaises(GatewayError):validate_request(d)
 def test_rejects_duplicate_ids(self):
  d=envelope();d['nodes'][1]['id']=1
  with self.assertRaises(GatewayError):validate_request(d)
 def test_rejects_boolean_id(self):
  d=envelope();d['nodes'][0]['id']=True
  with self.assertRaises(GatewayError):validate_request(d)
 def test_rejects_empty_screen_and_question(self):
  d=envelope();d['nodes']=[];d['question']=''
  with self.assertRaises(GatewayError):validate_request(d)
 def test_can_answer_question_without_screen(self):
  d=envelope();d['nodes']=[];self.assertEqual(validate_request(d)['nodes'],[])
 def test_sanitizes_identifiers(self):
  d=envelope();d['nodes'][0]['label']='CPF 123.456.789-01';d['question']='Email ana@example.com, +55 91 99999-1234'
  s=json.dumps(validate_request(d));self.assertNotIn('123.456.789-01',s);self.assertNotIn('ana@example.com',s);self.assertNotIn('99999-1234',s)
 def test_bounded_nodes(self):
  d=envelope();d['nodes']=d['nodes']*31
  with self.assertRaises(GatewayError):validate_request(d)
 def test_rejects_invented_target(self):
  with self.assertRaises(GatewayError):validate_advice({'instruction':'Toque no campo.','detail':'Um passo de cada vez.','target_id':99},envelope()['nodes'])
 def test_refuses_empty_provider_output(self):
  with self.assertRaises(GatewayError):validate_advice(None,envelope()['nodes'])
 def test_null_target_allowed(self):self.assertIsNone(validate_advice({'instruction':'Preciso de mais contexto.','detail':'Diga qual ajuda quer.','target_id':None},[])['target_id'])
 def test_missing_key_does_not_fake_ai(self):
  with patch.dict(os.environ,{'OPENAI_API_KEY':''}):
   with self.assertRaises(GatewayError) as e:call_openai(envelope())
   self.assertEqual(e.exception.code,'openai_not_configured')
 def test_daily_limit(self):
  b=Budget(daily=1);b.take()
  with self.assertRaises(GatewayError):b.take()
class HttpTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.calls=[];cls.token='test-token-'+'x'*24
  def provider(d):
   cls.calls.append(d);return {'instruction':'Toque no campo CPF.','detail':'Você preenche no seu ritmo.','target_id':1,'provider':'test','model':'fake','usage':{}}
  cls.server=Gateway(('127.0.0.1',0),cls.token,provider);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.url='http://127.0.0.1:'+str(cls.server.server_port)
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()
 def request(self,data,token=None,path='/v1/assist'):
  req=urllib.request.Request(self.url+path,data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+(token or self.token),'Content-Type':'application/json'})
  try:
   with urllib.request.urlopen(req,timeout=3) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:
   with e:return e.code,json.load(e)
 def test_unauthorized_never_calls_provider(self):
  count=len(self.calls);status,_=self.request(envelope(),'wrong');self.assertEqual(status,401);self.assertEqual(len(self.calls),count)
 def test_unsafe_payload_never_calls_provider(self):
  d=envelope();d['nodes'][0]['value']='12345678901';count=len(self.calls);self.assertEqual(self.request(d)[0],400);self.assertEqual(len(self.calls),count)
 def test_schema_to_provider_is_sanitized(self):
  d=envelope();d['question']='ana@example.com';status,result=self.request(d);self.assertEqual(status,200);self.assertEqual(result['provider'],'test');self.assertNotIn('ana@example.com',json.dumps(self.calls[-1]))
 def test_metrics_do_not_contain_context(self):
  self.request(envelope());data=json.dumps(self.server.metrics);self.assertNotIn('CPF',data);self.assertNotIn('Como continuo?',data);self.assertNotIn(self.token,data)
 def test_unknown_route(self):self.assertEqual(self.request(envelope(),path='/other')[0],404)
if __name__=='__main__':unittest.main(verbosity=2)
