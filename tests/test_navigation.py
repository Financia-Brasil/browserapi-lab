"""Regressões da migração: confirmação explícita e guard de origem preservado."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from browserapi_lab.chat import exchange
from browserapi_lab.config import ChatConfig, ConfigStore, arena_migration, display_origin, PROVIDERS
from browserapi_lab.setup import navigation_receipt


class TestNavigation(unittest.TestCase):
    def config(self):
        return ChatConfig('arena', 'https://lmarena.ai/', provider='lmarena',
                          composer='#input', send='#send', user='.user', assistant='.assistant')

    def test_new_default_is_current_domain(self):
        self.assertEqual(PROVIDERS['lmarena'], 'https://arena.ai/')

    def test_alias_is_narrow_not_wildcard_or_custom(self):
        config = self.config()
        self.assertTrue(arena_migration(config, 'https://arena.ai/c/test'))
        for url in ('https://evil.test', 'https://arena.ai.evil.test', 'https://www.arena.ai',
                    'http://arena.ai', 'https://arena.ai:444', 'https://accounts.google.com'):
            self.assertFalse(arena_migration(config, url), url)
        config.provider = 'custom'
        self.assertFalse(arena_migration(config, 'https://arena.ai/'))

    def test_migration_only_after_confirmation_preserves_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(tmp)
            config = self.config()
            store.save(config)
            page = SimpleNamespace(url='https://arena.ai/c/chosen')
            result = navigation_receipt(page, config, store, lambda _: 'n', lambda _: None)
            self.assertEqual(result['status'], 'wrong_origin')
            self.assertEqual(result['send_state'], 'not_sent')
            self.assertEqual(store.load('arena').url, 'https://lmarena.ai/')
            result = navigation_receipt(page, config, store, lambda _: 's', lambda _: None)
            self.assertIsNone(result)
            self.assertEqual(store.load('arena').url, page.url)
            self.assertEqual(store.load('arena').composer, '#input')

    def test_unrelated_redirect_never_offers_trust_and_leaks_no_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = navigation_receipt(SimpleNamespace(url='https://evil.test/private?token=SECRET'),
                    self.config(), ConfigStore(tmp), lambda _: self.fail('Não pedir confiança genérica'), lambda _: None)
            self.assertEqual(result['diagnostics']['observed_origin'], 'https://evil.test')
            self.assertNotIn('SECRET', str(result))
            self.assertEqual(result['stage'], 'navigation')

    def test_wrong_origin_does_not_call_sender_or_measure_model(self):
        # Mata H3/H4 sem um navegador pessoal: endereço real diverge do salvo.
        page = SimpleNamespace(url='https://arena.ai/')
        with patch('browserapi_lab.chat.google_login_blocked', return_value=False), \
             patch('browserapi_lab.chat.send_message') as sender:
            result = exchange(page, self.config(), authorized=True, health_check=True)
        sender.assert_not_called()
        self.assertEqual(result.status, 'wrong_origin')
        self.assertEqual(result.stage, 'preflight')
        self.assertEqual(result.send_state, 'not_sent')
        self.assertIn('preflight_ms', result.timings)
        self.assertNotIn('response_wait_ms', result.timings)
        self.assertEqual(result.receipt(self.config())['diagnostics']['expected_origin'], 'https://lmarena.ai')

    def test_origin_display_strips_private_components(self):
        self.assertEqual(display_origin('https://name:secret@arena.ai/c/private?q=SECRET#secret'), 'https://arena.ai')
        self.assertEqual(display_origin('chrome://version/'), 'página interna ou endereço inválido')
