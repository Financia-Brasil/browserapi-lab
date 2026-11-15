"""Ferramentas ADB para o painel; nenhuma chave de provedor é lida ou exibida."""
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = "com.ifpa.iassistente.beta"
FIXTURE = "com.ifpa.farol.fixture"


class Device:
    def __init__(self, serial, out):
        self.serial, self.out = serial, Path(out)
        self.out.mkdir(parents=True, exist_ok=True)

    def adb(self, *args, binary=False, timeout=30):
        p = subprocess.run(["adb", "-s", self.serial, *args], capture_output=True, timeout=timeout)
        if p.returncode:
            raise RuntimeError(p.stderr.decode(errors="replace")[:300])
        return p.stdout if binary else p.stdout.decode(errors="replace").strip()

    def dump(self):
        self.adb("shell", "uiautomator", "dump", "/data/local/tmp/farol-assistant-ui.xml")
        return ET.fromstring(self.adb("shell", "cat", "/data/local/tmp/farol-assistant-ui.xml"))

    def node(self, rid=None, text=None):
        for n in self.dump().iter("node"):
            if (rid and n.get("resource-id") == rid) or (text and n.get("text", "").casefold() == text.casefold()):
                b = list(map(int, re.findall(r"\d+", n.get("bounds", ""))))
                if len(b) == 4 and b[2] > b[0] and b[3] > b[1]:
                    return n, b

    def tap(self, rid=None, text=None, scroll=False):
        for _ in range(5 if scroll else 1):
            found = self.node(rid, text)
            if found:
                _, b = found
                self.adb("shell", "input", "tap", str((b[0]+b[2])//2), str((b[1]+b[3])//2))
                time.sleep(.5)
                return
            if scroll:
                size = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", self.adb("shell", "wm", "size"))[-1]
                w, h = map(int, size)
                self.adb("shell", "input", "swipe", str(w//2), str(int(h*.82)), str(w//2), str(int(h*.48)), "300")
        raise AssertionError("Controle ausente: " + str(rid or text))

    def shot(self, name):
        (self.out/(name+".png")).write_bytes(self.adb("exec-out", "screencap", "-p", binary=True))

    def private(self, name):
        if name not in {"last-assist-snapshot.json", "last-ai-result.json"}:
            raise ValueError("Somente evidências saneadas")
        return json.loads(self.adb("shell", "run-as", PACKAGE, "cat", "files/"+name))

    def invoke(self, method="key"):
        if method == "key":
            self.adb("shell", "input", "keyevent", "219")
        else:
            self.adb("shell", "cmd", "voiceinteraction", "show")
        time.sleep(1.5)

    def hide(self):
        self.adb("shell", "cmd", "voiceinteraction", "hide")

    def fixture(self, secure=False):
        self.hide()
        self.adb("shell", "am", "force-stop", FIXTURE)
        self.adb("shell", "am", "start", "-W", "-n", FIXTURE+"/.FixtureActivity", "--ez", "secure", str(secure).lower())
        time.sleep(.6)

    def texts(self):
        return "\n".join(n.get("text", "") for n in self.dump().iter("node"))

    def wait_text(self, text, timeout=35):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            if text.casefold() in self.texts().casefold():
                return
            time.sleep(.5)
        raise AssertionError("Estado ausente: "+text)
