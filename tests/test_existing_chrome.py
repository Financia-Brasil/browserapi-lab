"""Conexão existente: só endpoint local conhecido, com consentimento explícito."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.existing_chrome import endpoint, ExistingChromeError
from browserapi_lab.setup import configure, check


class TestExistingChrome(unittest.TestCase):
    def test_endpoint_is_local_bounded_and_never_http_probed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'google-chrome/DevToolsActivePort'
            path.parent.mkdir()
            for data in ('0\n/devtools/browser/id','65536\n/devtools/browser/id',
                         '9222\nhttps://evil.test','9222\n/devtools/browser/../secret',
                         '9222\n/devtools/browser/id\nextra', 'x'*1025):
                path.write_text(data)
                with self.assertRaises(ExistingChromeError):
                    endpoint(tmp)
            path.write_text('9222\n/devtools/browser/public-fixture-id\n')
            self.assertEqual(endpoint(tmp),'ws://127.0.0.1:9222/devtools/browser/public-fixture-id')
            path.unlink()
            other = Path(tmp)/'other'
            other.write_text('9222\n/devtools/browser/id')
            path.symlink_to(other)
            with self.assertRaises(ExistingChromeError):
                endpoint(tmp)

    def test_existing_mode_requires_chrome_and_defaults_stay_dedicated(self):
        self.assertEqual(ChatConfig('x','https://example.com').session_mode,'dedicated')
        with self.assertRaises(ValueError):
            ChatConfig('x','https://example.com',session_mode='existing_chrome').validate()
        ChatConfig('x','https://example.com',browser='chrome',session_mode='existing_chrome').validate()

    def test_denial_never_opens_or_connects_browser(self):
        config = ChatConfig('x','https://example.com',browser='chrome',session_mode='existing_chrome')
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(tmp)
            store.save(config)
            with patch('browserapi_lab.setup.BrowserSession') as unused:
                factory = lambda _: self.fail('Não conectar sem autorização')
                receipt = configure(store,'x',initial_config=config,ask=lambda _:'n',tell=lambda _:None, session_factory=factory)
                self.assertEqual(receipt['status'],'not_authorized')
                receipt = check(store,'x',ask=lambda _:'n',tell=lambda _:None,session_factory=factory)
                self.assertEqual(receipt['status'],'not_authorized')
                unused.assert_not_called()
