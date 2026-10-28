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


def pick(page, role, cancelled=None, *, step='', hint=''):
    """Abre o apontamento guiado e devolve o seletor.

    ``None`` significa "pulei este campo" — o mapeamento continua. Cancelar o
    mapeamento inteiro levanta ``EOFError``; só a escolha explícita do usuário
    faz isso (Esc e "Pular este campo" não abortam mais a configuração toda).
    """
    page.bring_to_front()
    script = (Path(__file__).parent / 'assets' / 'picker.js').read_text(encoding='utf-8')
    voice_script = (Path(__file__).parent / 'assets' / 'voice_control.js').read_text()
    page.evaluate('() => { window.__balVoiceControl = (' + voice_script + '); }')
    page.evaluate(script, {'role': role, 'step': step, 'hint': hint})
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
        if value.get('abort'):
            raise EOFError('Mapeamento cancelado')
        return None if value.get('cancelled') else value.get('selector')
    finally:
        page.evaluate('() => { if (window.__balPickerCleanup) window.__balPickerCleanup(); delete window.__balVoiceControl; }')


def element_preview(page, selector, prefer_last=False):
    """Texto e contagem que um seletor captura — para o usuário conferir.

    Só leitura: não envia, não altera. Devolve ``(texto_curto, contagem)``.
    ``prefer_last`` mostra a mensagem mais recente (a que está na tela), não a
    primeira da conversa.
    """
    if not selector or not hasattr(page, 'locator'):
        return None, 0
    try:
        locator = page.locator(selector)
        count = locator.count()
        if not count:
            return None, 0
        text = (locator.last if prefer_last else locator.first).evaluate(
            "el => (((el.innerText !== undefined ? el.innerText : el.textContent) || el.value"
            " || el.getAttribute('aria-label') || '') + '').replace(/\s+/g, ' ').trim()")
        text = ' '.join(str(text or '').split())
        return (text[:90] + ('…' if len(text) > 90 else '')), count
    except Exception:
        return None, 0


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


def manual_send_pick(page, config, ask, tell, picker, *, step='', hint='', prompt=None):
    script = (Path(__file__).parent / 'assets/typing_guard.js').read_text()
    page.evaluate(script)
    try:
        ask(prompt or ('Digite algo no campo do chat SEM enviar. Não pressione Enter. Quando aparecer Enviar, '
                       'volte aqui e clique em Continuar; depois clique nesse botão apenas para selecioná-lo. '))
        if page.evaluate('window.__balTypingCancelled'):
            raise EOFError('Seleção cancelada')
        from .sender import is_recorded_voice
        # Limite de tentativas: num site onde o botão sempre parece o microfone
        # registrado, repetir para sempre travaria o mapeamento (visto no CI).
        for attempt in range(3):
            selected = picker(page, 'botão Enviar', step=step, hint=hint)
            if not selected:
                return None
            readable = page.locator(selected)
            try:
                if not is_recorded_voice(readable, config):
                    tell('Seu rascunho foi preservado. Apague-o manualmente antes de autorizar um teste; '
                         'nada foi enviado pelo apontamento.')
                    return selected
            except Exception:
                return selected
            if attempt < 2:
                tell('Esse botão ainda é o microfone registrado. Digite no campo para ele virar Enviar '
                     'e clique de novo — ou use "Pular este campo".')
        tell('Não consegui distinguir o microfone de Enviar. O botão Enviar ficou como estava; '
             'refaça este campo quando o microfone estiver resolvido.')
        return None
    finally:
        page.evaluate('() => { if (window.__balTypingCleanup) window.__balTypingCleanup(); delete window.__balTypingCancelled; }')


# Rótulo que o picker.js mostra no topo do painel de seleção.
PICK_ROLES = {'composer': 'campo de mensagem', 'voice': 'botão de comando de voz',
              'send': 'botão Enviar', 'user': 'mensagem do usuário', 'assistant': 'resposta do assistente'}
DRAFT_PREVIEW = 'BrowserAPI: rascunho temporário de configuração, não enviar.'

# Passos do mapeamento: título curto, pergunta e dica para o apontamento.
MAPPING_STEPS = {
    'composer': ('Campo de digitação',
                 'Apontar o campo onde você digita a mensagem? É a caixa de texto de baixo, vazia — não é a conversa.',
                 'Clique na caixa de texto onde você digita. Nada é escrito nem enviado.'),
    'voice': ('Microfone (opcional)',
              'Com o campo de mensagem vazio, este chat tem um botão de entrada por voz (microfone)? '
              'Sim = você aponta agora; Não = seguimos para o botão Enviar.',
              'Clique no ícone de microfone. Se respondeu Sim e ele não existe, use "Pular este campo".'),
    'send': ('Botão Enviar',
             'Apontar o botão que ENVIA a mensagem (seta ou "Enviar")?',
             'Digite no campo, sem enviar, e clique no botão de enviar (seta ou "Enviar").'),
    'user': ('A sua pergunta',
             'Apontar A SUA PERGUNTA JÁ ENVIADA: o balão com o texto que você mandou (não o campo de digitar)?',
             'Clique em qualquer parte do balão da sua pergunta já enviada.'),
    'assistant': ('A resposta do chat',
                  'Apontar A RESPOSTA DO CHAT: o balão da resposta que o modelo deu?',
                  'Clique em qualquer parte do balão da resposta. Pegamos o balão inteiro.'),
}


def repair_fields(page, config, ask=input, tell=print, picker=pick, draft_preview=False, manual_send=False, fields=None):
    """Mapeamento guiado, um passo por campo, com pular/refazer.

    Regras que vieram do uso real (ADR-023):

    * cada pergunta diz o **passo** e **qual elemento** clicar;
    * ao confirmar, o programa mostra **o texto que vai capturar**;
    * pular um campo não cancela os outros (antes, um Esc perdia tudo);
    * no fim, cada campo pode ser refeito sem recomeçar do zero;
    * para mensagens, o apontamento sobe ao balão inteiro — o Gemini divide a
      resposta em vários ``<span>`` e um pedaço não é a resposta.
    """
    voice_wanted = manual_send or bool(fields and 'voice' in fields)
    order = [key for key in ('composer', 'voice', 'send', 'user', 'assistant')
             if (fields is None or key in fields) and (key != 'voice' or voice_wanted)]
    total = len(order)
    captured = {}
    skipped = []

    tell('Mapeamento por apontamento: um passo de cada vez. Esc pula o campo atual; '
         'o botão "Cancelar mapeamento" encerra tudo.')
    if {'user', 'assistant'} & set(order):
        tell('Para os balões da conversa, envie você mesmo uma pergunta no chat, espere a resposta e volte. '
             'O campo onde se digita NÃO é a pergunta já enviada.')
    tell('Não envie outra mensagem se a tentativa anterior ficou sem confirmação.')

    def record(key, selector):
        title = MAPPING_STEPS[key][0]
        text, count = element_preview(page, selector, prefer_last=key in ('user', 'assistant'))
        captured[key] = selector
        if text:
            extra = f' — {count} elemento(s) casam com este seletor' if count > 1 else ''
            tell(f'Capturado ({title}): “{text}”{extra}.')
        else:
            tell(f'Capturado ({title}) — não consegui ler texto nessa área. '
                 'Se a resposta não aparecer no teste, refaça este campo no fim.')

    def run_step(key, index):
        title, question, hint = MAPPING_STEPS[key]
        prefix = f'Passo {index} de {total} · {title} — '
        if key == 'voice':
            if not confirmed(ask, prefix + question):
                config.voice = ''
                config.voice_signature = ''
                tell('Seguindo sem microfone. Se o botão Enviar for confundido com o microfone, '
                     'refaça o campo no fim.')
                return
            selector = picker(page, 'botão de comando de voz', step=f'{index} de {total}', hint=hint)
            if not selector:
                skipped.append(key)
                tell('Microfone não apontado; seguimos para o botão Enviar.')
                return
            from .sender import control_fingerprint
            config.voice = selector
            config.voice_signature = control_fingerprint(page.locator(selector))
            tell('Microfone registrado: esse botão deixa de contar como Enviar.')
            captured[key] = selector
            return
        if not confirmed(ask, prefix + question):
            return
        selector = None
        temporary = False
        composer = None
        try:
            if key == 'send' and draft_preview and confirmed(ask,
                    'Autoriza um rascunho temporário SEM enviar, para o microfone virar Enviar?'):
                from .sender import read_composer
                composer = page.locator(config.composer)
                if composer.count() != 1 or not composer.is_editable():
                    tell('Primeiro aponte um campo de mensagem editável. Nenhum rascunho foi escrito.')
                    return
                if read_composer(composer):
                    tell('Seu rascunho será preservado. Aponte o botão Enviar, não o microfone.')
                else:
                    temporary = True
                    composer.fill(DRAFT_PREVIEW)
                    tell('Rascunho temporário preenchido. Aponte Enviar; nada será enviado pelo apontamento.')
            if key == 'send' and manual_send:
                selector = manual_send_pick(
                    page, config, ask, tell, picker, step=f'{index} de {total}', hint=hint,
                    prompt=(prefix + 'digite algo SEM enviar no campo do chat. Quando aparecer Enviar, '
                            'volte aqui e clique em Continuar; depois clique no botão para selecioná-lo. '))
            else:
                selector = picker(page, PICK_ROLES.get(key, title), step=f'{index} de {total}', hint=hint)
        finally:
            if temporary:
                try:
                    from .sender import read_composer
                    if composer.count() == 1 and read_composer(composer) == DRAFT_PREVIEW:
                        composer.fill('')
                        tell('Rascunho temporário removido.')
                    else:
                        tell('O conteúdo mudou; não apagamos sua edição. Confira o campo antes do teste.')
                except Exception:
                    tell('Não foi possível conferir a remoção do rascunho temporário. Confira a janela do chat.')
        if not selector:
            skipped.append(key)
            tell(f'{title}: campo não alterado (você pulou). Os outros passos continuam.')
            return
        setattr(config, key, selector)
        record(key, selector)

    for index, key in enumerate(order, 1):
        run_step(key, index)

    # Refazer sem recomeçar: uma pergunta única; só quem responde Sim percorre
    # os campos de novo (ninguém deve clicar "Não" cinco vezes para concluir).
    if captured and confirmed(ask, 'Passo final — algum campo saiu errado? '
                                   'Sim = refazer um por um; Não = concluir o mapeamento.'):
        for key in [item for item in order if item in captured]:
            if confirmed(ask, f'Refazer {MAPPING_STEPS[key][0]}?'):
                run_step(key, order.index(key) + 1)

    if captured:
        resumo = ', '.join(MAPPING_STEPS[key][0].lower() for key in order if key in captured)
        tell(f'Mapeamento concluído: {resumo}.')
    if skipped:
        nomes = ', '.join(MAPPING_STEPS[key][0].lower() for key in skipped)
        tell(f'Campos pulados: {nomes}. Eles continuam com o valor anterior; '
             'use "Corrigir campos" para refazê-los depois.')
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


def check(store, name, *, message=None, ask=input, tell=print, session_factory=BrowserSession, cancelled=None,
          show_answer=True, record=None):
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
        if result.answer is not None and message is not None and show_answer:
            tell(result.answer)
        # Chamado só depois de uma resposta nova validada. Recibos, telemetria e
        # relatórios continuam sem o texto; quem exibe decide onde guardá-lo.
        if (record is not None and message is not None and result.status == 'success'
                and isinstance(result.answer, str) and result.answer.strip()):
            try:
                record(name, message, result.answer, receipt)
            except Exception:
                tell('A resposta chegou, mas o painel não conseguiu mostrá-la. Nada foi reenviado; '
                     'veja a conversa no navegador.')
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
