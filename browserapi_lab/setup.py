"""Assistente terminal + apontamento no navegador; modelo sempre manual."""
from dataclasses import asdict
from pathlib import Path
import shutil
import time
from contextlib import contextmanager

from .browser import BrowserSession
from .chat import ChatResult, browser_config, config_fingerprint, exchange, google_login_blocked
from .config import BROWSERS, ChatConfig, ConfigStore, PROVIDERS, safe_name, safe_url
from .discovery import collect, rank_candidates

# Hipóteses, não contratos: check é o único caminho para recibo de compatibilidade.
HYPOTHESES = {
    'custom': {'user': '[data-message-author-role="user"],user-query,[data-role="user"]',
               'assistant': '[data-message-author-role="assistant"],model-response,[data-role="assistant"]'},
    'gemini': {'composer': '.ql-editor[contenteditable="true"]',
               'send': 'button[aria-label="Send message"],button[aria-label="Enviar mensagem"]',
               'user': 'user-query', 'assistant': 'model-response'},
    'lmarena': {'composer': 'textarea', 'send': 'button[aria-label="Send message"]',
                'user': '[data-message-author-role="user"]',
                'assistant': '[data-message-author-role="assistant"]'},
    'fixture': {'composer': '#composer', 'send': '#send', 'root': '#conversation',
                'user': '[data-role="user"] .body', 'assistant': '[data-role="assistant"] .body'},
}


def browser_options():
    # Não anunciar Firefox/Safari como compatíveis com um engine Chromium.
    return {
        'chromium': 'Chromium gerenciado (requer playwright install chromium)',
        'chrome': 'Google Chrome instalado' + ('' if shutil.which('google-chrome') else ' (não localizado no PATH)'),
        'msedge': 'Microsoft Edge instalado' + ('' if shutil.which('microsoft-edge') else ' (não localizado no PATH)'),
        'custom': 'Outro binário da família Chromium por caminho absoluto',
    }


def pick(page, role, cancelled=None):
    page.bring_to_front()
    script = (Path(__file__).parent / 'assets' / 'picker.js').read_text(encoding='utf-8')
    voice_script = (Path(__file__).parent / 'assets' / 'voice_control.js').read_text()
    page.evaluate('() => { window.__balVoiceControl = (' + voice_script + '); }')
    page.evaluate(script, role)
    try:
        if cancelled is None:
            page.wait_for_function('window.__balPick !== null', timeout=120000)
        else:
            import time
            deadline = time.monotonic() + 120
            while page.evaluate('window.__balPick === null'):
                if cancelled() or time.monotonic() > deadline:
                    raise EOFError('Seleção cancelada')
                page.wait_for_timeout(100)
        value = page.evaluate('window.__balPick')
        return None if value.get('cancelled') else value.get('selector')
    finally:
        page.evaluate('() => { if (window.__balPickerCleanup) window.__balPickerCleanup(); delete window.__balVoiceControl; }')


def suggest(page, config):
    for key, value in HYPOTHESES.get(config.provider, {}).items():
        if not getattr(config, key) or getattr(config, key) == 'body':
            setattr(config, key, value)
    for role, key in (('composer', 'composer'), ('send_button', 'send')):
        try:
            candidates = rank_candidates(collect(page, role)['candidates'], role)
            if (candidates and candidates[0].inside == 'document' and candidates[0].candidate.get('visible')
                    and candidates[0].score >= 50
                    and any(signal in candidates[0].signals for signal in ('name_match', 'placeholder_match', 'testid_match'))):
                setattr(config, key, candidates[0].selector)
        except Exception:
            pass
    return config


def manual_send_pick(page, config, ask, tell, picker):
    script = (Path(__file__).parent / 'assets/typing_guard.js').read_text()
    page.evaluate(script)
    try:
        ask('Na janela do chat, digite algo SEM enviar. Não pressione Enter. Quando aparecer Enviar, volte aqui e clique em Continuar; depois clique nesse botão apenas para selecioná-lo. ')
        if page.evaluate('window.__balTypingCancelled'):
            raise EOFError('Seleção cancelada')
        from .sender import is_recorded_voice
        while True:
            selected = picker(page, 'botão Enviar')
            if not selected or not is_recorded_voice(page.locator(selected), config):
                break
            tell('Esse é o estado de voz registrado. Selecione Enviar depois de digitar, ou Esc para cancelar.')
        tell('Seu rascunho foi preservado. Apague-o manualmente antes de autorizar um teste; nada foi enviado pelo apontamento.')
        return selected
    finally:
        page.evaluate('() => { if (window.__balTypingCleanup) window.__balTypingCleanup(); delete window.__balTypingCancelled; }')


def repair_fields(page, config, ask=input, tell=print, picker=pick, draft_preview=False, manual_send=False, fields=None):
    labels = {'composer': 'campo de mensagem', 'send': 'botão Enviar',
              'user': 'mensagem do usuário', 'assistant': 'resposta do assistente'}
    if manual_send or (fields and 'voice' in fields):
        labels = {'composer': 'campo de mensagem', 'voice': 'botão de comando de voz', **{key: label for key, label in labels.items() if key != 'composer'}}
    tell('Reparo por apontamento. Tenha uma mensagem sua e uma resposta visíveis na conversa.')
    tell('Não envie outra mensagem se a tentativa anterior ficou sem confirmação.')
    for key, label in labels.items():
        if fields is not None and key not in fields:
            continue
        if key == 'voice':
            should_pick = confirmed(ask, 'Com o campo de mensagem vazio, este chat tem um botão de entrada de texto por voz (microfone)?')
            if not should_pick:
                config.voice = ''
                config.voice_signature = ''
                tell('Chat sem entrada por voz: nenhum estado de microfone será usado.')
        else:
            should_pick = (key == 'send' and manual_send) or confirmed(ask, f'Apontar {label}?')
        if should_pick:
            preview = 'BrowserAPI: rascunho temporário de configuração, não enviar.'
            temporary = False
            composer = None
            try:
                if key == 'send' and draft_preview and confirmed(ask,
                        'Autoriza um rascunho temporário SEM enviar, para o microfone virar Enviar?'):
                    from .sender import read_composer
                    composer = page.locator(config.composer)
                    if composer.count() != 1 or not composer.is_editable():
                        tell('Primeiro aponte um campo de mensagem editável. Nenhum rascunho foi escrito.')
                        continue
                    if read_composer(composer):
                        tell('Seu rascunho será preservado. Aponte o botão Enviar, não o microfone.')
                    else:
                        temporary = True
                        composer.fill(preview)
                        tell('Rascunho temporário preenchido. Aponte Enviar; nada será enviado pelo apontamento.')
                selected = manual_send_pick(page, config, ask, tell, picker) if key == 'send' and manual_send else picker(page, label)
                if selected:
                    if key == 'voice':
                        from .sender import control_fingerprint
                        config.voice_signature = control_fingerprint(page.locator(selected))
                    setattr(config, key, selected)
                    tell('Controle de voz registrado para ignorar esse estado; não bloqueamos o mesmo botão depois que virar Enviar.' if key == 'voice' else 'Seleção atualizada.')
            finally:
                if temporary:
                    try:
                        from .sender import read_composer
                        if composer.count() == 1 and read_composer(composer) == preview:
                            composer.fill('')
                            tell('Rascunho temporário removido.')
                        else:
                            tell('O conteúdo mudou; não apagamos sua edição. Confira o campo antes do teste.')
                    except Exception:
                        tell('Não foi possível conferir a remoção do rascunho temporário. Confira a janela do chat.')
    return config.validate()


def confirmed(ask, message):
    return ask(message + ' [s/N] ').strip().lower() in ('s', 'sim')


def blocked_login_receipt(page, config, store, tell, timings=None):
    if not google_login_blocked(page):
        return None
    receipt = ChatResult('google_login_blocked',timings=timings or {}).receipt(config)
    if config.name in store.names():
        store.save_status(config.name, receipt)
    tell(receipt['message'])
    tell(receipt['action'])
    return receipt


def navigation_receipt(page, config, store, ask, tell, timings=None):
    """Não reensinar seletores nem permitir envio em outra origem.

    A migração conhecida só muda o endereço após confirmação humana. A prova
    de perfil ocorre antes, em BrowserSession; domínio não é prova de conta.
    """
    from .config import arena_migration, display_origin, origin
    if origin(page.url) == origin(config.url):
        return None
    if arena_migration(config, page.url) and confirmed(ask,
            'A Arena mudou de lmarena.ai para arena.ai. Confira a conta e a conversa na aba. '
            'Autoriza salvar o endereço atual sem apagar os campos já escolhidos?'):
        try:
            target = safe_url(page.url)
        except ValueError:
            target = None
        if target:
            config.url = target
            store.save(config)
            tell('Endereço da Arena atualizado. Os campos foram preservados; nenhum envio foi feito nesta atualização.')
            return None
    from .chat import verified_profile
    diagnostics = {'expected_origin': display_origin(config.url), 'observed_origin': display_origin(page.url)}
    if verified_profile(page):
        diagnostics['profile_directory'] = verified_profile(page)
    result = ChatResult('wrong_origin', stage='navigation', timings=timings or {}, diagnostics=diagnostics)
    receipt = result.receipt(config)
    if config.name in store.names():
        store.save_status(config.name, receipt)
    tell(receipt['message'])
    tell(receipt['action'])
    return receipt


def authorize_session(config, ask, tell):
    if config.session_mode != 'existing_chrome':
        return True
    profile = (' Perfil escolhido: ' + config.personal_profile + '.') if config.personal_profile else ''
    tell('Vamos reaproveitar o chat aberto ou abrir uma aba para você. Confira a conta no Chrome antes de continuar.')
    if not confirmed(ask, 'Conectar ao seu Chrome?' + profile + ' A permissão permite acesso às abas e contas desse navegador. Nada será enviado sem sua autorização.'):
        return False
    if config.personal_profile:
        from .existing_chrome import endpoint, ExistingChromeError
        try:
            endpoint(installation=config.personal_installation)
        except ExistingChromeError:
            from .profiles import inventory, open_profile
            selected = next((p for p in inventory() if p['installation'] == config.personal_installation
                             and p['directory'] == config.personal_profile and p['connectable']), None)
            if selected is None:
                raise ExistingChromeError('O perfil escolhido não está disponível. Atualize a lista e escolha seu perfil novamente.')
            open_profile(selected['id'], 'chrome://inspect/#remote-debugging')
            ask('No Chrome que abriu, digite chrome://inspect/#remote-debugging na barra de endereço (o Chrome não deixa programas abrirem essa página) e ative a Depuração remota. Depois volte e clique em Continuar. Essa permissão é configurada uma vez; use Chrome 144 ou mais recente. ')
            endpoint(installation=config.personal_installation)
    return True


@contextmanager
def measured_page(session_factory, config, store):
    """Separar inicialização/lookup da aba da espera humana e da resposta."""
    started = time.perf_counter()
    with session_factory(browser_config(config, store.root)) as session:
        timings = {'browser_start_ms': round((time.perf_counter() - started) * 1000, 3)}
        opened = time.perf_counter()
        page = session.page(config.url)
        timings['page_open_ms'] = round((time.perf_counter() - opened) * 1000, 3)
        yield page, timings


def configure(store, name, *, repairing=False, ask=input, tell=print, session_factory=BrowserSession, picker=pick,
              initial_config=None, cancelled=None, draft_preview=False, manual_send=False):
    safe_name(name)
    if initial_config is not None:
        config = initial_config.validate()
        if config.name != name:
            raise ValueError('Nome da configuração divergente.')
    elif repairing:
        config = store.load(name)
    else:
        tell('1/5 — Navegador. Usaremos o produto escolhido com perfil separado, nunca seu perfil pessoal.')
        for key, label in browser_options().items():
            tell(f'  {key}: {label}')
        browser = ask('Navegador [chrome]: ').strip() or 'chrome'
        if browser not in BROWSERS:
            raise ValueError('Navegador não suportado. Escolha uma opção exibida.')
        executable = ask('Caminho absoluto do binário Chromium: ').strip() if browser == 'custom' else None
        tell('2/5 — Chat: gemini, lmarena ou custom (URL própria).')
        provider = ask('Chat [gemini]: ').strip() or 'gemini'
        if provider not in (*PROVIDERS, 'custom'):
            raise ValueError('Chat inválido.')
        url = PROVIDERS[provider] if provider in PROVIDERS else safe_url(ask('URL do chat: ').strip())
        config = ChatConfig(name, url, browser=browser, executable=executable, provider=provider).validate()
    if not authorize_session(config, ask, tell):
        return ChatResult('not_authorized').receipt(config)
    tell('Confira sua conta e escolha o modelo na janela do chat.' if config.session_mode == 'existing_chrome' else 'Faça login e escolha o modelo na janela que abrir.')
    tell('Se o Google disser que o navegador não é seguro, interrompa. Não avance ao apontamento; o programa não contorna essa proteção.')
    with measured_page(session_factory, config, store) as (page, session_timings):
        ask('Confira a conta no avatar do Chrome e o modelo no chat. Se estiverem corretos, clique em Continuar. ' if config.session_mode == 'existing_chrome' else 'Quando o chat e o modelo estiverem prontos, pressione Enter. ')
        blocked = blocked_login_receipt(page, config, store, tell, session_timings)
        if blocked:
            return blocked
        navigation = navigation_receipt(page, config, store, ask, tell, session_timings)
        if navigation:
            return navigation
        suggest(page, config)
        review = manual_send or repairing or not config.ready or confirmed(ask, 'Revisar os campos por apontamento antes do teste?')
        if review:
            tell('4/5 — Aponte os controles sem escrever CSS ou JavaScript.')
            repair_fields(page, config, ask, tell, picker, draft_preview=draft_preview, manual_send=manual_send)
        else:
            tell('4/5 — Detectamos hipóteses de controles. O teste abaixo verificará se funcionam.')
        store.save(config)
        tell('Configuração salva. Isso sozinho NÃO comprova compatibilidade.')
        if confirmed(ask, '5/5 — Autoriza UMA mensagem sintética neste chat para testar?'):
            result = exchange(page, config, authorized=True, health_check=True, cancelled=cancelled)
        else:
            result = ChatResult('not_authorized')
        result.timings.update(session_timings)
        receipt = result.receipt(config)
        store.save_status(config.name, receipt)
        tell(receipt['message'])
        tell(receipt['action'])
        return receipt


def check(store, name, *, message=None, ask=input, tell=print, session_factory=BrowserSession, cancelled=None):
    config = store.load(name)
    if not authorize_session(config, ask, tell):
        return ChatResult('not_authorized').receipt(config)
    with measured_page(session_factory, config, store) as (page, session_timings):
        ask('Confira a conta no avatar do Chrome e o modelo no chat. Se estiverem corretos, clique em Continuar. ' if config.session_mode == 'existing_chrome' else 'Faça login e escolha o modelo no navegador; Enter quando estiver pronto. ')
        blocked = blocked_login_receipt(page, config, store, tell, session_timings)
        if blocked:
            return blocked
        navigation = navigation_receipt(page, config, store, ask, tell, session_timings)
        if navigation:
            return navigation
        if message is None:
            authorized = confirmed(ask, 'Autoriza UMA mensagem sintética de verificação?')
        else:
            authorized = confirmed(ask, 'Autoriza enviar a mensagem informada UMA vez?')
        result = exchange(page, config, message, authorized=authorized, health_check=message is None, cancelled=cancelled)
        result.timings.update(session_timings)
        receipt = result.receipt(config)
        # ask não é prova de formato/compatibilidade equivalente ao desafio check.
        if message is None:
            store.save_status(name, receipt)
        tell(receipt['message'])
        tell(receipt['action'])
        if result.answer is not None and message is not None:
            tell(result.answer)
        return receipt


def status(store, name):
    config = store.load(name)
    receipt = store.status(name)
    if not receipt:
        return {'name': name, 'status': 'not_tested', 'compatible_in_this_run': False,
                'action': f'Execute check {name} para verificar com autorização.'}
    if receipt.get('config_fingerprint') != config_fingerprint(config):
        return {'name': name, 'status': 'configuration_changed', 'compatible_in_this_run': False,
                'action': f'A configuração mudou. Execute check {name} novamente.'}
    return receipt


def point_controls(store, name, field, *, ask=input, tell=print, cancelled=None,
                   session_factory=BrowserSession, picker=pick):
    if field not in ('voice', 'send'):
        raise ValueError('Controle inválido.')
    config = store.load(name)
    if not authorize_session(config, ask, tell):
        return ChatResult('not_authorized').receipt(config)
    with measured_page(session_factory, config, store) as (page, session_timings):
        ask('Confira a aba e a conta do chat. Quando estiverem corretas, clique em Continuar. ')
        blocked = blocked_login_receipt(page, config, store, tell, session_timings)
        if blocked:
            return blocked
        navigation = navigation_receipt(page, config, store, ask, tell, session_timings)
        if navigation:
            return navigation
        repair_fields(page, config, ask, tell, picker, manual_send=True, fields=(field,))
        store.save(config)
        tell('Apontamento salvo. Não enviamos mensagem e isso não é um teste de compatibilidade.')
    return None
