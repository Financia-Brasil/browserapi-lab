#!/usr/bin/env python3
"""Revalida uma captura real e não vazia sem apagar os dados do Farol Beta."""
import argparse,json,re,subprocess,time,urllib.request,xml.etree.ElementTree as ET
from pathlib import Path
import websocket
p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--out',required=True);a=p.parse_args()
out=Path(a.out);out.mkdir(parents=True,exist_ok=True);package='com.ifpa.iassistente.beta'
def adb(*parts,binary=False):
 r=subprocess.run(['adb','-s',a.serial,*parts],capture_output=True,timeout=25,check=True)
 return r.stdout if binary else r.stdout.decode(errors='replace').strip()
def tap(name):
 for _ in range(5):
  adb('shell','uiautomator','dump','/data/local/tmp/farol-privacy.xml')
  root=ET.fromstring(adb('shell','cat','/data/local/tmp/farol-privacy.xml'))
  for n in root.iter('node'):
   if n.get('resource-id')==package+':id/'+name:
    b=list(map(int,re.findall(r'\d+',n.get('bounds',''))))
    if len(b)==4 and b[2]>b[0] and b[3]>b[1]:adb('shell','input','tap',str((b[0]+b[2])//2),str((b[1]+b[3])//2));return
  time.sleep(.5)
 raise AssertionError('Controle ausente: '+name)
adb('shell','am','force-stop',package)
adb('shell','am','start','-W','-n',package+'/com.ifpa.iassistente.MainActivity')
tap('start_practice')
pid=adb('shell','pidof',package).split()[0];adb('forward','tcp:9222','localabstract:webview_devtools_remote_'+pid)
deadline=time.monotonic()+25
while True:
 try:
  pages=json.load(urllib.request.urlopen('http://127.0.0.1:9222/json',timeout=3))
  page=next(p for p in pages if p.get('type')=='page' and p.get('url','').startswith('https://appassets.androidplatform.net/assets/practice.html'))
  w=websocket.create_connection(page['webSocketDebuggerUrl'],suppress_origin=True,timeout=10);break
 except Exception:
  if time.monotonic()>deadline:raise
  time.sleep(.5)
seq=0
def evaluate(expression):
 global seq
 seq+=1;w.send(json.dumps({'id':seq,'method':'Runtime.evaluate','params':{'expression':expression,'returnByValue':True}}))
 while True:
  r=json.loads(w.recv())
  if r.get('id')==seq:
   assert 'exceptionDetails' not in r.get('result',{}),r
   return r['result']['result'].get('value')
try:
 deadline=time.monotonic()+20
 while not evaluate("document.readyState==='complete' && document.querySelector('#begin')!==null"):
  assert time.monotonic()<deadline,'O treino não terminou de carregar'
  time.sleep(.3)
 evaluate("document.querySelector('#begin').click()")
 evaluate("(()=>{const f=document.querySelector('#cpf');f.value='12345678901';f.dispatchEvent(new Event('input',{bubbles:true}));})()")
 assert evaluate("document.querySelector('#cpf').value==='12345678901'")
 script=Path(__file__).parents[1].joinpath('android/app/src/main/assets/capture.js').read_text()
 snapshot=evaluate('if(window.__farol)window.__farol.force=true;\n'+script)
 assert isinstance(snapshot,dict) and snapshot.get('nodes'),'Captura real vazia'
 assert any(n.get('role')=='textbox' and n.get('filled') for n in snapshot['nodes']),'Campo preenchido ausente'
 assert '12345678901' not in json.dumps(snapshot),'CPF presente na captura'
 assert '12345678901' not in adb('shell','run-as',package,'cat','shared_prefs/farol.xml'),'CPF persistido'
 (out/'captura-saneada.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2))
 proof={'status':'pass','captured_nodes':len(snapshot['nodes']),'filled_field_present':True,'typed_value_absent':True,'typed_value_not_persisted':True,'method':'forçar e capturar no mesmo comando JavaScript no WebView real'}
 (out/'privacy-probe.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
 p=out/'device-tests.json';cases=json.loads(p.read_text())
 for case in cases:
  if case['name']=='captura do aparelho exclui valor digitado':case.update(status='pass',detail='Revalidado com captura não vazia; ver captura-saneada.json e privacy-probe.json')
 p.write_text(json.dumps(cases,ensure_ascii=False,indent=2))
 print(json.dumps(proof,ensure_ascii=False),flush=True)
 (out/'20-privacidade-verificada.png').write_bytes(adb('exec-out','screencap','-p',binary=True))
finally:w.close()
tap('home_button')
