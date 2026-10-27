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

def fake_playwright():
    """Módulo mínimo: o núcleo é testado sem instalar navegador."""
    import sys
    import types
    package = types.ModuleType('playwright')
    api = types.ModuleType('playwright.sync_api')

    class TimeoutError(Exception):
        pass
    api.TimeoutError = TimeoutError
    package.sync_api = api
    return patch.dict(sys.modules, {'playwright': package, 'playwright.sync_api': api})


def identities(table):
    return patch('browserapi_lab.existing_chrome.target_context_id',
                 side_effect=lambda context, page: table[page])


class TestSimplifiedConnection(unittest.TestCase):
    def session(self, pages=(), profile='Default'):
        from unittest.mock import Mock
        from browserapi_lab.browser import BrowserSession, BrowserConfig
        session = BrowserSession(BrowserConfig(attach_existing_chrome=True, existing_profile=profile))
        session._profile_context_id = 'chosen'
        session._context = Mock(pages=list(pages))
        return session

    def test_missing_chat_opens_natively_in_chosen_profile_without_touching_other_tabs(self):
        from unittest.mock import Mock
        unrelated = Mock(url='https://unrelated.example/')
        session = self.session([unrelated], profile='Profile 1')
        new = Mock(url='https://example.com/chat')
        with fake_playwright(), identities({new: 'chosen'}), patch(
                'browserapi_lab.profiles.open_profile',
                side_effect=lambda identifier, target: session._context.pages.append(new)) as native:
            page = session.page('https://example.com/chat')
        native.assert_called_once_with('chrome:Profile 1', 'https://example.com/chat')
        self.assertIs(page, new)
        self.assertEqual(page._browserapi_verified_profile, 'Profile 1')
        # createTarget abre no perfil usado por último, não no escolhido.
        session._context.new_page.assert_not_called()
        unrelated.goto.assert_not_called()
        unrelated.close.assert_not_called()

    def test_same_site_tab_from_another_profile_is_not_reused(self):
        from unittest.mock import Mock
        wrong = Mock(url='https://example.com/chat')
        new = Mock(url='https://example.com/chat')
        session = self.session([wrong])
        with fake_playwright(), identities({wrong: 'other', new: 'chosen'}), patch(
                'browserapi_lab.profiles.open_profile',
                side_effect=lambda identifier, target: session._context.pages.append(new)) as native:
            result = session.page('https://example.com/chat')
        self.assertIs(result, new)
        native.assert_called_once()
        wrong.goto.assert_not_called()
        wrong.close.assert_not_called()

    def test_existing_chat_in_chosen_profile_is_reused_without_opening_anything(self):
        from unittest.mock import Mock
        mine = Mock(url='https://example.com/thread')
        theirs = Mock(url='https://example.com/other-thread')
        session = self.session([theirs, mine])
        with identities({mine: 'chosen', theirs: 'other'}), patch('browserapi_lab.profiles.open_profile') as native:
            self.assertIs(session.page('https://example.com/chat'), mine)
        native.assert_not_called()
        session._context.new_page.assert_not_called()

    def test_ambiguous_chat_in_chosen_profile_does_not_open_or_choose_another_tab(self):
        from unittest.mock import Mock
        first, second = Mock(url='https://example.com/a'), Mock(url='https://example.com/b')
        session = self.session([first, second])
        with identities({first: 'chosen', second: 'chosen'}), patch('browserapi_lab.profiles.open_profile') as native:
            with self.assertRaises(ExistingChromeError):
                session.page('https://example.com/chat')
        native.assert_not_called()
        session._context.new_page.assert_not_called()

    def test_native_open_that_lands_elsewhere_is_never_used_or_retried(self):
        import itertools
        from unittest.mock import Mock
        elsewhere = Mock(url='https://example.com/chat')
        session = self.session([])
        with fake_playwright(), identities({elsewhere: 'other'}), patch(
                'browserapi_lab.profiles.open_profile',
                side_effect=lambda identifier, target: session._context.pages.append(elsewhere)) as native, patch(
                'browserapi_lab.browser.time.monotonic', side_effect=itertools.count(0, 10)):
            with self.assertRaises(ExistingChromeError):
                session.page('https://example.com/chat')
        native.assert_called_once()
        elsewhere.goto.assert_not_called()
        elsewhere.close.assert_not_called()
        session._context.new_page.assert_not_called()

    def test_two_new_tabs_in_chosen_profile_are_ambiguous_and_left_open(self):
        from unittest.mock import Mock
        one, two = Mock(url='https://example.com/chat'), Mock(url='https://example.com/chat')
        session = self.session([])
        with fake_playwright(), identities({one: 'chosen', two: 'chosen'}), patch(
                'browserapi_lab.profiles.open_profile',
                side_effect=lambda identifier, target: session._context.pages.extend([one, two])):
            with self.assertRaises(ExistingChromeError):
                session.page('https://example.com/chat')
        one.close.assert_not_called()
        two.close.assert_not_called()

    def test_native_refusal_is_not_retried_with_another_tab(self):
        session = self.session([])
        with patch('browserapi_lab.profiles.open_profile', side_effect=ValueError('Chrome recusou')) as native:
            with self.assertRaises(ValueError):
                session.page('https://example.com/chat')
        native.assert_called_once()
        session._context.new_page.assert_not_called()

    def test_explicit_new_tab_in_other_profile_never_navigates(self):
        from unittest.mock import Mock
        session = self.session([])
        context = session._context
        with patch('browserapi_lab.existing_chrome.target_context_id', return_value='other'):
            with self.assertRaises(ExistingChromeError):
                session.new_page('https://example.com/chat')
        context.new_page.return_value.goto.assert_not_called()
        context.new_page.return_value.close.assert_called_once_with()


    def proof_tab(self):
        from unittest.mock import Mock
        proof = Mock(url='chrome://version/')
        proof.is_closed.return_value = False
        return proof

    def test_proof_tab_becomes_the_chat_tab_without_a_second_native_open(self):
        proof = self.proof_tab()
        session = self.session([proof], profile='Profile 1')
        session._proof_page = proof
        with identities({}), patch('browserapi_lab.profiles.open_profile') as native:
            page = session.page('https://example.com/chat')
        self.assertIs(page, proof)
        proof.goto.assert_called_once_with('https://example.com/chat', wait_until='domcontentloaded')
        native.assert_not_called()
        proof.close.assert_not_called()
        self.assertEqual(page._browserapi_verified_profile, 'Profile 1')
        self.assertIsNone(session._proof_page)

    def test_existing_chat_in_the_profile_wins_and_the_proof_tab_is_released(self):
        from unittest.mock import Mock
        proof = self.proof_tab()
        mine = Mock(url='https://example.com/thread')
        session = self.session([proof, mine])
        session._proof_page = proof
        with identities({mine: 'chosen'}), patch('browserapi_lab.profiles.open_profile') as native:
            self.assertIs(session.page('https://example.com/chat'), mine)
        proof.close.assert_called_once_with()
        proof.goto.assert_not_called()
        native.assert_not_called()
        self.assertIsNone(session._proof_page)

    def test_failed_navigation_keeps_the_proof_tab_registered_for_cleanup(self):
        proof = self.proof_tab()
        proof.goto.side_effect = RuntimeError('navegação recusada')
        session = self.session([proof])
        session._proof_page = proof
        with self.assertRaises(RuntimeError):
            session.page('https://example.com/chat')
        self.assertIs(session._proof_page, proof)
        session._release_proof()
        proof.close.assert_called_once_with()
        self.assertIsNone(session._proof_page)

    def test_close_releases_an_unused_proof_tab(self):
        proof = self.proof_tab()
        session = self.session([proof])
        session._proof_page = proof
        session.close()
        proof.close.assert_called_once_with()


class TestAttachedStart(unittest.TestCase):
    def prepare(self, profile='Profile 1'):
        from unittest.mock import Mock
        from browserapi_lab.browser import BrowserSession, BrowserConfig
        session = BrowserSession(BrowserConfig(attach_existing_chrome=True, existing_profile=profile))
        context = Mock(pages=[])
        session._pw = Mock()
        session._pw.chromium.connect_over_cdp.return_value = Mock(contexts=[context])
        return session, context

    def test_missing_consent_endpoint_has_no_side_effect_on_personal_chrome(self):
        session, context = self.prepare()
        with patch('browserapi_lab.existing_chrome.endpoint', side_effect=ExistingChromeError('sem consentimento')), \
                patch('browserapi_lab.profiles.open_profile') as native:
            with self.assertRaises(ExistingChromeError):
                session._start_attached(0)
        session._pw.chromium.connect_over_cdp.assert_not_called()
        native.assert_not_called()

    def test_profile_is_required_and_other_contexts_stop_before_opening_tabs(self):
        from unittest.mock import Mock
        session, context = self.prepare(profile='')
        with self.assertRaises(ExistingChromeError):
            session._start_attached(0)
        session, context = self.prepare()
        session._pw.chromium.connect_over_cdp.return_value = Mock(contexts=[context, Mock(pages=[])])
        with patch('browserapi_lab.existing_chrome.endpoint', return_value='ws://127.0.0.1:1/devtools/browser/x'), \
                patch('browserapi_lab.profiles.open_profile') as native:
            with self.assertRaises(ExistingChromeError):
                session._start_attached(0)
        native.assert_not_called()

    def test_connect_then_native_proof_then_verify_then_release(self):
        import time
        from unittest.mock import Mock
        calls = []
        session, context = self.prepare('Profile 1')
        proof = Mock()

        def native_open(identifier, target):
            calls.append(('open', identifier, target))
            proof.url = target   # a aba só aparece depois de um evento de página
        context.wait_for_event.side_effect = lambda *args, **kwargs: context.pages.append(proof)

        def connect(address, timeout):
            calls.append(('connect', address))
            return session._pw.chromium.connect_over_cdp.return_value
        session._pw.chromium.connect_over_cdp.side_effect = connect
        session._pw.chromium.connect_over_cdp.return_value = Mock(contexts=[context])

        def verify(ctx, expected, probe=None, keep_probe=False):
            calls.append(('verify', str(expected), probe, keep_probe))
            return 'context-profile-1'
        with fake_playwright(), patch('browserapi_lab.existing_chrome.endpoint', return_value='ws://127.0.0.1:1/devtools/browser/x'), \
                patch('browserapi_lab.profiles.installation_root', return_value=Path('/fixtures/google-chrome')), \
                patch('browserapi_lab.profiles.open_profile', side_effect=native_open), \
                patch('browserapi_lab.existing_chrome.verify_profile', side_effect=verify):
            session._start_attached(time.perf_counter())
        self.assertEqual([call[0] for call in calls], ['connect', 'open', 'verify'])
        self.assertEqual(calls[1][1], 'chrome:Profile 1')
        # Só http(s) chega ao Chrome por linha de comando; chrome:// seria descartado.
        self.assertRegex(calls[1][2], r'^http://127\.0\.0\.1:\d+/browserapi-proof-[0-9a-f]{32}$')
        self.assertEqual(calls[2][1], '/fixtures/google-chrome/Profile 1')
        self.assertIs(calls[2][2], proof)
        # A aba de prova fica aberta (vira a aba do chat); fechar a única janela do perfil o derruba.
        self.assertTrue(calls[2][3])
        self.assertIs(session._proof_page, proof)
        context.wait_for_event.assert_called_with('page', timeout=250)
        self.assertEqual(session._profile_context_id, 'context-profile-1')
        self.assertIs(session._context, context)

    def test_proof_tab_never_appears_fails_closed_before_any_chat(self):
        import itertools
        session, context = self.prepare()
        with fake_playwright(), patch('browserapi_lab.existing_chrome.endpoint', return_value='ws://127.0.0.1:1/devtools/browser/x'), \
                patch('browserapi_lab.profiles.installation_root', return_value=Path('/fixtures/google-chrome')), \
                patch('browserapi_lab.profiles.open_profile') as native, \
                patch('browserapi_lab.existing_chrome.verify_profile') as verify, \
                patch('browserapi_lab.browser.time.monotonic', side_effect=itertools.count(0, 10)):
            with self.assertRaises(ExistingChromeError):
                session._start_attached(0)
        native.assert_called_once()
        verify.assert_not_called()
        self.assertIsNone(session._context)
        self.assertIsNone(session._profile_context_id)


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
    def test_failed_profile_proof_leaves_no_identity_and_no_registered_tab(self):
        from unittest.mock import Mock
        from browserapi_lab.existing_chrome import ProfileMismatchError
        session, context = self.prepare()
        proof = Mock()
        context.pages.append(proof)

        def native_open(identifier, target):
            proof.url = target
        with fake_playwright(), patch('browserapi_lab.existing_chrome.endpoint', return_value='ws://127.0.0.1:1/devtools/browser/x'), \
                patch('browserapi_lab.profiles.installation_root', return_value=Path('/fixtures/google-chrome')), \
                patch('browserapi_lab.profiles.open_profile', side_effect=native_open), \
                patch('browserapi_lab.existing_chrome.verify_profile', side_effect=ProfileMismatchError('outro perfil')):
            with self.assertRaises(ProfileMismatchError):
                session._start_attached(0)
        self.assertIsNone(session._profile_context_id)
        self.assertIsNone(session._proof_page)
        self.assertIsNone(session._context)


class TestProfileIdentity(unittest.TestCase):
    def probe(self, actual):
        from unittest.mock import Mock
        page = Mock(url='chrome://version/')
        page.locator.return_value.inner_text.return_value = actual
        context = Mock()
        context.new_page.return_value = page
        context.new_cdp_session.return_value.send.return_value = {'targetInfo':{'browserContextId':'verified-fixture'}}
        return context, page

    def test_verified_directory_not_profile_label(self):
        from browserapi_lab.existing_chrome import verify_profile
        context, page = self.probe('/fixtures/google-chrome/Profile 1')
        identity = verify_profile(context, Path('/fixtures/google-chrome/Profile 1'))
        # Sem este valor nenhuma aba do chat pode ser ligada ao perfil confirmado.
        self.assertEqual(identity, 'verified-fixture')
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

    def test_different_data_dir_is_not_reported_as_an_account_switch(self):
        from browserapi_lab.existing_chrome import verify_profile, ProfileMismatchError
        context, page = self.probe('/fixtures/another-install/Default')
        with self.assertRaisesRegex(ProfileMismatchError, 'outra pasta de dados'):
            verify_profile(context, '/fixtures/google-chrome/Default')
        context, page = self.probe('/fixtures/google-chrome/Default')
        with self.assertRaisesRegex(ProfileMismatchError, 'outro perfil'):
            verify_profile(context, '/fixtures/google-chrome/Profile 1')

    def test_selected_profile_reaches_browser_config(self):
        from browserapi_lab.chat import browser_config
        with tempfile.TemporaryDirectory() as tmp:
            config = ChatConfig('x', 'https://example.com', browser='chrome',
                                session_mode='existing_chrome', personal_profile='Profile 1')
            self.assertEqual(browser_config(config, Path(tmp)).existing_profile, 'Profile 1')


class TestProofPage(unittest.TestCase):
    def fetch(self, url):
        import urllib.request
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.headers, response.read().decode()

    def test_serves_a_harmless_page_on_loopback_only_and_stops_afterwards(self):
        import urllib.error
        from browserapi_lab.existing_chrome import ProofPage
        with ProofPage() as page:
            self.assertRegex(page.url, r'^http://127\.0\.0\.1:\d+/browserapi-proof-[0-9a-f]{32}$')
            self.assertEqual(page._server.server_address[0], '127.0.0.1')
            status, headers, body = self.fetch(page.url)
            self.assertEqual(status, 200)
            self.assertIn('no-store', headers['Cache-Control'])
            self.assertNotIn('<script', body.lower())
        with self.assertRaises((urllib.error.URLError, ConnectionError)):
            self.fetch(page.url)

    def test_each_proof_has_its_own_nonce(self):
        from browserapi_lab.existing_chrome import ProofPage
        with ProofPage() as first, ProofPage() as second:
            self.assertNotEqual(first.url.rsplit('/', 1)[1], second.url.rsplit('/', 1)[1])

    def test_proof_url_is_accepted_by_the_native_open_policy_and_chrome_urls_are_not(self):
        from browserapi_lab.config import safe_url
        from browserapi_lab.existing_chrome import ProofPage
        with ProofPage() as page:
            self.assertEqual(safe_url(page.url), page.url)
        for rejected in ('chrome://version/#browserapi-' + '0' * 32, 'about:blank#x', 'data:text/html,x'):
            with self.assertRaises(ValueError):
                safe_url(rejected)


class TestProofNavigation(unittest.TestCase):
    def test_provided_probe_is_navigated_by_cdp_because_chrome_drops_chrome_urls_from_launches(self):
        from unittest.mock import Mock
        from browserapi_lab.existing_chrome import verify_profile
        page = Mock(url='chrome://version/')
        page.locator.return_value.inner_text.return_value = '/fixtures/google-chrome/Default'
        context = Mock()
        context.new_cdp_session.return_value.send.return_value = {'targetInfo': {'browserContextId': 'identity'}}
        self.assertEqual(verify_profile(context, '/fixtures/google-chrome/Default', probe=page), 'identity')
        page.goto.assert_called_once()
        self.assertEqual(page.goto.call_args.args[0], 'chrome://version/')
        context.new_page.assert_not_called()   # usa a aba pedida, não cria outra
        page.close.assert_called_once_with()

    def test_keep_probe_stays_open_only_when_the_proof_succeeds(self):
        from unittest.mock import Mock
        from browserapi_lab.existing_chrome import verify_profile, ProfileMismatchError

        def probe(path):
            page = Mock(url='chrome://version/')
            page.locator.return_value.inner_text.return_value = path
            context = Mock()
            context.new_cdp_session.return_value.send.return_value = {'targetInfo': {'browserContextId': 'identity'}}
            return context, page
        context, page = probe('/fixtures/google-chrome/Default')
        verify_profile(context, '/fixtures/google-chrome/Default', probe=page, keep_probe=True)
        page.close.assert_not_called()
        context, page = probe('/fixtures/google-chrome/Default')
        with self.assertRaises(ProfileMismatchError):
            verify_profile(context, '/fixtures/google-chrome/Profile 1', probe=page, keep_probe=True)
        page.close.assert_called_once_with()
