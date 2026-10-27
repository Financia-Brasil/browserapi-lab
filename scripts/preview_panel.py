"""Prévia visual isolada: nenhum acesso a Chrome/perfis reais ou API de agentes."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from browserapi_lab.gui import Panel,ASSETS
from browserapi_lab.config import ConfigStore
import tempfile
_temp=tempfile.TemporaryDirectory()
panel=Panel(ConfigStore(Path(_temp.name)/'config'),Path(_temp.name)/'data')
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,data,mime='application/json',status=200):
        raw=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/api/state':return self.send(panel.snapshot())
        if path=='/api/profiles':return self.send({'profiles':[{'id':'chrome:Default','label':'Perfil de exemplo','directory':'Default','installation':'chrome','connectable':True,'openable':False,'endpoint_available':False,'account_verified':False}]})
        if path in ('/inter.ttf','/mono.ttf'):
            from browserapi_lab.font_assets import content
            return self.send(content('inter' if path=='/inter.ttf' else 'mono'),'font/ttf')
        names={'/':'panel.html','/panel.js':'panel.js','/panel.css':'panel.css'}
        if path in names:
            raw=(ASSETS/names[path]).read_bytes()
            if path=='/':raw=raw.replace(b'<body>',b'<body><p class="preview-banner">Previa visual: nao acessa seu Chrome ou computador.</p>')
            if path=='/panel.css':raw+=b'.preview-banner{position:sticky;top:0;z-index:10;margin:0;padding:8px 16px;background:#1b3029;color:#fff;text-align:center;font-size:12px}.sidebar{top:32px}'
            return self.send(raw,'text/html; charset=utf-8' if path=='/' else 'text/javascript' if path.endswith('.js') else 'text/css')
        return self.send({'error':'Não encontrado'},status=404)
    def do_POST(self):return self.send({'error':'Esta é uma prévia visual. Abrir perfis e conectar só funciona no aplicativo instalado no seu computador.'},status=400)
if __name__=='__main__':
    try:ThreadingHTTPServer(('0.0.0.0',3000),Handler).serve_forever()
    finally:panel.close();_temp.cleanup()
