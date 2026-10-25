import json
import os
from pathlib import Path
import tempfile
import unittest
from browserapi_lab.config import ChatConfig, ConfigStore, safe_name, safe_url
from browserapi_lab.chat import ChatResult
from browserapi_lab.setup import status


class TestConfig(unittest.TestCase):
    def config(self):
        return ChatConfig('my-chat', 'https://example.com/chat', composer='#input', send='#send',
                          user='.user', assistant='.assistant')

    def test_roundtrip_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(Path(tmp) / 'config')
            config = self.config()
            store.save(config)
            self.assertEqual(store.load(config.name), config)
            self.assertEqual(os.stat(store._path(config.name)).st_mode & 0o777, 0o600)
            store.save_status(config.name, ChatResult('success', True).receipt(config))
            self.assertEqual(store.names(), ['my-chat'])
            self.assertTrue(status(store, config.name)['compatible_in_this_run'])

    def test_changed_config_invalidates_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(tmp)
            config = self.config()
            store.save(config)
            store.save_status(config.name, ChatResult('success', True).receipt(config))
            config.assistant = '.new-assistant'
            store.save(config)
            self.assertEqual(status(store, config.name)['status'], 'configuration_changed')
            self.assertFalse(status(store, config.name)['compatible_in_this_run'])

    def test_not_tested_is_not_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(tmp)
            store.save(self.config())
            self.assertEqual(status(store, 'my-chat')['status'], 'not_tested')

    def test_no_path_traversal(self):
        for value in ('../profile', 'a/b', '/tmp/absolute', '', '.hidden', 'x'*65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_name(value)

    def test_unsafe_urls_rejected(self):
        for value in ('file:///etc/passwd', 'javascript:alert(1)', 'https://u:p@x.com/',
                      'https://x.com/?token=private', 'http://remote.example/',
                      'https://x.com/#token', 'https://x.com:bad', 'https://x.com/has space'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_url(value)
        self.assertEqual(safe_url('http://127.0.0.1:8123/chat'), 'http://127.0.0.1:8123/chat')

    def test_invalid_values(self):
        for key, value in (('browser', 'firefox'), ('timeout_ms', -1), ('stability_ms', True),
                           ('assistant', []), ('schema_version', 2)):
            config = self.config()
            setattr(config, key, value)
            with self.subTest(key=key), self.assertRaises(ValueError):
                config.validate()

    def test_receipt_never_contains_answer(self):
        config = self.config()
        result = ChatResult('success', True, answer='private answer value')
        payload = json.dumps(result.receipt(config))
        self.assertNotIn('private answer value', payload)
        self.assertNotIn(config.url, payload)
        self.assertNotIn(config.composer, payload)

    def test_unknown_schema_or_config_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(tmp)
            store._path('bad').write_text('{"name":"bad","url":"https://x.com","extra":true}')
            with self.assertRaises(ValueError):
                store.load('bad')
