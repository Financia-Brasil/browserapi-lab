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
    finally:(OUT/"device-tests.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
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

try:
    if args.reset: adb("shell","pm","clear",PACKAGE)
    adb("shell","am","force-stop",PACKAGE)
    adb("shell","am","start","-W","-n",PACKAGE+"/com.ifpa.iassistente.MainActivity")
    time.sleep(1)
    screenshot("01-consentimento")
    check("primeira abertura pede consentimento",lambda:wait_native("Você no comando"))
    tap(rid="onboarding_refuse")
    check("recusa bloqueia o guia",lambda:wait_native("desativado"))
    tap(text="Rever minha escolha")
    tap(rid="onboarding_accept")
    check("consentimento abre tela inicial",lambda:wait_native("Vamos por partes"))
    screenshot("02-inicio")
    tap(rid="start_practice")
    cdp=CDP();time.sleep(2)
    check("treino carrega offline empacotado",lambda:truth(cdp.eval("location.href").endswith("/assets/practice.html"),"Origem de treino incorreta"))
    check("guia não executa o primeiro clique",lambda:truth(cdp.eval("!document.querySelector('#intro').hidden"),"O app iniciou o treino sozinho"))
    check("destaque não bloqueia toque",lambda:truth(cdp.eval("getComputedStyle(window.__farol.overlay).pointerEvents==='none'"),"Overlay bloqueia toque"))
    screenshot("03-treino-inicio")
    click_dom("#begin")
    check("captura detecta mudança de etapa",lambda:wait_native("campo CPF"))
    screenshot("04-campo")
    fill("12");click_dom("#continue")
    check("erro de preenchimento vira orientação",lambda:wait_native("Confira o campo"))
    screenshot("05-erro-cpf")
    click_dom("#expire")
    check("sessão expirada recebe tradução correta",lambda:wait_native("tempo desta sessão"))
    check("não confunde timeout com conta em outro aparelho",lambda:truth("outro aparelho" not in guide(),"Tradução incorreta"))
    screenshot("06-sessao-expirada")
    click_dom("#try-again")
    fill("12345678901")
    check("campo preenchido avança indicação ao botão",lambda:wait_native("Quando estiver pronto"))
    cdp.eval("window.__farol.force=true")
    script=Path(__file__).parents[1].joinpath("android/app/src/main/assets/capture.js").read_text()
    snapshot=cdp.eval(script)
    (OUT/"captura-saneada.json").write_text(json.dumps(snapshot,ensure_ascii=False,indent=2))
    check("captura do aparelho exclui valor digitado",lambda:truth("12345678901" not in json.dumps(snapshot),"CPF vazou na captura"))
    time.sleep(1.2)
    check("preencher não envia formulário automaticamente",lambda:truth(cdp.eval("!document.querySelector('#form').hidden"),"Formulário avançou sozinho"))
    tap(rid="guidance_pause")
    check("pausa tem estado textual",lambda:wait_native("Guia pausado"))
    check("pausa remove destaque",lambda:truth(cdp.eval("window.__farol.overlay.hidden"),"Destaque continua ativo"))
    tap(rid="guidance_pause")
    check("retomada recupera orientação",lambda:wait_native("Quando estiver pronto"))
    tap(rid="guidance_rephrase")
    check("reformular tem alternativa escrita",lambda:wait_native("Confira o que"))
    click_dom("#continue")
    check("fluxo completo confirma conclusão",lambda:wait_native("Treino concluído"))
    screenshot("07-concluido")
    cdp.close()
    tap(rid="home_button");tap(rid="open_skills")
    check("treino concluído aparece nos fluxos",lambda:wait_native("Treinos concluídos: 1"))
    screenshot("08-meus-fluxos")
    tap(rid="home_button");tap(rid="open_settings")
    check("ajustes de voz disponíveis",lambda:truth(node("settings_speed") is not None,"Controle de velocidade ausente"))
    tap(rid="settings_voice")
    prefs=adb("shell","run-as",PACKAGE,"cat","shared_prefs/farol.xml")
    check("preferência de voz é salva",lambda:truth('name="voice" value="false"' in prefs,"Voz não foi salva"))
    check("persistência não grava CPF de teste",lambda:truth("12345678901" not in prefs,"Dado digitado persistiu"))
    screenshot("09-ajustes")
    tap(rid="home_button");tap(rid="start_practice")
    cdp=CDP();time.sleep(1.5)
    check("treino retoma etapa sem recuperar valores",lambda:truth(cdp.eval("!document.querySelector('#done').hidden && document.querySelector('#cpf').value===''"),"Etapa ou valores recuperados incorretamente"))
    click_dom("#again");click_dom("#begin")
    cdp.close()
    # Keyboard test: use actual Android input, rather than DOM assignment.
    cdp=CDP()
    coords=cdp.eval("(()=>{let r=document.querySelector('#cpf').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:innerWidth};})()")
    native=node("browser_web")[1]
    scale=(native[2]-native[0])/coords["w"]
    adb("shell","input","tap",str(int(native[0]+coords["x"]*scale)),str(int(native[1]+coords["y"]*scale)))
    time.sleep(1)
    adb("shell","input","text","12345678901");time.sleep(1)
    check("teclado real preenche o formulário",lambda:truth(cdp.eval("document.querySelector('#cpf').value==='12345678901'"),"Entrada ADB não preencheu o campo"))
    screenshot("10-teclado")
    adb("shell","input","keyevent","4");time.sleep(.5)
    cdp.close()
    # Confirm persisted privacy after a genuine keyboard input.
    check("teclado não altera valores persistidos do guia",lambda:truth("12345678901" not in adb("shell","run-as",PACKAGE,"cat","shared_prefs/farol.xml"),"Valor do teclado foi salvo"))
    screenshot("11-browser-final")
except Exception as error:
    if not results or results[-1]["status"] != "fail":
        results.append({"name":"execução da suíte","status":"fail","detail":str(error)})
    raise
finally:
    try:cdp.close()
    except Exception:pass
    (OUT/"device-tests.json").write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps({"passed":sum(r["status"]=="pass" for r in results),"failed":sum(r["status"]=="fail" for r in results)},ensure_ascii=False),flush=True)
