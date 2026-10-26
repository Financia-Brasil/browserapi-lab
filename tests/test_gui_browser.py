"""Interface real + segundo Chromium visível no worker; somente site sintético."""
import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from _harness import BrowserTestCase, FixtureServer, REPO_ROOT
from browserapi_lab.config import ChatConfig, ConfigStore
from browserapi_lab.gui import LocalServer, Panel
from browserapi_lab.setup import HYPOTHESES, configure as real_configure
from browserapi_lab.browser import BrowserSession


class TestGraphicalJourney(BrowserTestCase):
    def setUp(self):
        self.training_audit = []
        self.temp = tempfile.TemporaryDirectory()
        fixture_dir = Path(self.temp.name) / 'fixture'
        fixture_dir.mkdir()
        source = (REPO_ROOT/'fixtures/fake_chat.html').read_text()
        # Não substituir </body> dentro da string srcdoc do iframe: isso
        # introduziria um </script> no meio do JavaScript original.
        before, after = source.rsplit('</body>', 1)
        source = before + '<script>FakeChat.config({mode:"contract",delay:1});</script></body>' + after
        (fixture_dir/'fake_chat.html').write_text(source)
        self.chat_server = FixtureServer(fixture_dir).start()
        self.store = ConfigStore(Path(self.temp.name) / 'config')
        self.panel = Panel(self.store, Path(self.temp.name) / 'data')
        self.http = LocalServer(self.panel)
        self.http_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.http_thread.start()

    def tearDown(self):
        self.panel.close()
        self.http.shutdown()
        self.http.server_close()
        self.http_thread.join(2)
        self.chat_server.stop()
        self.temp.cleanup()

    def open_panel(self):
        self.page.goto(self.http.entry_url)
        self.page.wait_for_function("document.querySelector('#prepared-label').textContent !== 'Verificando componentes…'")
        self.assertNotIn(self.http.token, self.page.url)

    def wait_question(self, text):
        self.page.wait_for_function("text => !document.querySelector('#prompt').hidden && document.querySelector('#question').textContent.includes(text)", arg=text)

    def wait_phase(self, phase):
        self.page.wait_for_function("text => document.querySelector('#phase').textContent === text", arg=phase, timeout=45000)

    def seed(self, mode='contract'):
        config = ChatConfig('saved', self.chat_server.url(), provider='fixture',
                            timeout_ms=4000, stability_ms=400, **HYPOTHESES['fixture'])
        self.store.save(config)
        return config

    def configure_with_simulated_person(self, store, name, **kwargs):
        # Fixtures locais apenas. O worker possui a página; o teste não a usa em outra thread.
        audit = self.training_audit
        current = []
        class TrainingSession(BrowserSession):
            def page(self, url=None):
                page = super().page(url)
                current[:] = [page]
                page.evaluate("""() => {
                    const composer = document.querySelector('#composer');
                    const send = document.querySelector('#send');
                    send.setAttribute('aria-label','Microfone');
                    composer.addEventListener('input', () => send.setAttribute('aria-label', composer.value ? 'Enviar mensagem' : 'Microfone'));
                    let previous;
                    window.__fixtureTeaching = [];
                    setInterval(() => {
                        if (window.__balTypingCleanup && !composer.value) {
                            composer.value = 'rascunho digitado na fixture';
                            composer.dispatchEvent(new Event('input', {bubbles:true}));
                        }
                        const banner = document.querySelector('#__browserapi_picker');
                        if (banner && banner !== previous) {
                            previous = banner;
                            const text = banner.textContent;
                            if (text.includes('botão de comando de voz')) {
                                window.__fixtureTeaching.push('voice'); send.click();
                            } else if (text.includes('botão Enviar')) {
                                window.__fixtureTeaching.push('send'); send.click(); window.__fixtureSelected = true;
                            }
                        }
                        if (window.__fixtureClearAllowed && window.__fixtureSelected && !window.__balTypingCleanup && !window.__balPickerCleanup && composer.value === 'rascunho digitado na fixture') {
                            window.__fixtureTeaching.push('removed-own-draft');
                            composer.value = ''; composer.dispatchEvent(new Event('input',{bubbles:true}));
                        }
                    }, 80);
                }""")
                return page
        original_ask = kwargs['ask']
        def ask(text):
            if 'Apontar mensagem do usuário' in text:
                current[0].evaluate('window.__fixtureClearAllowed = true')
            if 'Autoriza UMA' in text:
                audit.append(current[0].evaluate('({count:FakeChat.state().user_messages,steps:window.__fixtureTeaching})'))
            return original_ask(text)
        kwargs['ask'] = ask
        return real_configure(store,name,session_factory=TrainingSession,**kwargs)

    def skip_other_message_fields(self):
        self.wait_question('Apontar mensagem do usuário')
        self.page.click('#no')
        self.wait_question('Apontar resposta do assistente')
        self.page.click('#no')

    def test_managed_update_reloads_interface_without_reinstall_or_new_token(self):
        class Managed:
            def snapshot(self):
                return {'managed':True,'enabled':True,'message':'Atualização automática ativa.'}
        self.panel.updater=Managed()
        self.open_panel()
        self.assertTrue(self.page.locator('#auto-update').is_checked())
        original_url=self.page.url
        original_token=self.http.token
        new_assets=Path(self.temp.name)/'new-assets'
        new_assets.mkdir()
        for source in (REPO_ROOT/'browserapi_lab/assets').iterdir():
            if source.is_file():
                (new_assets/source.name).write_text(source.read_text().replace('0.3.0','0.3.1'))
        with patch('browserapi_lab.gui.ASSETS',new_assets), patch('browserapi_lab.gui.APP_VERSION','0.3.1'):
            self.page.wait_for_function("document.querySelector('#version-status').textContent.includes('Painel 0.3.1') && document.querySelector('#version-status').textContent.includes('programa 0.3.1')",timeout=10000)
            self.assertEqual(self.page.url,original_url)
            self.assertEqual(self.http.token,original_token)
            self.assertTrue(self.page.locator('#error').is_hidden())
            self.assertTrue(self.page.locator('#auto-update').is_checked())

    def test_pattern_and_console_have_no_invalid_regex_or_favicon_error(self):
        failures = []
        self.page.on('pageerror', lambda error: failures.append(str(error)))
        self.page.on('console', lambda message: failures.append(message.text) if message.type == 'error' else None)
        self.open_panel()
        for value in ('chat-voz','chat_voz','Gemini2'):
            self.page.fill('#name',value)
            self.assertTrue(self.page.locator('#name').evaluate('el => el.checkValidity()'))
        for value in ('-chat','chat com espaço','chat!'):
            self.page.fill('#name',value)
            self.assertFalse(self.page.locator('#name').evaluate('el => el.checkValidity()'))
        self.assertEqual(self.page.request.get(self.http.url+'/favicon.ico').status,204)
        self.assertEqual(failures,[])

    def test_runtime_mismatch_blocks_actions_instead_of_old_task_400(self):
        self.seed()
        original = self.panel.snapshot
        def old_state():
            state = original()
            state.pop('version')
            return state
        with patch.object(self.panel,'snapshot',side_effect=old_state):
            self.open_panel()
            self.assertIn('versões diferentes',self.page.locator('#error').inner_text())
            self.assertTrue(self.page.locator('#configure').is_disabled())
            self.assertTrue(self.page.get_by_role('button',name='Corrigir campos').is_disabled())
            self.assertIn('antigo',self.page.locator('#version-status').inner_text())

    def test_repair_always_asks_voice_presence_then_type_and_send(self):
        config = self.seed()
        config.voice = '#send'
        config.voice_signature = 'a'*64
        self.store.save(config)
        self.open_panel()
        with patch('browserapi_lab.gui.configure',side_effect=self.configure_with_simulated_person):
            self.page.get_by_role('button',name='Corrigir campos').click()
            self.wait_question('Quando o chat')
            self.page.click('#continue')
            self.wait_question('Apontar campo de mensagem')
            self.page.click('#no')
            self.wait_question('Com o campo de mensagem vazio')
            self.page.click('#no')  # sem voz: remove estado negativo antigo
            self.wait_question('digite algo SEM enviar')
            self.page.click('#continue')
            self.skip_other_message_fields()
            self.wait_question('Autoriza UMA')
            self.page.click('#no')
            self.wait_phase('Concluído')
        self.assertEqual(self.store.load('saved').voice,'')
        self.assertEqual(self.store.load('saved').voice_signature,'')
        self.assertEqual(self.store.status('saved')['status'],'not_authorized')
        self.assertEqual(self.training_audit[0]['count'],0)
        self.assertIn('send',self.training_audit[0]['steps'])

    def test_buttons_voice_send_and_switch_saved_session_are_visible(self):
        self.seed()
        self.open_panel()
        self.assertEqual(self.page.get_by_role('button',name='Selecionar botão de voz').count(),1)
        self.assertEqual(self.page.get_by_role('button',name='Digitar e selecionar Enviar / Enter').count(),1)
        with patch('browserapi_lab.browser.BrowserSession.start') as launch:
            self.page.get_by_role('button',name='Usar Chrome já aberto').click()
            self.wait_question('Mudar este chat salvo')
            self.page.click('#yes')
            self.wait_phase('Concluído')
            self.assertEqual(self.store.load('saved').session_mode,'existing_chrome')
            self.assertIn('Chrome já aberto (configurado)',self.page.locator('#chats').inner_text())
            launch.assert_not_called()

    def test_full_form_configure_then_health_check(self):
        # A hipótese é local à fixture, não evidência de compatibilidade com sites reais.
        with patch.dict(HYPOTHESES, {'custom':HYPOTHESES['fixture']}), patch('browserapi_lab.gui.configure',side_effect=self.configure_with_simulated_person):
            self.open_panel()
            self.page.select_option('#browser','chromium')
            self.page.select_option('#provider','custom')
            self.page.fill('#name','graphical')
            self.page.fill('#url', self.chat_server.url())
            self.page.click('#configure')
            self.wait_question('Quando o chat')
            self.assertFalse((self.store.root/'graphical.status.json').exists())
            self.page.click('#continue')
            self.wait_question('Apontar campo de mensagem')
            self.page.click('#no')
            self.wait_question('Com o campo de mensagem vazio')
            self.page.click('#yes')
            self.wait_question('digite algo SEM enviar')
            self.page.click('#continue')
            self.skip_other_message_fields()
            self.wait_question('Autoriza UMA')
            self.assertFalse((self.store.root/'graphical.status.json').exists())
            self.page.click('#yes')
            self.wait_phase('Concluído')
            receipt = self.store.status('graphical')
            self.assertTrue(receipt['compatible_in_this_run'], receipt)
            self.assertEqual(self.training_audit[0]['count'],0)
            self.assertIn('voice',self.training_audit[0]['steps'])
            self.assertIn('send',self.training_audit[0]['steps'])
            self.assertIn('Funcionou neste teste',self.page.locator('#result-title').inner_text())
            self.assertEqual(receipt['browser'],'chromium')
            self.page.wait_for_function("document.querySelector('#stat-requests').textContent === '1'")
            self.assertEqual(self.page.locator('#stat-success').inner_text(),'100%')
            self.assertEqual(self.page.locator('#stat-tokens').inner_text(),'Não disponível')
            self.assertIn('Online (observado)',self.page.locator('#source-health').inner_text())
            self.assertEqual(self.page.locator('#latency-history li').count(),1)
            self.assertGreaterEqual(receipt['timings']['browser_start_ms'],0)
            self.assertGreaterEqual(receipt['timings']['page_open_ms'],0)
            self.assertIn('Pipeline de envio',self.page.locator('#stage-timings').text_content())

            self.page.get_by_role('button', name='Testar agora').click()
            self.wait_question('Faça login')
            self.page.click('#continue')
            self.wait_question('Autoriza UMA')
            self.page.click('#yes')
            self.wait_phase('Concluído')
            self.assertTrue(self.store.status('graphical')['compatible_in_this_run'])
            self.page.wait_for_function("document.querySelector('#stat-requests').textContent === '2'")
            self.assertEqual(self.page.locator('#latency-history li').count(),2)
            self.assertEqual(self.panel.snapshot()['telemetry']['requests'],2)

            evidence = {'kind':'synthetic_graphical_journey','headed_worker':True,
                        'form_configure':True,'health_check':True,'consent_buttons':True,
                        'receipt':self.store.status('graphical'),
                        'scope':'Fixture local; não autentica sites externos ou instala em desktop Ubuntu real.'}
            destination = REPO_ROOT/'results/ci/gui-flow.json'
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_text(json.dumps(evidence,indent=2)+'\n')

    def test_denial_and_cancel_do_not_run_exchange(self):
        self.seed()
        self.open_panel()
        with patch('browserapi_lab.setup.exchange') as exchange:
            self.page.get_by_role('button',name='Testar agora').click()
            self.wait_question('Faça login')
            self.page.click('#cancel')
            self.wait_phase('Interrompido')
            exchange.assert_not_called()
            self.assertIsNone(self.store.status('saved'))
        self.page.get_by_role('button',name='Testar agora').click()
        self.wait_question('Faça login')
        self.page.click('#continue')
        self.wait_question('Autoriza UMA')
        self.page.click('#no')
        self.wait_phase('Concluído')
        self.assertEqual(self.store.status('saved')['status'],'not_authorized')
        self.assertFalse(self.store.status('saved')['compatible_in_this_run'])

    def test_dom_text_is_not_executable_and_repair_remedy_visible(self):
        config = self.seed()
        config.composer = '#missing'
        self.store.save(config)
        self.panel.tell('<img src=x onerror="window.secretLeaked=true">')
        self.open_panel()
        self.assertIn('<img',self.page.locator('#log').inner_text())
        self.assertEqual(self.page.locator('#log img').count(),0)
        self.assertFalse(self.page.evaluate('Boolean(window.secretLeaked)'))
        self.page.get_by_role('button',name='Testar agora').click()
        self.wait_question('Faça login')
        self.page.click('#continue')
        self.wait_question('Autoriza UMA')
        self.page.click('#yes')
        self.wait_phase('Concluído')
        self.assertEqual(self.store.status('saved')['status'],'composer_missing')
        self.assertIn('Corrigir campos',self.page.locator('#result-action').inner_text())
