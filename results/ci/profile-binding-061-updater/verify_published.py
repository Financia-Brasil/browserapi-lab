"""Verifica os artefatos PÚBLICOS da 0.6.1 contra o código testado; rodar na raiz do repositório.

Não grava nada em downloads/: a pasta do código é histórica; o instalador vigente é o asset da release.
"""
import datetime
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

root = Path.cwd()
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'scripts'))
from browserapi_lab.updates import candidate, content, github
from build_release import bundle

VERSION = '0.6.1'
manifest, commit = candidate()
assert manifest['version'] == VERSION, manifest['version']
release = github('/releases/latest')
assert release['tag_name'] == 'v' + VERSION, release['tag_name']
names = ('BrowserAPI-Ubuntu.deb', 'BrowserAPI-runtime.zip', 'update.json', 'SHA256SUMS')
files = {name: content(github, 'downloads/' + name, commit) for name in names}
hashes = {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}
for line in files['SHA256SUMS'].decode().splitlines():
    expected, name = line.split()
    assert hashes[name] == expected, name
assert len(release['assets']) == 4, [a['name'] for a in release['assets']]
for asset in release['assets']:
    assert asset['digest'] == 'sha256:' + hashes[asset['name']], asset['name']
    assert asset['size'] == len(files[asset['name']]), asset['name']
raw = files['BrowserAPI-runtime.zip']
assert len(raw) == manifest['size'] and hashes['BrowserAPI-runtime.zip'] == manifest['sha256']
assert raw == bundle(VERSION), 'o runtime publicado não é o construído do código testado'
with tempfile.TemporaryDirectory() as tmp:
    deb = Path(tmp) / 'app.deb'
    deb.write_bytes(files['BrowserAPI-Ubuntu.deb'])
    assert subprocess.check_output(['dpkg-deb', '-f', str(deb), 'Version'], text=True).strip() == VERSION
    extracted = Path(tmp) / 'extracted'
    subprocess.run(['dpkg-deb', '-x', str(deb), str(extracted)], check=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.namelist()
        for name in entries:
            assert (extracted / 'usr/share/browserapi-lab' / name).read_bytes() == archive.read(name), name
proof = {
    'verified_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'release': release['html_url'],
    'installer': 'https://github.com/Financia-Brasil/browserapi-lab/releases/download/v%s/BrowserAPI-Ubuntu.deb' % VERSION,
    'release_commit': commit, 'version': VERSION, 'hashes': hashes,
    'runtime_matches_tested_source': True,
    'deb_runtime_payloads_match': len(entries),
    'github_asset_digests_match': True,
    'method': 'Conteúdo do repositório fixado no commit da release + SHA256SUMS + digests dos assets do GitHub; '
              'confiança no editor, não assinatura independente nem teste no seu desktop.'}
(root / 'results/ci/profile-binding-061-updater/published.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof, indent=2))
