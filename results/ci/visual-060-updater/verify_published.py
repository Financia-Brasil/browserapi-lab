"""Verify public 0.6.0 payloads against tested source; run from repo root."""
import datetime
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

root=Path.cwd()
sys.path.insert(0,str(root));sys.path.insert(0,str(root/'scripts'))
from browserapi_lab.updates import candidate,content,github
from build_release import bundle

manifest,commit=candidate()
assert manifest['version']=='0.6.0'
release=github('/releases/latest')
assert release['tag_name']=='v0.6.0'
files={name:content(github,'downloads/'+name,commit) for name in
       ('BrowserAPI-Ubuntu.deb','BrowserAPI-runtime.zip','update.json','SHA256SUMS')}
hashes={name:hashlib.sha256(body).hexdigest() for name,body in files.items()}
for line in files['SHA256SUMS'].decode().splitlines():
    expected,name=line.split();assert hashes[name]==expected
assert len(release['assets'])==4
for asset in release['assets']:
    assert asset['digest']=='sha256:'+hashes[asset['name']]
    assert asset['size']==len(files[asset['name']])
raw=files['BrowserAPI-runtime.zip']
assert len(raw)==manifest['size'] and hashes['BrowserAPI-runtime.zip']==manifest['sha256']
assert raw==bundle('0.6.0')
with tempfile.TemporaryDirectory() as tmp:
    deb=Path(tmp)/'app.deb';deb.write_bytes(files['BrowserAPI-Ubuntu.deb'])
    assert subprocess.check_output(['dpkg-deb','-f',str(deb),'Version'],text=True).strip()=='0.6.0'
    extracted=Path(tmp)/'extracted'
    subprocess.run(['dpkg-deb','-x',str(deb),str(extracted)],check=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names=archive.namelist()
        for name in names:
            assert (extracted/'usr/share/browserapi-lab'/name).read_bytes()==archive.read(name),name
for name,body in files.items():
    (root/'downloads'/name).write_bytes(body)
proof={'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'release':release['html_url'],'release_commit':commit,'version':'0.6.0',
       'hashes':hashes,'runtime_matches_tested_source':True,
       'deb_runtime_payloads_match':len(names),'github_asset_digests_match':True,
       'method':'Pinned GitHub repository contents + SHA256SUMS + GitHub asset digests; publisher trust, not independent signature or personal account/desktop test.'}
(root/'results/ci/visual-060-updater/published.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))
