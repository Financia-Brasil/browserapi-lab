"""Fluxo assistido por configuração: uma mensagem autorizada, nenhum retry cego."""
from dataclasses import dataclass, field
import hashlib
import json
import secrets
import time

from .browser import BrowserConfig, BrowserSession
from .config import origin
from .discovery import ScoredCandidate, install_probe
from .extractor import html_to_markdown, html_to_text
from .observer import WatchConfig, install, mark_sent, read_ui, wait_for_completion
from .sender import read_composer, send_message
from .validation import response_instruction, select_output

REMEDIES = {
    'not_configured': ('Configuração incompleta', 'Execute configure ou repair e aponte os campos na página.'),
    'wrong_origin': ('Página diferente da configurada', 'Volte ao chat escolhido; se o site mudou de endereço, refaça configure.'),
    'composer_missing': ('Campo de mensagem não encontrado ou ambíguo', 'Execute repair e clique no campo de mensagem correto.'),
    'draft_present': ('Há um rascunho no campo', 'Envie ou remova o rascunho manualmente antes de tentar de novo.'),
    'send_missing': ('Botão de envio não encontrado ou ambíguo', 'Execute repair e aponte o botão Enviar.'),
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

    def receipt(self, config):
        title, action = REMEDIES.get(self.status, ('Resposta confirmada nesta execução', 'Modelo escolhido manualmente; repita check se a interface mudar.'))
        return {
            'schema_version': 1, 'name': config.name, 'provider': config.provider,
            'browser': config.browser, 'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'config_fingerprint': config_fingerprint(config),
            'status': self.status, 'compatible_in_this_run': self.compatible,
            'message': title, 'action': action, 'timings': self.timings,
            'scope': 'Uma execução; não garante disponibilidade futura ou funcionamento 24/7.',
        }


def config_fingerprint(config):
    from dataclasses import asdict
    return hashlib.sha256(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()


def browser_config(config, root, headless=False):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return BrowserConfig(profile=config.name, profiles_root=root / 'profiles', headless=headless,
                         channel=config.browser if config.browser in ('chrome', 'msedge') else None,
                         executable_path=config.executable if config.browser == 'custom' else None)


def preflight(page, config):
    if not config.ready:
        return 'not_configured'
    if origin(page.url) != origin(config.url):
        return 'wrong_origin'
    install_probe(page)
    blocked = read_ui(page, config.root).blocking
    if blocked:
        return blocked
    for key, failure in (('composer', 'composer_missing'), ('send', 'send_missing')):
        try:
            locator = page.locator(getattr(config, key))
            if locator.count() != 1 or not locator.is_visible():
                return failure
        except Exception:
            return failure
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


def exchange(page, config, text=None, *, authorized=False, health_check=False):
    """Não registra texto. O caller decide exibir answer, nunca inclui no recibo."""
    if not authorized:
        return ChatResult('not_authorized')
    start = time.perf_counter()
    result = ChatResult('page_unavailable')
    try:
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
        mark_sent(page)
        sent = send_message(page, composer, button, prompt,
                            strategies=('type_contenteditable',) if data.get('contenteditable') in ('true', '') else ('fill',),
                            activation=('click_send',), user_selector=config.user,
                            verify_timeout_ms=min(5000, config.timeout_ms))
        if not sent.success:
            return ChatResult('send_unconfirmed')
        observation = wait_for_completion(page, WatchConfig(stability_window_ms=config.stability_ms,
                                                           timeout_ms=config.timeout_ms), config.root)
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
        return result
    except Exception:
        # Playwright inclui texto/HTML/URLs em exceções: não persistir o detalhe.
        return ChatResult('page_unavailable')
    finally:
        try:
            from .observer import reset
            reset(page)
        except Exception:
            pass
