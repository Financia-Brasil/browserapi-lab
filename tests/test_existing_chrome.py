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

class TestSimplifiedConnection(unittest.TestCase):
    def test_missing_chat_opens_once_in_existing_context_without_touching_other_tabs(self):
        from unittest.mock import Mock
        from browserapi_lab.browser import BrowserSession, BrowserConfig
        session = BrowserSession(BrowserConfig(attach_existing_chrome=True))
        unrelated = Mock(url='https://unrelated.example/')
        context = Mock(pages=[unrelated])
        session._context = context
        page = session.page('https://example.com/chat')
        context.new_page.assert_called_once_with()
        page.goto.assert_called_once_with('https://example.com/chat',wait_until='domcontentloaded')
        unrelated.goto.assert_not_called()

    def test_ambiguous_chat_does_not_open_or_choose_another_tab(self):
        from unittest.mock import Mock
        from browserapi_lab.browser import BrowserSession, BrowserConfig
        session = BrowserSession(BrowserConfig(attach_existing_chrome=True))
        session._context = Mock(pages=[Mock(url='https://example.com/a'),Mock(url='https://example.com/b')])
        with self.assertRaises(ExistingChromeError):
            session.page('https://example.com/chat')
        session._context.new_page.assert_not_called()

    def test_navigation_failure_is_not_retried_with_another_tab(self):
        from unittest.mock import Mock
        from browserapi_lab.browser import BrowserSession, BrowserConfig
        session = BrowserSession(BrowserConfig(attach_existing_chrome=True))
        session._context = Mock(pages=[])
        session._context.new_page.return_value.goto.side_effect = RuntimeError('navigation refused')
        with self.assertRaises(RuntimeError):
            session.page('https://example.com/chat')
        session._context.new_page.assert_called_once_with()

    def test_first_connection_opens_permission_for_selected_profile_only_after_consent(self):
        from browserapi_lab.setup import authorize_session
        config = ChatConfig('x','https://example.com',browser='chrome',session_mode='existing_chrome',personal_profile='Profile 1')
        profile = dict(id='selected',installation='chrome',directory='Profile 1',connectable=True)
        questions=[]
        def ask(text):
            questions.append(text)
            return 's' if len(questions)==1 else ''
        with patch('browserapi_lab.existing_chrome.endpoint',side_effect=[ExistingChromeError('missing'), 'ws://local']), patch('browserapi_lab.profiles.inventory',return_value=[profile]), patch('browserapi_lab.profiles.open_profile') as native:
            self.assertTrue(authorize_session(config,ask,lambda _:None))
            native.assert_called_once_with('selected','chrome://inspect/#remote-debugging')
            self.assertEqual(len(questions),2)

class TestProfileIdentity(unittest.TestCase):
    def probe(self, actual):
        from unittest.mock import Mock
        page = Mock(url='chrome://version/')
        page.locator.return_value.inner_text.return_value = actual
        context = Mock()
        context.new_page.return_value = page
        return context, page

    def test_verified_directory_not_profile_label(self):
        from browserapi_lab.existing_chrome import verify_profile
        context, page = self.probe('/fixtures/google-chrome/Profile 1')
        verify_profile(context, Path('/fixtures/google-chrome/Profile 1'))
        page.close.assert_called_once_with()
        page.locator.assert_called_once_with('#profile_path')
        context.close.assert_not_called()

    def test_two_choices_cannot_silently_bind_to_same_profile(self):
        from browserapi_lab.existing_chrome import verify_profile, ProfileMismatchError
        context, page = self.probe('/fixtures/google-chrome/Default')
        verify_profile(context, '/fixtures/google-chrome/Default')
        with self.assertRaises(ProfileMismatchError):
            verify_profile(context, '/fixtures/google-chrome/Profile 1')
        self.assertEqual(page.close.call_count, 2)
        context.close.assert_not_called()

    def test_unreadable_or_non_native_page_fails_closed_and_closes_only_probe(self):
        from browserapi_lab.existing_chrome import verify_profile
        for actual in ('', 'Default', '/fixtures/another-install/Default'):
            context, page = self.probe(actual)
            with self.assertRaises(ExistingChromeError):
                verify_profile(context, '/fixtures/google-chrome/Default')
            page.close.assert_called_once_with()
        context, page = self.probe('/fixtures/google-chrome/Default')
        page.url = 'https://spoof.example/'
        with self.assertRaises(ExistingChromeError):
            verify_profile(context, '/fixtures/google-chrome/Default')
        page.locator.assert_not_called()

    def test_selected_profile_reaches_browser_config(self):
        from browserapi_lab.chat import browser_config
        with tempfile.TemporaryDirectory() as tmp:
            config = ChatConfig('x', 'https://example.com', browser='chrome',
                                session_mode='existing_chrome', personal_profile='Profile 1')
            self.assertEqual(browser_config(config, Path(tmp)).existing_profile, 'Profile 1')
