#!/usr/bin/env python3
"""Após CI main: patch automático; commit de release por API, sem mover main."""
import base64
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile

from build_release import artifacts, BASE, payload

REPO = 'Financia-Brasil/browserapi-lab'


def gh(*args,data=None):
    command = ['gh',*args]
    if data is None:
        return json.loads(subprocess.check_output(command,text=True))
    return json.loads(subprocess.check_output(command+['--input','-'],input=json.dumps(data),text=True))


def next_version(base,latest):
    current = tuple(map(int,base.split('.')))
    previous = tuple(map(int,latest.removeprefix('v').split('.'))) if latest else (0,0,0)
    return base if current>previous else '.'.join(map(str,(*previous[:2],previous[2]+1)))


def main():
    head = os.environ['GITHUB_SHA']
    release = [r for page in gh('api',f'repos/{REPO}/releases?per_page=100','--paginate','--slurp') for r in page]
    stable = [r for r in release if not r['draft'] and not r['prerelease'] and re.fullmatch(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)',r['tag_name'])]
    # Reexecutar o mesmo source SHA não publica outra versão.
    if any('source: '+head in (r.get('body') or '') for r in stable):
        return
    latest = max((r['tag_name'] for r in stable),default=None,key=lambda tag:tuple(map(int,tag.removeprefix('v').split('.'))))
    target_version = next_version(BASE,latest)
    with tempfile.TemporaryDirectory() as tmp:
        output = artifacts(target_version,tmp)
        entries = []
        files = [(f'downloads/{p.name}',p.read_bytes()) for p in output.iterdir() if p.is_file()]
        files += [(name,payload(name,target_version)) for name in
                  ('browserapi_lab/version.py','browserapi_lab/assets/panel.html','browserapi_lab/assets/panel.js')]
        for name,body in files:
            blob = gh('api',f'repos/{REPO}/git/blobs',data={'encoding':'base64','content':base64.b64encode(body).decode()})
            entries.append({'path':name,'mode':'100644','type':'blob','sha':blob['sha']})
        source = gh('api',f'repos/{REPO}/git/commits/{head}')
        tree = gh('api',f'repos/{REPO}/git/trees',data={'base_tree':source['tree']['sha'],'tree':entries})
        commit = gh('api',f'repos/{REPO}/git/commits',data={'message':f'Release {target_version}\n\nsource: {head}',
            'tree':tree['sha'],'parents':[head]})
        subprocess.run(['gh','release','create','v'+target_version,'--repo',REPO,'--target',commit['sha'],
            '--title','BrowserAPI '+target_version,'--notes',
            f'source: {head}\n\nAtualização automática ABI 1. Artefatos verificados por SHA256; confiança no editor GitHub, sem assinatura independente.',
            *[str(p) for p in output.iterdir() if p.is_file()]],check=True)


if __name__=='__main__':
    main()
