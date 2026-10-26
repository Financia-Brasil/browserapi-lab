import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from browserapi_lab.profiles import inventory, profile_name
from browserapi_lab.existing_chrome import endpoint
from browserapi_lab.config import ChatConfig
from browserapi_lab.chat import config_fingerprint


class TestProfiles(unittest.TestCase):
    def test_inventory_is_metadata_only_and_excludes_guest_symlinks_and_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'google-chrome';root.mkdir()
            for directory in ('Default','Profile 1','Guest Profile','System Profile'):
                (root/directory).mkdir()
            (root/'Profile 2').symlink_to(root/'Default',target_is_directory=True)
            (root/'Local State').write_text(json.dumps({'profile':{'info_cache':{'Default':{
                'name':'Pessoal','user_name':'SECRET_EMAIL','gaia_id':'SECRET_ID'}}}}))
            # Nunca abrir bancos sensíveis: inválidos de propósito.
            (root/'Default/Cookies').mkdir()
            value=inventory(tmp)
            self.assertEqual([p['directory'] for p in value],['Default','Profile 1'])
            self.assertEqual(value[0]['label'],'Pessoal')
            self.assertNotIn('SECRET',json.dumps(value))
            self.assertFalse(value[0]['account_verified'])

    def test_beta_endpoint_and_edge_inventory_without_claiming_support(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('google-chrome-beta','microsoft-edge'):
                root=Path(tmp)/name;root.mkdir();(root/'Default').mkdir()
            (Path(tmp)/'google-chrome-beta/DevToolsActivePort').write_text('9222\n/devtools/browser/abc-123\n')
            rows=inventory(tmp)
            self.assertEqual(len(rows),2)
            self.assertFalse(next(p for p in rows if p['installation']=='edge')['connectable'])
            self.assertEqual(endpoint(tmp,installation='chrome-beta'),'ws://127.0.0.1:9222/devtools/browser/abc-123')

    def test_invalid_local_state_falls_back_and_unsafe_profile_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'google-chrome';root.mkdir();(root/'Default').mkdir()
            (root/'Local State').write_text('{invalid')
            self.assertEqual(inventory(tmp)[0]['label'],'Default')
        for value in ('../Default','Guest Profile','/tmp/secret','Profile 1234567'):
            with self.assertRaises(ValueError):profile_name(value)

    def test_default_config_fingerprint_preserves_existing_receipts(self):
        import hashlib
        from dataclasses import asdict
        config=ChatConfig('saved','https://example.com')
        old=asdict(config);old.pop('personal_installation');old.pop('personal_profile')
        self.assertEqual(config_fingerprint(config),hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest())
        config.personal_profile='Profile 1'
        self.assertNotEqual(config_fingerprint(config),hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest())
