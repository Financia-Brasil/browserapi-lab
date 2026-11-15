#!/usr/bin/env python3
"""Repete controles nativos do treino offline; não navega em sites reais."""
import argparse, json, random, re, subprocess, time, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
import websocket

p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--out',required=True);args=p.parse_args()
out=Path(args.out);out.mkdir(parents=True,exist_ok=True);package='com.ifpa.iassistente.beta'
def adb(*parts,binary=False):
 r=subprocess.run(['adb','-s',args.serial,*parts],capture_output=True,timeout=25,check=True)
 return r.stdout if binary else r.stdout.decode(errors='replace').strip()
def ui():
 adb('shell','uiautomator','dump','/data/local/tmp/farol-stress.xml')
 return ET.fromstring(adb('shell','cat','/data/local/tmp/farol-stress.xml'))
def find(root,name):
 n=next(n for n in root.iter('node') if n.get('resource-id')==package+':id/'+name)
 bounds=list(map(int,re.findall(r'\d+',n.get('bounds'))));assert bounds[2]>bounds[0] and bounds[3]>bounds[1]
 return n,((bounds[0]+bounds[2])//2,(bounds[1]+bounds[3])//2)
def value(expression):
 pid=adb('shell','pidof',package).split()[0]
 adb('forward','tcp:9222','localabstract:webview_devtools_remote_'+pid)
 pages=json.load(urllib.request.urlopen('http://127.0.0.1:9222/json',timeout=5))
 target=next(p for p in pages if p.get('type')=='page')
 w=websocket.create_connection(target['webSocketDebuggerUrl'],suppress_origin=True,timeout=10)
 try:
  w.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':expression,'returnByValue':True}}))
  while True:
   r=json.loads(w.recv())
   if r.get('id')==1:return r['result']['result'].get('value')
 finally:w.close()

results=[];events=[];started=time.time()
try:
 assert value("location.hostname==='appassets.androidplatform.net' && !document.querySelector('#intro').hidden"), 'Comece na primeira tela do treino offline'
 root=ui();points={name:find(root,name)[1] for name in ['guidance_explain','guidance_repeat','guidance_pause']}
 original_pid=adb('shell','pidof',package)
 (out/'memoria-antes.txt').write_text(adb('shell','dumpsys','meminfo',package))
 rng=random.Random(20261115)
 for index in range(100):
  name=rng.choice(list(points));x,y=points[name]
  adb('shell','input','tap',str(x),str(y));events.append(name);time.sleep(.05)
  if (index+1)%25==0:print('ACOES',index+1,flush=True)
 time.sleep(1)
 assert adb('shell','pidof',package)==original_pid,'O processo do app reiniciou'
 results.append({'name':'processo estável após 100 toques nos controles do guia','status':'pass'})
 assert value("location.hostname==='appassets.androidplatform.net' && !document.querySelector('#intro').hidden"),'Controles do guia avançaram o formulário'
 results.append({'name':'repetição dos controles não executa o formulário','status':'pass'})
 root=ui();find(root,'guidance_pause');find(root,'guidance_explain')
 results.append({'name':'controles continuam acessíveis após repetição','status':'pass'})
 (out/'memoria-depois.txt').write_text(adb('shell','dumpsys','meminfo',package))
 (out/'stress-final.png').write_bytes(adb('exec-out','screencap','-p',binary=True))
except Exception as e:
 results.append({'name':'repetição dos controles','status':'fail','detail':str(e)})
 raise
finally:
 (out/'stress-tests.json').write_text(json.dumps({'seed':20261115,'event_count':len(events),'duration_seconds':round(time.time()-started,2),'events':events,'results':results},ensure_ascii=False,indent=2))
 print(json.dumps({'passed':sum(r['status']=='pass' for r in results),'failed':sum(r['status']=='fail' for r in results),'events':len(events)}),flush=True)
