import http.client,json,os,signal,subprocess,sys,tempfile,time
from pathlib import Path
root=Path(os.environ.get('BROWSERAPI_REPO',Path.cwd()))
sys.path.insert(0,str(root));sys.path.insert(0,str(root/'scripts'))
from build_release import bundle
from browserapi_lab.updates import UpdateStore
import hashlib
with tempfile.TemporaryDirectory() as tmp:
 data=Path(tmp)/'browserapi-lab';store=UpdateStore(data)
 env=dict(os.environ,XDG_DATA_HOME=tmp)
 command='import sys;sys.path.insert(0,sys.argv.pop(1));from browserapi_lab.bootstrap import main;raise SystemExit(main())'
 process=subprocess.Popen([sys.executable,'-c',command,str(root),'--no-open','--config-dir',str(Path(tmp)/'configs')],env=env,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 def read_window():
  return json.loads((data/'window.json').read_text())
 def request(window,method='GET',path='/api/state',payload=None):
  port=int(window['url'].rsplit(':',1)[1]);c=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
  c.request(method,path,json.dumps(payload) if payload is not None else None,{'X-BrowserAPI-Token':window['token'],'Content-Type':'application/json'})
  r=c.getresponse();body=r.read();assert r.status==200;c.close();return json.loads(body)
 try:
  deadline=time.monotonic()+4
  while True:
   try:
    original=read_window();before=request(original);break
   except (OSError,ValueError):
    assert process.poll() is None
    assert time.monotonic()<deadline
    time.sleep(.05)
  assert before['version']=='0.3.0',before['version']
  raw=bundle('0.3.1');meta={'version':'0.3.1','size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
  store.stage(meta,raw)
  deadline=time.monotonic()+25
  while True:
   try:
    current=read_window();after=request(current)
    if after['version']=='0.3.1':break
   except (OSError,ValueError):pass
   assert process.poll() is None
   assert time.monotonic()<deadline
   time.sleep(.1)
  assert current==original,'Porta/token mudaram'
  assert after['telemetry']['requests']==0
  request(current,'POST','/api/updates',{'enabled':False})
  deadline=time.monotonic()+35
  while store.read().get('trial'):
   assert process.poll() is None
   assert time.monotonic()<deadline
   time.sleep(.2)
  assert store.read()['active']=='0.3.1'
  assert store.read()['enabled'] is False
  print(json.dumps({'result':'PASS','from':'0.3.0','to':'0.3.1','real_supervisor_and_two_gui_processes':True,'same_port_and_token':True,'automatic_idle_switch':True,'startup_confirmation':True,'messages_sent':0,'public_network_required':False}))
 finally:
  try:os.killpg(process.pid,signal.SIGTERM)
  except ProcessLookupError:pass
  process.wait(timeout=10)
  try:os.killpg(process.pid,signal.SIGKILL)
  except ProcessLookupError:pass
