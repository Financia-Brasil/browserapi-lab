"""Metas de produto testadas contra chat controlado, não sites autenticados."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _harness import BrowserTestCase
from browserapi_lab.chat import exchange, preflight
from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.setup import HYPOTHESES, configure, repair_fields, status, pick


class TestChatWorkflow(BrowserTestCase):
    def prepare(self, mode='contract'):
        config = ChatConfig('test-chat', self.server.url(), provider='fixture',
                            timeout_ms=4000, stability_ms=400, **HYPOTHESES['fixture'])
        self.page.goto(config.url, wait_until='load')
        self.page.evaluate('mode => FakeChat.config({mode, delay:1})', mode)
        return config

    def test_native_profile_proof_reads_real_chromium_and_rejects_other_directory(self):
        from browserapi_lab.existing_chrome import verify_profile, ProfileMismatchError
        # O headless shell padrão não tem WebUI. Testar o Chromium COMPLETO,
        # como o Chrome pessoal, sem reutilizar credenciais ou outro Playwright.
        with tempfile.TemporaryDirectory() as tmp:
            context = self.session._pw.chromium.launch_persistent_context(
                tmp, headless=True, executable_path=self.session._pw.chromium.executable_path)
            try:
                before = list(context.pages)
                verify_profile(context, Path(tmp) / 'Default')
                self.assertEqual(list(context.pages), before)
                with self.assertRaises(ProfileMismatchError):
                    verify_profile(context, Path(tmp) / 'Profile 1')
                self.assertEqual(list(context.pages), before)
                self.assertFalse(before[0].is_closed())
            finally:
                context.close()  # só o Chromium descartável criado neste teste

    def test_removing_origin_guard_allows_send_to_wrong_destination_counterexample(self):
        # Contraprova de H4, SOMENTE fixture local. Nunca uma conta pessoal.
        config = self.prepare()
        config.url = 'https://unrelated.example/'
        blocked = exchange(self.page, config, authorized=True, health_check=True)
        self.assertEqual(blocked.status, 'wrong_origin')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)
        with patch('browserapi_lab.chat.preflight', return_value=None):
            unsafe = exchange(self.page, config, authorized=True, health_check=True)
        self.assertEqual(unsafe.status, 'success')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 1)

    def test_authorized_health_contract(self):
        config = self.prepare()
        result = exchange(self.page, config, authorized=True, health_check=True)
        self.assertEqual(result.status, 'success')
        self.assertTrue(result.compatible)
        self.assertEqual(result.send_state,'confirmed')
        self.assertEqual(result.answer, 'browserapi-ok')
        self.assertIsNotNone(result.timings['ttft_dom_ms'])
        self.assertLess(result.timings['capture_overhead_ms'], 2500)
        stages = ('preflight_ms','send_pipeline_ms','response_wait_ms','parse_ms')
        self.assertTrue(all(result.timings[key] >= 0 for key in stages))
        self.assertLessEqual(sum(result.timings[key] for key in stages),result.timings['total_ms']+.01)
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'),1)

    def test_failure_is_timed_without_sending_or_inventing_later_stages(self):
        config = self.prepare()
        self.page.locator('#composer').fill('rascunho privado')
        result = exchange(self.page,config,authorized=True,health_check=True)
        self.assertEqual(result.status,'draft_present')
        self.assertEqual(result.send_state,'not_sent')
        self.assertGreater(result.timings['total_ms'],0)
        self.assertIn('preflight_ms',result.timings)
        self.assertNotIn('response_wait_ms',result.timings)
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'),0)


    def test_send_hidden_until_composer_input(self):
        config = self.prepare()
        self.page.evaluate("""() => {
            const button = document.querySelector('#send');
            button.style.display = 'none';
            document.querySelector('#composer').addEventListener('input', () => {
                button.style.display = '';
            });
        }""")
        result = exchange(self.page, config, authorized=True, health_check=True)
        self.assertEqual(result.status, 'success')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 1)

    def test_send_absent_until_composer_input(self):
        config = self.prepare()
        self.page.evaluate("""() => {
            const button = document.querySelector('#send');
            button.remove();
            document.querySelector('#composer').addEventListener('input', () => {
                document.querySelector('#composer-host').append(button);
            });
        }""")
        self.assertIsNone(preflight(self.page, config))
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'success')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 1)

    def test_site_que_reescreve_o_texto_ainda_confirma_o_envio(self):
        """Relato real: a mensagem foi enviada, mas o painel disse "sem confirmação".

        O fixture aqui imita chats reais que normalizam o balão da pessoa
        (espaços/NBSP) e demoram alguns milissegundos para pintá-lo.
        """
        config = self.prepare()
        self.page.evaluate("""() => {
            const conversation = document.querySelector('#conversation');
            new MutationObserver(() => {
                for (const node of conversation.querySelectorAll('.message[data-role="user"] .body')) {
                    if (node.dataset.balNormalized) continue;
                    node.dataset.balNormalized = '1';
                    node.textContent = node.textContent.replace(/\\s+/g, '\u00a0') + '\u200b';
                }
            }).observe(conversation, {childList: true, subtree: true});
        }""")
        result = exchange(self.page, config, authorized=True, health_check=True)
        self.assertEqual(result.status, 'success', result.diagnostics)
        self.assertEqual(result.send_state, 'confirmed')
        self.assertEqual(result.answer, 'browserapi-ok')
        self.assertIn('texto esperado', result.diagnostics.get('send_evidence', ''))

    def test_texto_divergente_sem_campo_esvaziado_nao_vira_sucesso(self):
        """Contraprova: reescrever o balão sem que o site consuma o rascunho."""
        config = self.prepare()
        self.page.evaluate("""() => {
            const conversation = document.querySelector('#conversation');
            new MutationObserver(() => {
                for (const node of conversation.querySelectorAll('.message[data-role="user"] .body')) {
                    if (node.dataset.balChanged) continue;
                    node.dataset.balChanged = '1';
                    node.textContent = 'conteúdo completamente diferente';
                }
            }).observe(conversation, {childList: true, subtree: true});
            // Mantém um texto no campo para o sinal de esvaziamento não valer.
            const composer = document.querySelector('#composer');
            setInterval(() => {
                if (!composer.value) {
                    composer.value = 'rascunho que permanece';
                    composer.dispatchEvent(new Event('input', {bubbles: true}));
                }
            }, 30);
        }""")
        result = exchange(self.page, config, authorized=True, health_check=True)
        self.assertNotEqual(result.status, 'success')
        self.assertEqual(result.send_state, 'unknown')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 1)

    def test_ambiguous_send_after_fill_never_clicks_or_retries(self):
        config = self.prepare()
        config.timeout_ms = 500
        self.page.evaluate("""() => {
            document.querySelector('#composer').addEventListener('input', () => {
                if (document.querySelectorAll('#send').length === 1)
                    document.querySelector('#composer-host').append(document.querySelector('#send').cloneNode(true));
            });
        }""")
        result=exchange(self.page, config, authorized=True, health_check=True)
        self.assertEqual(result.status,'send_missing')
        self.assertEqual(result.send_state,'unknown')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)
        self.assertTrue(self.page.locator('#composer').input_value())
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'draft_present')

    def test_google_refusal_stops_before_pointing_or_sending(self):
        config = self.prepare()
        self.page.route('https://accounts.google.com/**', lambda route: route.fulfill(
            content_type='text/html; charset=utf-8', body='<meta charset="utf-8"><p>Esse navegador ou app pode não ser seguro.</p>'))
        try:
            self.page.goto('https://accounts.google.com/fixture')
            self.assertEqual(self.page.locator('p').inner_text(), 'Esse navegador ou app pode não ser seguro.')
            self.assertEqual(preflight(self.page, config), 'google_login_blocked')
            page = self.page
            class BlockedSession:
                def page(self, _url):
                    return page
            @contextmanager
            def factory(_config):
                yield BlockedSession()
            with tempfile.TemporaryDirectory() as root, patch('browserapi_lab.setup.repair_fields') as repair:
                receipt = configure(ConfigStore(root), config.name, initial_config=config,
                                    session_factory=factory, ask=lambda _: '', tell=lambda _:None)
                self.assertEqual(receipt['status'], 'google_login_blocked')
                repair.assert_not_called()
        finally:
            self.page.unroute('https://accounts.google.com/**')

    def test_google_refusal_english_no_send(self):
        config = self.prepare()
        self.page.route('https://accounts.google.com/**', lambda route: route.fulfill(
            content_type='text/html; charset=utf-8',
            body='<p>This browser or app may not be secure.</p>'))
        try:
            self.page.goto('https://accounts.google.com/fixture')
            self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status,
                             'google_login_blocked')
        finally:
            self.page.unroute('https://accounts.google.com/**')

    def test_microphone_is_never_activated(self):
        config = self.prepare()
        self.page.locator('#send').evaluate("el => el.setAttribute('aria-label', 'Microfone')")
        result = exchange(self.page, config, authorized=True, health_check=True)
        self.assertEqual(result.status, 'send_is_microphone')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)

    def test_same_button_changes_from_microphone_to_send(self):
        config = self.prepare()
        self.page.evaluate("""() => {
            const button = document.querySelector('#send');
            button.setAttribute('aria-label', 'Microfone');
            document.querySelector('#composer').addEventListener('input', () => {
                button.setAttribute('aria-label', 'Enviar mensagem');
            });
        }""")
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'success')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 1)

    def test_preview_draft_cleanup_preserves_changes_and_never_sends(self):
        for case in ('normal', 'existing', 'changed', 'cancelled', 'denied'):
            with self.subTest(case=case):
                config = self.prepare()
                if case == 'existing':
                    self.page.locator('#composer').fill('rascunho pessoal')
                replies = iter(['n','s','n' if case == 'denied' else 's','n','n'])
                def selecting(page, role):
                    self.assertEqual(role, 'botão Enviar')
                    value = page.locator('#composer').input_value()
                    if case in ('normal','changed','cancelled'):
                        self.assertIn('rascunho temporário', value)
                    if case == 'existing':
                        self.assertEqual(value, 'rascunho pessoal')
                    if case == 'denied':
                        self.assertEqual(value, '')
                    if case == 'changed':
                        page.locator('#composer').fill('edição pessoal')
                    if case == 'cancelled':
                        raise EOFError()
                    return '#send'
                try:
                    repair_fields(self.page, config, ask=lambda _:next(replies),tell=lambda _:None,
                                  picker=selecting,draft_preview=True)
                    self.assertNotEqual(case,'cancelled')
                except EOFError:
                    self.assertEqual(case,'cancelled')
                expected = {'existing':'rascunho pessoal','changed':'edição pessoal'}.get(case,'')
                self.assertEqual(self.page.locator('#composer').input_value(), expected)
                self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)

    def test_real_picker_rejects_voice_then_selects_send(self):
        self.prepare()
        self.page.evaluate("""() => {
            const button = document.querySelector('#send');
            button.setAttribute('aria-label', 'Microfone');
            const timer = setInterval(() => {
                if (!window.__balVoiceControl || window.__balPick !== null) return;
                clearInterval(timer);
                button.click();
                window.__voiceRejected = window.__balPick === null;
                button.setAttribute('aria-label', 'Enviar mensagem');
                button.click(); document.querySelector('[data-picker-confirm]').click();
            }, 100);
        }""")
        self.assertEqual(pick(self.page, 'botão Enviar'), '#send')
        self.assertTrue(self.page.evaluate('window.__voiceRejected'))
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'),0)

    @contextmanager
    def personal_chrome(self):
        """Chrome descartável que imita o navegador pessoal. Nunca usa perfil real.

        O pedido NATIVO de perfil não é emulado por segundo processo: o Chromium
        descartável sem janela respondeu SHUTDOWN ao hand-off (LOCK_ERROR, CI
        40519568084), o que não é o comportamento de um Chrome com janela. Aqui o
        pedido é emulado por CDP; o hand-off real é exercitado, contra o Google
        Chrome instalado, por scripts/native_open_probe.py.
        """
        import subprocess
        import time
        from types import SimpleNamespace
        from browserapi_lab.existing_chrome import endpoint
        binary = self.session._pw.chromium.executable_path
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            profile = home / 'google-chrome'
            log = home / 'fixture-chrome.log'
            with log.open('wb') as stderr:
                process = subprocess.Popen([binary, '--headless=new', '--no-sandbox', '--remote-debugging-port=0',
                    '--user-data-dir=' + str(profile), 'about:blank'], stdout=subprocess.DEVNULL, stderr=stderr)
            try:
                deadline = time.monotonic() + 30
                while not (profile / 'DevToolsActivePort').exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise AssertionError('Chrome descartável não expôs a porta (código %s): %s' % (
                            process.poll(), log.read_text(errors='replace')[-800:]))
                    self.page.wait_for_timeout(100)
                yield SimpleNamespace(home=home, profile=profile, address=endpoint(home), process=process)
            finally:
                # Somente o Chromium descartável criado acima pertence ao teste.
                # SIGTERM só no pai podia deixar filhos escrevendo em Default
                # durante TemporaryDirectory.cleanup (ENOTEMPTY no CI).
                # Isso NÃO faz parte de BrowserSession nem fecha Chrome pessoal.
                try:
                    cleanup = self.session._pw.chromium.connect_over_cdp(endpoint(home))
                    cleanup.new_browser_cdp_session().send('Browser.close')
                except Exception:
                    process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    @contextmanager
    def attached_to(self, personal, holder):
        """Pedido nativo emulado por CDP na própria conexão da sessão testada."""
        def opener(identifier, target):
            cdp = holder['session']._attached_browser.new_browser_cdp_session()
            try:
                cdp.send('Target.createTarget', {'url': target})
            finally:
                cdp.detach()
            holder.setdefault('opened', []).append((identifier, target))
        with patch('browserapi_lab.existing_chrome.endpoint', return_value=personal.address), \
                patch('browserapi_lab.profiles.installation_root', return_value=personal.profile), \
                patch('browserapi_lab.profiles.open_profile', side_effect=opener):
            yield

    def in_worker(self, function, timeout=90):
        # A API síncrona do Playwright não roda dentro do loop desta thread.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as worker:
            return worker.submit(function).result(timeout=timeout)

    def test_connect_existing_browser_does_not_close_or_reload_it(self):
        from browserapi_lab.browser import BrowserConfig, BrowserSession
        with self.personal_chrome() as personal:
            config = BrowserConfig(profile='connection', profiles_root=personal.home / 'app',
                                   attach_existing_chrome=True, existing_profile='Default')
            holder = {}

            def exercise_connection():
                with self.attached_to(personal, holder):
                    session = holder['session'] = BrowserSession(config)
                    with session as attached:
                        count = len(attached.context.pages)
                        page = attached.page(self.server.url())
                        # A aba de prova virou a aba do chat: nenhuma aba a mais.
                        self.assertEqual(len(attached.context.pages), count)
                        self.assertTrue(page.url.startswith(self.server.url()))
                        self.assertEqual(page._browserapi_verified_profile, 'Default')
                        self.assertIs(attached.page(self.server.url()), page)
                        self.assertEqual(len(attached.context.pages), count)
                        page.evaluate("window.__fixtureSession = 'still-here'")
                        other = attached.context.new_page()
                        other.goto('data:text/html,unrelated-fixture')
                    self.assertIsNone(personal.process.poll(), 'Desconectar não deve fechar navegador pessoal')
                    session = holder['session'] = BrowserSession(config)
                    with session as attached:
                        page = attached.page(self.server.url())
                        self.assertEqual(page.evaluate('window.__fixtureSession'), 'still-here')
                        self.assertTrue(any(p.url.startswith('data:') for p in attached.context.pages))
                        duplicate = attached.new_page(self.server.url())
                        with self.assertRaises(RuntimeError):
                            attached.page(self.server.url())
                        duplicate.close()  # só a duplicata criada acima
                    # Um único pedido por sessão: a aba de prova é reaproveitada como aba do chat
                    # na primeira; na segunda o chat já existia e a aba de prova é fechada.
                    self.assertEqual(['/browserapi-proof-' in target for _, target in holder['opened']],
                                     [True, True])
            self.in_worker(exercise_connection)

    def test_same_origin_tab_in_another_browser_context_is_never_used(self):
        """Playwright agrupa os perfis num contexto só; a identidade CDP os separa.

        Contextos de navegador criados por CDP têm o mesmo comportamento observável
        de perfis diferentes para o Playwright (aba desconhecida cai no contexto
        padrão) e IDs distintos. Fixture local, sem conta real.
        """
        from browserapi_lab.browser import BrowserConfig, BrowserSession
        from browserapi_lab.existing_chrome import target_context_id
        with self.personal_chrome() as personal:
            url = self.server.url()
            holder = {}

            def exercise():
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    browser = pw.chromium.connect_over_cdp(personal.address)
                    cdp = browser.new_browser_cdp_session()
                    other_id = cdp.send('Target.createBrowserContext')['browserContextId']
                    ctx = browser.contexts[0]
                    mine = ctx.new_page()
                    mine.goto(url)
                    cdp.send('Target.createTarget', {'url': url, 'browserContextId': other_id})
                    for _ in range(80):
                        tabs = [p for p in ctx.pages if p.url.startswith(url)]
                        if len(tabs) >= 2:
                            break
                        mine.wait_for_timeout(100)
                    # Evidência empírica da ficha F13 (Playwright 1.64.1, Chromium real):
                    self.assertEqual(len(browser.contexts), 1, 'Playwright deveria ver um único contexto')
                    self.assertEqual(len(tabs), 2, 'As duas abas aparecem no mesmo contexto do Playwright')
                    identities = {id(p): target_context_id(ctx, p) for p in tabs}
                    self.assertEqual(len(set(identities.values())), 2, 'IDs CDP distintos por contexto')
                    other = next(p for p in tabs if p is not mine)

                    session = BrowserSession(BrowserConfig(attach_existing_chrome=True, existing_profile='Default',
                                                           profiles_root=personal.home / 'app'))
                    session._context, session._attached_browser = ctx, browser
                    session._profile_context_id = identities[id(mine)]
                    holder['session'] = session
                    with patch('browserapi_lab.profiles.open_profile', side_effect=AssertionError('não deve abrir nada')):
                        chosen = session.page(url)
                    self.assertIs(chosen, mine)
                    self.assertIsNot(chosen, other)

                    # Sem aba no contexto escolhido: abre pelo pedido (emulado) e ignora a do outro contexto.
                    mine.close()

                    def opener(identifier, target):
                        holder['opened'] = (identifier, target)
                        cdp.send('Target.createTarget', {'url': target})
                    with patch('browserapi_lab.profiles.open_profile', side_effect=opener):
                        reopened = session.page(url)
                    self.assertEqual(holder['opened'], ('chrome:Default', url))
                    self.assertIsNot(reopened, other)
                    self.assertEqual(target_context_id(ctx, reopened), session._profile_context_id)
                    self.assertFalse(other.is_closed(), 'A aba do outro contexto não pode ser tocada')
            self.in_worker(exercise)

    def test_profile_not_honored_by_chrome_fails_before_any_chat_tab(self):
        """Se o Chrome ignorar o perfil pedido, parar antes de abrir o chat."""
        from browserapi_lab.browser import BrowserConfig, BrowserSession
        from browserapi_lab.existing_chrome import ProfileMismatchError
        with self.personal_chrome() as personal:
            config = BrowserConfig(profile='connection', profiles_root=personal.home / 'app',
                                   attach_existing_chrome=True, existing_profile='Profile 1')
            holder = {}

            def exercise_mismatch():
                with self.attached_to(personal, holder):
                    session = holder['session'] = BrowserSession(config)
                    with self.assertRaises(ProfileMismatchError):
                        session.start()
            self.in_worker(exercise_mismatch)
            self.assertEqual(len(holder['opened']), 1, 'Somente a aba de prova pode ter sido pedida')
            self.assertIn('/browserapi-proof-', holder['opened'][0][1])

    def test_manual_voice_then_type_then_select_send_without_sending(self):
        config = self.prepare()
        self.page.evaluate("""() => {
            const button = document.querySelector('#send');
            button.setAttribute('aria-label', 'Microfone');
            document.querySelector('#composer').addEventListener('input', event => {
                button.setAttribute('aria-label', event.target.value ? 'Enviar mensagem' : 'Microfone');
            });
        }""")
        prompts = []
        def ask(text):
            prompts.append(text)
            if 'digite algo' in text:
                self.page.locator('#composer').fill('rascunho digitado pela pessoa')
                self.page.locator('#send').click()
                self.page.keyboard.press('Enter')
                self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)
                return ''
            return 's'
        def choose(page, role):
            page.evaluate("""() => { const timer = setInterval(() => {
                if (!window.__balPickerCleanup) return;
                clearInterval(timer); document.querySelector('#send').click(); document.querySelector('[data-picker-confirm]').click();
            }, 100); }""")
            return pick(page, role)
        repair_fields(self.page, config, ask=ask, tell=lambda _:None, picker=choose,
                      manual_send=True, fields=('voice','send'))
        self.assertEqual(config.voice, '#send')
        self.assertEqual(len(config.voice_signature), 64)
        self.assertEqual(config.send, '#send')
        self.assertTrue(any('digite algo' in text for text in prompts))
        self.assertEqual(self.page.locator('#composer').input_value(), 'rascunho digitado pela pessoa')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)
        self.page.locator('#composer').fill('')  # pessoa apaga antes de autorizar o teste
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'success')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 1)

    def test_recorded_voice_state_blocks_even_without_voice_label(self):
        from browserapi_lab.sender import control_fingerprint
        config = self.prepare()
        button = self.page.locator('#send')
        button.evaluate("el => { el.removeAttribute('aria-label'); el.textContent = '●'; }")
        config.voice = '#send'
        config.voice_signature = control_fingerprint(button)
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'send_is_microphone')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)

    def test_manual_teaching_cancel_preserves_user_draft_and_removes_guard(self):
        config = self.prepare()
        def ask(text):
            if 'digite algo' in text:
                self.page.locator('#composer').fill('minha edição')
                raise EOFError()
            return 's'
        with self.assertRaises(EOFError):
            repair_fields(self.page, config, ask=ask, tell=lambda _:None,
                          manual_send=True, fields=('send',))
        self.assertEqual(self.page.locator('#composer').input_value(), 'minha edição')
        self.assertFalse(self.page.evaluate('Boolean(window.__balTypingCleanup)'))
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)

    def test_no_authorization_no_send(self):
        config = self.prepare()
        self.assertEqual(exchange(self.page, config, health_check=True).status, 'not_authorized')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)

    def test_draft_not_overwritten(self):
        config = self.prepare()
        self.page.locator('#composer').fill('private draft')
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'draft_present')
        self.assertEqual(self.page.locator('#composer').input_value(), 'private draft')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)

    def test_old_answer_does_not_confirm_new_response(self):
        config = self.prepare('empty')
        config.timeout_ms = 500
        self.page.locator('[data-role=assistant] .body').evaluate("el => el.textContent = 'old answer'")
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'timeout')

    def test_broken_selector_repair_then_success(self):
        config = self.prepare()
        config.composer = '#missing'
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'composer_missing')
        answers = iter(['s', 'n', 'n', 'n'])
        repair_fields(self.page, config, ask=lambda _: next(answers), tell=lambda *_: None,
                      picker=lambda *_: '#composer')
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'success')

    def test_blocked_states_and_remedies(self):
        for mode, expected in (('login', 'login_required'), ('ratelimit', 'rate_limit'), ('error', 'error')):
            with self.subTest(mode=mode):
                config = self.prepare(mode)
                result = exchange(self.page, config, authorized=True, health_check=True)
                self.assertEqual(result.status, expected)
                self.assertTrue(result.receipt(config)['action'])
                self.assertFalse(result.compatible)

    def test_wrong_origin_never_sends(self):
        config = self.prepare()
        config.url = 'https://other.example/'
        self.assertEqual(exchange(self.page, config, authorized=True, health_check=True).status, 'wrong_origin')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)

    def test_ask_returns_markdown_without_health_prompt(self):
        config = self.prepare('normal')
        result = exchange(self.page, config, 'Mensagem pública', authorized=True)
        self.assertEqual(result.status, 'success')
        self.assertIn('```python', result.answer)
        self.assertEqual(self.page.evaluate('FakeChat.lastUserMessage()'), 'Mensagem pública')

    def test_configure_wizard_with_explicit_confirmation(self):
        config = self.prepare()
        session = self.session
        page = self.page
        class WizardSession:
            def page(self, url):
                page.goto(url, wait_until='load')
                page.evaluate("FakeChat.config({mode:'contract',delay:1})")
                return page
        @contextmanager
        def factory(browser):
            self.assertFalse(browser.headless, 'assistente deve abrir janela visível por padrão')
            yield WizardSession()
        answers = iter(['chromium', 'custom', config.url, '', 's', 's', 's', 's', 's', 's'])
        selectors = iter(['#composer', '#send', '[data-role="user"] .body', '[data-role="assistant"] .body'])
        with tempfile.TemporaryDirectory() as root:
            store = ConfigStore(root)
            receipt = configure(store, 'wizard', ask=lambda _: next(answers), tell=lambda *_: None,
                                session_factory=factory, picker=lambda *_: next(selectors))
            self.assertTrue(receipt['compatible_in_this_run'], receipt)
            self.assertEqual(status(store, 'wizard')['status'], 'success')
            self.assertTrue(store.load('wizard').ready)

    def test_picker_selects_composer_and_prevents_send(self):
        self.prepare()
        script = (Path(__file__).parents[1] / 'browserapi_lab/assets/picker.js').read_text()
        self.page.evaluate(script, 'campo de mensagem')
        self.page.locator('#composer').click()
        self.assertIsNone(self.page.evaluate('window.__balPick'))
        self.page.locator('[data-picker-confirm]').click()
        self.assertEqual(self.page.evaluate('window.__balPick.selector'), '#composer')
        self.page.locator('#composer').fill('Não enviar durante reparo')
        self.page.evaluate(script, 'botão Enviar')
        self.page.locator('#send').click()
        self.page.locator('[data-picker-confirm]').click()
        self.assertEqual(self.page.evaluate('window.__balPick.selector'), '#send')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 0)
        self.assertEqual(self.page.locator('#__browserapi_picker').count(), 0)

    def test_visual_picker_generic_text_preview_layers_back_and_cancel(self):
        self.prepare()
        self.page.evaluate("""() => {
            const section=document.createElement('section');
            section.id='sample-selection';
            section.innerHTML='<div><p>Resposta de exemplo para selecionar visualmente.</p></div>';
            document.body.prepend(section);
        }""")
        script=(Path(__file__).parents[1]/'browserapi_lab/assets/picker.js').read_text()
        self.page.evaluate(script,'resposta do assistente')
        self.page.locator('#sample-selection p').click()
        self.assertIsNone(self.page.evaluate('window.__balPick'))
        self.assertGreater(self.page.locator('#__browserapi_picker_marks button').count(),0)
        self.page.get_by_role('button',name='Camada maior',exact=True).click()
        self.page.get_by_role('button',name='Voltar',exact=True).click()
        self.page.locator('[data-picker-confirm]').click()
        selector=self.page.evaluate('window.__balPick.selector')
        self.assertEqual(self.page.locator(selector).inner_text(),'Resposta de exemplo para selecionar visualmente.')
        self.assertEqual(self.page.locator('#__browserapi_picker_marks').count(),0)
        self.page.evaluate(script,'campo de mensagem')
        self.page.get_by_role('button',name='Cancelar',exact=True).click()
        self.assertTrue(self.page.evaluate('window.__balPick.cancelled'))
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'),0)

    def test_unrelated_page_mutations_do_not_block_completion(self):
        config = self.prepare()
        config.root = 'body'
        self.page.evaluate('''() => {
          const clock = document.createElement('div'); document.body.appendChild(clock);
          window.noiseTimer = setInterval(() => { clock.textContent = String(performance.now()); }, 25);
        }''')
        try:
            result = exchange(self.page, config, authorized=True, health_check=True)
            self.assertEqual(result.status, 'success')
        finally:
            self.page.evaluate('clearInterval(window.noiseTimer)')


    def test_repair_message_containers_by_real_pointing(self):
        config = self.prepare()
        self.page.evaluate("FakeChat.send('mensagem de amostra')")
        self.page.wait_for_function("FakeChat.state().status === 'done'")
        script = (Path(__file__).parents[1] / 'browserapi_lab/assets/picker.js').read_text()
        for role, target, key in (('mensagem do usuário', '[data-role=user] .body', 'user'),
                                  ('resposta do assistente', '[data-role=assistant]:last-child .body', 'assistant')):
            self.page.evaluate(script, role)
            self.page.locator(target).click()
            self.page.locator('[data-picker-confirm]').click()
            selected = self.page.evaluate('window.__balPick.selector')
            setattr(config, key, selected)
        result = exchange(self.page, config, authorized=True, health_check=True)
        self.assertEqual(result.status, 'success')
        self.assertEqual(self.page.evaluate('FakeChat.state().user_messages'), 2)



class TestCLIRealBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from _harness import no_browser_reason
        import shutil
        reason = no_browser_reason()
        if reason:
            raise unittest.SkipTest(reason)
        if not shutil.which('xvfb-run'):
            raise RuntimeError('CI precisa de xvfb-run para testar a CLI headed')

    def test_check_status_and_ask_from_real_cli(self):
        import os
        import subprocess
        import sys
        from _harness import FixtureServer, REPO_ROOT
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            html = (REPO_ROOT / 'browserapi_lab/assets/fake_chat.html').read_text()
            html = html.replace('mode: "normal",', 'mode: "contract",').replace('delay: 4,', 'delay: 1,')
            # A fixture CLI deve ser explicitamente curta; não aumentar timeout
            # nem reenviar para mascarar uma execução que não concluiu.
            self.assertIn('mode: "contract",', html)
            self.assertIn('delay: 1,', html)
            (root / 'fake_chat.html').write_text(html)
            server = FixtureServer(root).start()
            try:
                config = ChatConfig('cli-chat', server.url(), provider='fixture', timeout_ms=15000,
                                    stability_ms=400, **HYPOTHESES['fixture'])
                store = ConfigStore(root / 'settings')
                store.save(config)
                command = ['xvfb-run', '-a', sys.executable, '-m', 'browserapi_lab.cli',
                           '--config-dir', str(store.root)]
                env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
                result = subprocess.run(command + ['check', 'cli-chat'], input='\ns\n', text=True,
                                        capture_output=True, timeout=40, cwd=root, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(store.status('cli-chat')['compatible_in_this_run'])
                status_result = subprocess.run(command + ['status', 'cli-chat'], text=True,
                                               capture_output=True, timeout=10, cwd=root, env=env)
                self.assertEqual(status_result.returncode, 0, status_result.stderr)
                # Ausência de consentimento nunca envia; status anterior é substituído por recibo de não envio.
                result = subprocess.run(command + ['check', 'cli-chat'], input='\nn\n', text=True,
                                        capture_output=True, timeout=40, cwd=root, env=env)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(store.status('cli-chat')['status'], 'not_authorized')
            finally:
                server.stop()


class TestProductHealthBenchmark(BrowserTestCase):
    def test_ten_checks_same_chat_with_capture_budget(self):
        import json
        import statistics
        from _harness import REPO_ROOT
        from browserapi_lab.benchmark import percentile
        config = ChatConfig('benchmark-health', self.server.url(), provider='fixture',
                            timeout_ms=15000, stability_ms=1200, **HYPOTHESES['fixture'])
        self.page.goto(config.url, wait_until='load')
        self.page.evaluate("FakeChat.config({mode:'contract', delay:1})")
        values, totals = [], []
        for iteration in range(10):
            result = exchange(self.page, config, authorized=True, health_check=True)
            self.assertEqual(result.status, 'success', f'iteration={iteration+1}')
            values.append(result.timings['capture_overhead_ms'])
            totals.append(result.timings['total_ms'])
        summary = {'iterations': 10, 'failures': 0, 'same_conversation': True,
                   'capture_p95_ms': percentile(values), 'capture_budget_ms': 900,
                   'total_p50_ms': statistics.median(totals), 'total_p95_ms': percentile(totals),
                   'browser_version': self.session.context.browser.version,
                   'scope': 'Contrato sintético local; não mede API ou chat real.'}
        self.assertLess(summary['capture_p95_ms'], 900)
        ConfigStore.write_json(REPO_ROOT / 'results/ci/product-flow.json', summary)
