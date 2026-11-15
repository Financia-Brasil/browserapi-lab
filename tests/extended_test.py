#!/usr/bin/env python3
"""Testes funcionais no aparelho físico. Somente com.ifpa.iassistente.beta.
Requer adb e websocket-client. Não compila código e não limpa outros apps.
"""
import argparse, json, re, subprocess, time, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
import websocket

parser=argparse.ArgumentParser()
parser.add_argument("--serial",required=True)
parser.add_argument("--out",required=True)
parser.add_argument("--reset",action="store_true",help="Apaga somente os dados do Farol Beta antes da suíte")
args=parser.parse_args()
OUT=Path(args.out);OUT.mkdir(parents=True,exist_ok=True)
PACKAGE="com.ifpa.iassistente.beta"
results=[]
def adb(*parts,timeout=25,binary=False):
    p=subprocess.run(["adb","-s",args.serial,*parts],capture_output=True,timeout=timeout)
    if p.returncode: raise RuntimeError(p.stderr.decode(errors="replace")[:500])
    return p.stdout if binary else p.stdout.decode(errors="replace").strip()
def dump():
    adb("shell","uiautomator","dump","/data/local/tmp/farol-ui.xml")
    return ET.fromstring(adb("shell","cat","/data/local/tmp/farol-ui.xml"))
def node(rid=None,text=None):
    for n in dump().iter("node"):
        resource_id = rid if rid and ":" in rid else PACKAGE+":id/"+str(rid)
        if (rid and n.get("resource-id")==resource_id) or (text and n.get("text", "").casefold()==text.casefold()):
            b=list(map(int,re.findall(r"\d+",n.get("bounds",""))))
            if len(b)==4 and b[2]>b[0] and b[3]>b[1]:return n,b
    return None
def tap(rid=None,text=None,scroll=True):
    for attempt in range(6 if scroll else 1):
        found=node(rid,text)
        if found:
            n,b=found;adb("shell","input","tap",str((b[0]+b[2])//2),str((b[1]+b[3])//2));time.sleep(.5);return
        adb("shell","input","swipe","540","1900","540","700","300");time.sleep(.3)
    raise AssertionError("Controle não encontrado: "+str(rid or text))
def screenshot(name):
    (OUT/(name+".png")).write_bytes(adb("exec-out","screencap","-p",binary=True))
def check(name,fn):
    try:
        detail=fn()
        results.append({"name":name,"status":"pass","detail":detail or ""})
        print("PASS",name,flush=True)
    except Exception as e:
        screenshot("FALHA-"+str(len(results)))
        results.append({"name":name,"status":"fail","detail":str(e)})
        print("FAIL",name,str(e),flush=True)
        raise
    finally:(OUT/"extended-tests.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
def truth(value,message):
    if not value:raise AssertionError(message)
def wait_native(text,timeout=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        root=dump()
        found=any(text.lower() in n.get("text","").lower() for n in root.iter("node"))
        if found:return
        time.sleep(.5)
    raise AssertionError("Texto ausente: "+text)

class CDP:
    def __init__(self):
        pid=adb("shell","pidof",PACKAGE).split()[0]
        adb("forward","tcp:9222","localabstract:webview_devtools_remote_"+pid)
        deadline=time.monotonic()+12
        while True:
            try:
                pages=json.load(urllib.request.urlopen("http://127.0.0.1:9222/json",timeout=3))
                page=next(p for p in pages if p.get("type")=="page")
                self.ws=websocket.create_connection(page["webSocketDebuggerUrl"],timeout=10,suppress_origin=True)
                self.seq=0;return
            except Exception:
                if time.monotonic()>deadline:raise
                time.sleep(.5)
    def eval(self,expression):
        self.seq+=1
        self.ws.send(json.dumps({"id":self.seq,"method":"Runtime.evaluate","params":{"expression":expression,"returnByValue":True,"awaitPromise":True}}))
        while True:
            r=json.loads(self.ws.recv())
            if r.get("id")==self.seq:
                if "exceptionDetails" in r.get("result",{}):raise AssertionError(r)
                return r.get("result",{}).get("result",{}).get("value")
    def close(self):self.ws.close()

def click_dom(selector):
    cdp.eval("document.querySelector("+json.dumps(selector)+").click()")
    time.sleep(1.3)
def fill(value):
    cdp.eval("(()=>{let e=document.querySelector('#cpf');e.value="+json.dumps(value)+";e.dispatchEvent(new Event('input',{bubbles:true}));})()")
    time.sleep(1.2)
def guide():
    n=node("guidance_text");return n[0].get("text","") if n else ""

original_font=adb("shell","settings","get","system","font_scale")
original_rotation=adb("shell","settings","get","system","user_rotation")
original_auto=adb("shell","settings","get","system","accelerometer_rotation")
size_info=adb("shell","wm","size")
original_size=re.search(r"Override size:\s*(\S+)",size_info)
cdp=None
def address_to(url):
    tap(rid="browser_address")
    adb("shell","input","keycombination","113","29")
    adb("shell","input","text",url)
    tap(rid="browser_go")
    time.sleep(.5)
def done():
    if cdp:
        try:cdp.close()
        except Exception:pass
try:
    # Begin from a known screen without clearing the completed functional tests.
    adb("shell","am","force-stop",PACKAGE)
    adb("shell","am","start","-W","-n",PACKAGE+"/com.ifpa.iassistente.MainActivity")
    wait_native("Vamos por partes")
    check("consentimento persiste após reiniciar",lambda:truth(node("onboarding_accept") is None,"Consentimento perdido"))
    tap(rid="open_browser")
    cdp=CDP();time.sleep(5)
    check("navegador real carrega origem HTTPS",lambda:truth(cdp.eval("location.protocol")== "https:","Origem não HTTPS"))
    screenshot("12-portal-real")
    for scheme in ["http://www.gov.br","file:///sdcard/Download","content://settings/system","javascript:noop","https://user:secret@example.com"]:
        address_to(scheme)
        check("endereço bloqueado: "+scheme.split(":")[0]+(" com credenciais" if "user:secret" in scheme else ""),lambda:wait_native("Confira o endereço"))
        tap(rid="android:id/button1")
    address_to("https://farol-offline-check.invalid/")
    check("falha de rede recebe mensagem recuperável",lambda:wait_native("Não foi possível carregar"))
    screenshot("13-falha-rede")
    time.sleep(3)
    check("erro de rede não entra em loop de orientação",lambda:truth("Não foi possível carregar" in guide(),"Mensagem de falha foi substituída por guia incorreto"))
    done();cdp=None
    tap(rid="home_button");tap(rid="start_practice")
    cdp=CDP();time.sleep(1)
    check("treino continua disponível após falha da rede",lambda:truth(cdp.eval("location.hostname")== "appassets.androidplatform.net","Treino indisponível"))
    check("reiniciar navegador não recupera CPF digitado",lambda:truth(cdp.eval("document.querySelector('#cpf').value===''"),"Valor de CPF reapareceu"))
    done();cdp=None
    adb("shell","settings","put","system","accelerometer_rotation","0")
    adb("shell","settings","put","system","user_rotation","1");time.sleep(2)
    cdp=CDP()
    check("rotação mantém o treino aberto",lambda:truth(cdp.eval("location.pathname").endswith("practice.html"),"Rotação perdeu o treino"))
    screenshot("14-paisagem")
    done();cdp=None
    adb("shell","settings","put","system","user_rotation","0");time.sleep(1.5)
    adb("shell","wm","size","891x1987");time.sleep(2)
    cdp=CDP()
    check("375px não cria overflow horizontal no treino",lambda:truth(cdp.eval("document.documentElement.scrollWidth<=innerWidth"),"Overflow horizontal em 375px"))
    screenshot("15-375px")
    done();cdp=None
    adb("shell","settings","put","system","font_scale","2.0");time.sleep(2)
    cdp=CDP()
    check("fonte ampliada preserva formulário sem overflow",lambda:truth(cdp.eval("document.documentElement.scrollWidth<=innerWidth"),"Overflow com fonte ampliada"))
    check("fonte ampliada mantém campo disponível",lambda:truth(cdp.eval("document.querySelector('#cpf')!==null"),"Campo perdido ao ampliar fonte"))
    screenshot("16-fonte-200")
    done();cdp=None
    adb("shell","settings","put","system","font_scale",original_font)
    adb("shell","wm","size",original_size.group(1) if original_size else "reset");time.sleep(2)
    tap(rid="home_button");tap(rid="open_settings")
    tap(rid="settings_voice")
    check("voz pode ser reativada",lambda:truth('name="voice" value="true"' in adb("shell","run-as",PACKAGE,"cat","shared_prefs/farol.xml"),"Voz não reativou"))
    tap(rid="settings_test")
    time.sleep(1)
    tap(rid="settings_delete")
    tap(rid="android:id/button2")
    check("cancelar exclusão preserva consentimento",lambda:truth('name="consent" value="true"' in adb("shell","run-as",PACKAGE,"cat","shared_prefs/farol.xml"),"Cancelar apagou dados"))
    tap(rid="settings_delete");tap(rid="android:id/button1")
    check("revogar volta ao consentimento",lambda:wait_native("Você no comando"))
    prefs=adb("shell","run-as",PACKAGE,"cat","shared_prefs/farol.xml")
    check("revogação remove preferências e fluxos",lambda:truth('name="flows"' not in prefs and 'name="consent"' not in prefs,"Dados sobreviveram à revogação"))
    tap(rid="onboarding_accept");tap(rid="start_practice")
    cdp=CDP();time.sleep(1)
    check("revogação remove etapa do treino",lambda:truth(cdp.eval("!document.querySelector('#intro').hidden"),"Estado do treino não foi apagado"))
    screenshot("17-treino-final")
except Exception as error:
    if not results or results[-1]["status"] != "fail":
        results.append({"name":"execução estendida","status":"fail","detail":str(error)})
    raise
finally:
    done()
    adb("shell","settings","put","system","font_scale",original_font)
    adb("shell","settings","put","system","user_rotation",original_rotation)
    adb("shell","settings","put","system","accelerometer_rotation",original_auto)
    adb("shell","wm","size",original_size.group(1) if original_size else "reset")
    (OUT/"extended-tests.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps({"passed":sum(r["status"]=="pass" for r in results),"failed":sum(r["status"]=="fail" for r in results)},ensure_ascii=False),flush=True)
