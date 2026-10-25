"""Fluxo assistido por configuração: uma mensagem autorizada, nenhum retry cego."""
from dataclasses import dataclass, field
import hashlib
import json
import re
from urllib.parse import urlsplit
import secrets
import time

from .browser import BrowserConfig, BrowserSession
from .config import origin
from .discovery import ScoredCandidate, install_probe
from .extractor import html_to_markdown, html_to_text
from .observer import WatchConfig, install, mark_sent, read_ui, wait_for_completion
from .sender import SendControlUnavailable, VoiceControlUnavailable, is_voice_control, is_recorded_voice, read_composer, send_message
from .validation import response_instruction, select_output

REMEDIES = {
    'not_configured': ('Configuração incompleta', 'Execute configure ou repair e aponte os campos na página.'),
    'wrong_origin': ('Página diferente da configurada', 'Volte ao chat escolhido; se o site mudou de endereço, refaça configure.'),
    'composer_missing': ('Campo de mensagem não encontrado ou ambíguo', 'Execute repair e clique no campo de mensagem correto.'),
    'draft_present': ('Há um rascunho no campo', 'Envie ou remova o rascunho manualmente antes de tentar de novo.'),
    'send_missing': ('Botão Enviar não ficou disponível com segurança', 'Após preencher, o botão precisa estar visível, habilitado e ser único. Pode ter ficado um rascunho: confira a página antes de tentar de novo. Se necessário, use Corrigir campos.'),
    'send_is_microphone': ('O controle selecionado ainda é de voz/microfone', 'Nenhum clique foi feito. Use Corrigir campos e autorize o rascunho temporário para apontar o botão no estado Enviar. Confira o rascunho deixado antes de outra tentativa.'),
    'google_login_blocked': ('Google recusou o login neste navegador controlado', 'Não continue o apontamento nem repita o login pelo programa. Não há correção garantida aqui; a proteção do Google não será contornada.'),
    'output_invalid': ('Saída configurada não pôde ser lida', 'Execute repair e aponte uma resposta inteira do assistente.'),
    'send_unconfirmed': ('Envio sem confirmação', 'Confira a conversa manualmente. Não reenviamos para evitar duplicação; repare o campo da mensagem do usuário.'),
    'timeout': ('Resposta não confirmada no prazo', 'Confira a página, conexão e modelo. Se respondeu, repare a seleção de saída; não reenviar automaticamente.'),
    'captcha': ('Verificação humana encontrada', 'Resolva a verificação no navegador, sem automatizá-la, e confirme quando terminar.'),
    'login_required': ('Login necessário ou expirado', 'Faça login manualmente no navegador do projeto e escolha o modelo.'),
    'rate_limit': ('Limite de uso do site', 'Aguarde o prazo informado pelo site. Não insistir nem contornar o limite.'),
    'error': ('O site informou um erro', 'Leia a mensagem na página e tente novamente somente após verificar se houve envio.'),
    'contract_invalid': ('Resposta não seguiu o formato solicitado', 'Confira se selecionou a resposta correta. O modelo também pode ter desobedecido; não prova incompatibilidade do chat.'),
    'ambiguous_output': ('Mais de uma saída válida', 'Execute repair para selecionar somente mensagens do assistente, sem contêineres duplicados.'),
    'page_unavailable': ('Página indisponível ou estrutura mudou', 'Confira se a aba está aberta, volte ao chat e execute repair.'),
    'browser_unavailable': ('Não foi possível abrir o navegador', 'Execute doctor; selecione outro navegador instalado ou instale Chromium e as dependências sugeridas.'),
    'not_authorized': ('Nenhuma mensagem enviada', 'Autorize explicitamente uma mensagem de teste para verificar compatibilidade.'),
}


@dataclass
class ChatResult:
    status: str
    compatible: bool = False
    answer: str | None = None
    timings: dict = field(default_factory=dict)
    request_id: str | None = None
    browser_version: str | None = None

    def receipt(self, config):
        title, action = REMEDIES.get(self.status, ('Resposta confirmada nesta execução', 'Modelo escolhido manualmente; repita check se a interface mudar.'))
        return {
            'schema_version': 1, 'name': config.name, 'provider': config.provider,
            'browser': config.browser, 'browser_version': self.browser_version, 'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'config_fingerprint': config_fingerprint(config),
            'status': self.status, 'compatible_in_this_run': self.compatible,
            'message': title, 'action': action, 'timings': self.timings,
            'performance': {
                'capture_budget_ms': 900,
                'within_capture_budget': (self.timings.get('capture_overhead_ms') <= 900
                    if self.timings.get('capture_overhead_ms') is not None else None),
                'api_equivalence': 'not_measured',
            },
            'scope': 'Uma execução; não garante disponibilidade futura ou funcionamento 24/7.',
        }


def config_fingerprint(config):
    from dataclasses import asdict
    return hashlib.sha256(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()


def browser_config(config, root, headless=False):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return BrowserConfig(profile=config.name, profiles_root=root / 'profiles', headless=headless,
                         channel=config.browser if config.browser in ('chrome', 'msedge') else None,
                         attach_existing_chrome=config.session_mode == 'existing_chrome',
                         executable_path=config.executable if config.browser == 'custom' else None)


def google_login_blocked(page):
    """Reconhece recusa explícita, sem tentar autenticar ou contornar o Google."""
    if urlsplit(page.url).hostname != 'accounts.google.com':
        return False
    notice = page.get_by_text(re.compile(
        r'(Esse navegador ou app pode não ser seguro|This browser or app may not be secure)', re.I))
    return any(notice.nth(i).is_visible() for i in range(min(notice.count(), 10)))


def preflight(page, config):
    if google_login_blocked(page):
        return 'google_login_blocked'
    if not config.ready:
        return 'not_configured'
    if origin(page.url) != origin(config.url):
        return 'wrong_origin'
    install_probe(page)
    blocked = read_ui(page, config.root).blocking
    if blocked:
        return blocked
    try:
        locator = page.locator(config.composer)
        if locator.count() != 1 or not locator.is_visible():
            return 'composer_missing'
    except Exception:
        return 'composer_missing'
    # Em alguns chats, Enviar só existe/aparece depois de digitar.
    # A validação rigorosa do botão ocorre após preencher, antes de clicar.
    if not page.locator(config.composer).is_editable():
        return 'composer_missing'
    if read_composer(page.locator(config.composer)):
        return 'draft_present'
    try:
        if page.locator(config.root).count() != 1:
            return 'output_invalid'
        page.locator(config.user).count()
        page.locator(config.assistant).count()
    except Exception:
        return 'output_invalid'
    return None


def exchange(page, config, text=None, *, authorized=False, health_check=False, cancelled=None):
    """Não registra texto. O caller decide exibir answer, nunca inclui no recibo."""
    if not authorized:
        return ChatResult('not_authorized')
    start = time.perf_counter()
    result = ChatResult('page_unavailable')
    try:
        if cancelled and cancelled():
            raise EOFError('Operação interrompida')
        config.validate()
        problem = preflight(page, config)
        if problem:
            return ChatResult(problem)
        outputs_before = page.locator(config.assistant).count()
        locator = page.locator(config.composer)
        data = locator.evaluate('''el => ({tag:el.tagName.toLowerCase(),
                contenteditable:el.getAttribute('contenteditable')})''')
        composer = ScoredCandidate(dict(data, selector=config.composer), 0)
        button = ScoredCandidate({'selector': config.send}, 0)
        request_id = secrets.token_hex(12) if health_check else None
        prompt = (response_instruction(request_id) + ' Use answer igual a browserapi-ok.'
                  if health_check else text)
        if not isinstance(prompt, str) or not prompt.strip():
            return ChatResult('not_authorized')
        install(page, root_selector=config.root, message_selector=config.assistant,
                message_count_baseline=outputs_before)
        if cancelled and cancelled():
            raise EOFError('Operação interrompida')
        mark_sent(page)
        def ready_to_activate():
            deadline = time.monotonic() + min(3, config.timeout_ms / 1000)
            while True:
                if cancelled and cancelled():
                    raise EOFError('Operação interrompida')
                control = page.locator(config.send)
                if control.count() == 1 and control.is_visible() and control.is_enabled():
                    if is_voice_control(control) or is_recorded_voice(control, config):
                        raise VoiceControlUnavailable()
                    return
                if time.monotonic() >= deadline:
                    raise SendControlUnavailable()
                page.wait_for_timeout(100)
        sent = send_message(page, composer, button, prompt,
                            strategies=('type_contenteditable',) if data.get('contenteditable') in ('true', '') else ('fill',),
                            activation=('click_send',), user_selector=config.user,
                            verify_timeout_ms=min(5000, config.timeout_ms), before_activate=ready_to_activate)
        if not sent.success:
            if any(attempt.error == 'VoiceControlUnavailable' for attempt in sent.attempts):
                return ChatResult('send_is_microphone')
            if any(attempt.error == 'SendControlUnavailable' for attempt in sent.attempts):
                return ChatResult('send_missing')
            return ChatResult('send_unconfirmed')
        def check_cancel(*_):
            if cancelled and cancelled():
                raise EOFError('Operação interrompida')
        check_cancel()
        observation = wait_for_completion(page, WatchConfig(stability_window_ms=config.stability_ms,
                                                           timeout_ms=config.timeout_ms), config.root, on_poll=check_cancel)
        if observation.status != 'success':
            block = read_ui(page, config.root).blocking
            return ChatResult(block or ('timeout' if observation.status == 'timeout' else 'page_unavailable'))
        outputs = page.locator(config.assistant)
        fresh = []
        for index in range(outputs_before, outputs.count()):
            item = outputs.nth(index)
            if item.is_visible():
                fresh.append(item.inner_html())
        if not fresh:
            return ChatResult('output_invalid')
        if health_check:
            texts = [html_to_text(html) for html in fresh]
            selection = select_output(texts, request_id)
            if selection.status != 'selected':
                return ChatResult('ambiguous_output' if selection.status == 'ambiguous' else 'contract_invalid')
            # Uma resposta correta ao desafio, não só JSON de esquema correto.
            value = json.loads(texts[selection.index])
            if value['answer'] != 'browserapi-ok':
                return ChatResult('contract_invalid')
            answer = value['answer']
        else:
            if len(fresh) != 1:
                return ChatResult('ambiguous_output')
            answer = html_to_markdown(fresh[0])
        summary = page.evaluate('window.__bal.streamSummary()')
        first = summary.get('first_token_ms')
        sent_ms = summary.get('sent_ms')
        result = ChatResult('success', True, answer=answer, request_id=request_id, timings={
            'total_ms': round((time.perf_counter() - start) * 1000, 1),
            'ttft_dom_ms': round(max(0, first - sent_ms), 1) if first is not None and sent_ms is not None else None,
            'capture_overhead_ms': summary.get('since_last_mutation_ms'),
            'fill_ms': round(sent.fill_ms, 1), 'send_ms': round(sent.send_ms, 1),
        })
        result.browser_version = page.context.browser.version
        return result
    except (EOFError, KeyboardInterrupt):
        raise
    except Exception:
        # Playwright inclui texto/HTML/URLs em exceções: não persistir o detalhe.
        return ChatResult('page_unavailable')
    finally:
        try:
            from .observer import reset
            reset(page)
        except Exception:
            pass
