#!/usr/bin/env python3
"""Artefatos ABI 1 determinísticos e manifesto (hash não é assinatura)."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import runpy
import zipfile

from build_deb import build

ROOT = Path(__file__).resolve().parents[1]
BASE = runpy.run_path(str(ROOT/'browserapi_lab/version.py'))['APP_VERSION']


def payload(name,version):
    body = (ROOT/name).read_bytes()
    if name in ('browserapi_lab/version.py','browserapi_lab/assets/panel.html','browserapi_lab/assets/panel.js'):
        body = body.replace(BASE.encode(),version.encode())
    return body


def bundle(version):
    memory = io.BytesIO()
    files = list((ROOT/'browserapi_lab').glob('*.py'))+[p for p in (ROOT/'browserapi_lab/assets').iterdir() if p.suffix in ('.html','.js','.css')]
    with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            name = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(name,(2020,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info,payload(name,version))
    return memory.getvalue()


def artifacts(version,directory):
    import sys
    sys.path.insert(0,str(ROOT))
    from browserapi_lab.updates import version as validate, UpdateStore
    import tempfile
    validate(version)
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    raw = bundle(version)
    manifest = {'schema':1,'abi':1,'version':version,'python_min':[3,11],'playwright':'1.64.1',
                'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    with tempfile.TemporaryDirectory() as tmp:
        UpdateStore(tmp).stage(manifest,raw)
    (directory/'BrowserAPI-runtime.zip').write_bytes(raw)
    (directory/'update.json').write_text(json.dumps(manifest,indent=2)+'\n')
    build(directory/'BrowserAPI-Ubuntu.deb',version=version)
    (directory/'SHA256SUMS').write_text(''.join(hashlib.sha256((directory/name).read_bytes()).hexdigest()+'  '+name+'\n'
        for name in ('BrowserAPI-Ubuntu.deb','BrowserAPI-runtime.zip','update.json')))
    return directory


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version',default=BASE)
    parser.add_argument('--output',default='downloads')
    args = parser.parse_args()
    artifacts(args.version,args.output)
