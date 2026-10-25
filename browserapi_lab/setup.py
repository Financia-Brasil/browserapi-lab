"""Assistente terminal + apontamento no navegador; modelo sempre manual."""
from dataclasses import asdict
from pathlib import Path
import shutil

from .browser import BrowserSession
from .chat import ChatResult, browser_config, config_fingerprint, exchange
from .config import BROWSERS, ChatConfig, ConfigStore, PROVIDERS, safe_name, safe_url
from .discovery import collect, rank_candidates

# Hipóteses, não contratos: check é o único caminho para recibo de compatibilidade.
HYPOTHESES = {
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


def pick(page, role):
    script = (Path(__file__).parent / 'assets' / 'picker.js').read_text(encoding='utf-8')
    page.evaluate(script, role)
    try:
        page.wait_for_function('window.__balPick !== null', timeout=120000)
        value = page.evaluate('window.__balPick')
        return None if value.get('cancelled') else value.get('selector')
    finally:
        page.evaluate('() => { if (window.__balPickerCleanup) window.__balPickerCleanup(); }')


def suggest(page, config):
    for key, value in HYPOTHESES.get(config.provider, {}).items():
        if not getattr(config, key) or getattr(config, key) == 'body':
            setattr(config, key, value)
    for role, key in (('composer', 'composer'), ('send_button', 'send')):
        try:
            candidates = rank_candidates(collect(page, role)['candidates'], role)
            if candidates and candidates[0].inside == 'document' and candidates[0].candidate.get('visible'):
                setattr(config, key, candidates[0].selector)
        except Exception:
            pass
    return config


def repair_fields(page, config, ask=input, tell=print, picker=pick):
    labels = {'composer': 'campo de mensagem', 'send': 'botão Enviar',
              'user': 'mensagem do usuário', 'assistant': 'resposta do assistente'}
    tell('Reparo por apontamento. Tenha uma mensagem sua e uma resposta visíveis na conversa.')
    tell('Não envie outra mensagem se a tentativa anterior ficou sem confirmação.')
    for key, label in labels.items():
        if ask(f'Apontar {label}? [s/N] ').strip().lower() in ('s', 'sim'):
            selected = picker(page, label)
            if selected:
                setattr(config, key, selected)
                tell('Seleção atualizada.')
    return config.validate()


def confirmed(ask, message):
    return ask(message + ' [s/N] ').strip().lower() in ('s', 'sim')


def configure(store, name, *, repairing=False, ask=input, tell=print, session_factory=BrowserSession, picker=pick):
    safe_name(name)
    if repairing:
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
    tell('3/5 — Abra o navegador do projeto. Faça login e escolha o modelo manualmente.')
    with session_factory(browser_config(config, store.root)) as session:
        page = session.page(config.url)
        ask('Quando o chat e o modelo estiverem prontos, pressione Enter. ')
        suggest(page, config)
        if repairing or not config.ready:
            tell('4/5 — Aponte os controles sem escrever CSS ou JavaScript.')
            repair_fields(page, config, ask, tell, picker)
        else:
            tell('4/5 — Detectamos hipóteses de controles. O teste abaixo verificará se funcionam.')
        store.save(config)
        tell('Configuração salva. Isso sozinho NÃO comprova compatibilidade.')
        if confirmed(ask, '5/5 — Autoriza UMA mensagem sintética neste chat para testar?'):
            result = exchange(page, config, authorized=True, health_check=True)
        else:
            result = ChatResult('not_authorized')
        receipt = result.receipt(config)
        store.save_status(config.name, receipt)
        tell(receipt['message'])
        tell(receipt['action'])
        return receipt


def check(store, name, *, message=None, ask=input, tell=print, session_factory=BrowserSession):
    config = store.load(name)
    with session_factory(browser_config(config, store.root)) as session:
        page = session.page(config.url)
        ask('Faça login e escolha o modelo no navegador; Enter quando estiver pronto. ')
        if message is None:
            authorized = confirmed(ask, 'Autoriza UMA mensagem sintética de verificação?')
        else:
            authorized = confirmed(ask, 'Autoriza enviar a mensagem informada UMA vez?')
        result = exchange(page, config, message, authorized=authorized, health_check=message is None)
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
