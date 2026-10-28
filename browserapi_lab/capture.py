"""Leitura da conversa em camadas — uma fonte de verdade, três forças.

Motivo (dossiê ``pesquisa/2026-10-28-arquitetura-captura-e-ui.md``): depender de
um seletor apontado à mão quebra a cada mudança de layout e produziu os dois
últimos incidentes (resposta lida como pergunta, "envio não confirmado" com o
envio feito). Em vez de adivinhar o DOM, este módulo lê na ordem da força da
evidência:

1. ``marker``    — o site diz o papel (``data-message-author-role``, ``user-query``,
   ``model-response``, ``data-role``, ``data-author``, rótulo acessível);
2. ``framework`` — o app é React e o próprio objeto da mensagem diz o papel
   (``__reactProps$…``/``__reactFiber$…`` → ``memoizedProps``). É leitura do que
   já está na página: nenhuma integração nova, nenhum script do site;
3. ``structure`` — só a geometria/ordem: turnos do container da conversa, papel
   por alinhamento e, na falta dele, alternância. É o último recurso e vem
   marcado como frágil.

O seletor apontado pelo usuário continua valendo: quando ele lê a conversa de
forma limpa, é ele que manda (o mapeamento foi conferido por uma pessoa). Quando
ele mistura camadas ou perde mensagens, a leitura em camadas assume e o painel
diz exatamente isso — em vez de falhar com "envio não confirmado".

Nada aqui escreve na página, envia mensagem ou guarda texto: o retorno é usado
para conferir o mapeamento e confirmar o envio, não para histórico.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

CAPTURE_VERSION = 3
LAYERS = ('marker', 'framework', 'structure')
STRONG_LAYERS = ('marker', 'framework')
MAX_ITEMS = 80
MAX_TEXT = 400

# Um único script: mede as duas leituras (apontada e em camadas) e devolve as
# duas. Escolher em Python deixa a decisão testável sem navegador.
CAPTURE_SCRIPT = r"""(args) => {
  const options = args || {};
  const userSelector = options.user || '';
  const assistantSelector = options.assistant || '';
  const MAX_ITEMS = 80;
  const SKIP = 'button,[role="button"],script,style,noscript,template,[aria-hidden="true"],[hidden],'
    + '.cdk-visually-hidden,.screen-reader-only,.sr-only,.visually-hidden';
  const MARKER_SELECTOR = '[data-message-author-role],[data-message-role],user-query,model-response,'
    + '[data-role="user"],[data-role="assistant"],[data-role=user],[data-role=assistant],'
    + '[data-author],[data-sender]';
  // "Casca" da página: compositor e controles. Um container de conversa não tem
  // formulário dentro; sem isso, uma barra lateral cheia de <label> virava
  // "conversa" (dois turnos de texto uniforme) e a última resposta saía errada.
  const SHELL = 'textarea,[contenteditable="true"],[contenteditable=""],[role="textbox"],'
    + 'button[type="submit"],input[type="submit"],select,input,label,[role="combobox"]';

  const visible = el => {
    if (!el || !el.getBoundingClientRect) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 2 || rect.height <= 2) return false;
    const style = getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
  };
  // Rótulos de papel/avatar/cópia são cromo, não conversa: o Gemini inclusive
  // repete "Gemini said" em nó visível só para leitor de tela. Mesma regra do
  // probe (chat_probe.js), para texto e HTML saírem iguais por qualquer caminho.
  const CHROME = /(^|[-_])(role|author|avatar|actions?|toolbar|feedback|copy|copiar|menu|label|caption)([-_]|$)/i;
  const clean = el => {
    const clone = el.cloneNode(true);
    try {
      clone.querySelectorAll(SKIP).forEach(node => node.remove());
      clone.querySelectorAll('[class]').forEach(node => {
        if (!CHROME.test(node.getAttribute('class') || '')) return;
        const label = String(node.textContent || '').replace(/\s+/g, ' ').trim();
        if (label.length <= 40) node.remove();
      });
    } catch (error) { /* nó hostil: segue com o que deu */ }
    return clone;
  };
  const textOf = el => {
    if (!el) return '';
    const clone = clean(el);
    const raw = (clone.innerText !== undefined && clone.innerText !== null) ? clone.innerText : clone.textContent;
    return String(raw || '').replace(/\s+/g, ' ').trim();
  };
  const htmlOf = el => {
    if (!el) return '';
    const clone = clean(el);
    try { return clone.innerHTML || ''; } catch (error) { return ''; }
  };
  const shortened = value => {
    const text = String(value || '');
    return text.length > 400 ? text.slice(0, 399) + '…' : text;
  };
  const depth = el => {
    let level = 0;
    let node = el;
    while (node && node.parentElement) { level += 1; node = node.parentElement; }
    return level;
  };
  const query = selector => {
    if (!selector) return [];
    try { return [...document.querySelectorAll(selector)]; } catch (error) { return []; }
  };
  // Camada interna do mesmo balão não é outra mensagem (Gemini: model-response
  // e o <p> de dentro casavam os dois). Remove quem está dentro de outro.
  const outermost = nodes => nodes.filter(el => !nodes.some(other => other !== el && other.contains(el)));
  const byDocument = nodes => nodes.slice().sort((a, b) =>
    (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);

  const family = value => {
    const word = String(value || '').toLowerCase().replace(/[^a-z]/g, '');
    if (!word) return '';
    if (['user', 'human', 'you', 'me', 'question', 'prompt', 'pergunta', 'usuario', 'utilizador'].includes(word)) return 'user';
    if (['assistant', 'model', 'ai', 'bot', 'response', 'answer', 'resposta', 'chat', 'llm', 'gemini', 'gpt', 'claude'].includes(word)) return 'assistant';
    return '';
  };

  const markerRole = el => {
    if (!el || !el.tagName) return '';
    const tag = el.tagName.toLowerCase();
    if (tag === 'user-query' || tag === 'user-message') return 'user';
    if (tag === 'model-response' || tag === 'assistant-message') return 'assistant';
    for (const attribute of ['data-message-author-role', 'data-message-role', 'data-role', 'data-author', 'data-sender']) {
      const found = family(el.getAttribute && el.getAttribute(attribute));
      if (found) return found;
    }
    // Rótulo acessível: "You said", "Gemini said", "Você disse".
    const label = String((el.getAttribute && (el.getAttribute('aria-label') || '')) || '');
    const said = family((label.match(/^\s*([^\s]+)/) || [])[1]);
    if (said) return said;
    return '';
  };

  // Estado do React: o objeto da mensagem sabe o papel; a chave é aleatória por
  // sessão, então procuramos pelo prefixo, nunca pelo nome completo.
  const findRole = (value, level) => {
    if (!value || typeof value !== 'object' || level > 3) return '';
    for (const field of ['role', 'author', 'sender', 'type', 'kind', 'from']) {
      const found = family(value[field]);
      if (found) return found;
    }
    if (value.isUser === true) return 'user';
    if (value.isUser === false && value.message !== undefined) return 'assistant';
    for (const field of ['message', 'props', 'memoizedProps', 'data', 'payload', 'content', 'stateNode']) {
      const found = findRole(value[field], level + 1);
      if (found) return found;
    }
    return '';
  };
  const frameworkRole = el => {
    let keys = [];
    try { keys = Object.keys(el); } catch (error) { return ''; }
    for (const key of keys) {
      if (!/^__(reactProps|reactFiber)\$/.test(key)) continue;
      try {
        const found = findRole(el[key], 0);
        if (found) return found;
      } catch (error) { /* objeto hostil: segue */ }
    }
    return '';
  };

  // Um pedaço apontado no passado (ex.: o <p class="first-token"> do Gemini)
  // não é a resposta: sobe ao balão inteiro antes de ler o texto.
  const climbToTurn = el => {
    const root = transcriptRoot();
    if (root && root.contains(el)) {
      let node = el;
      while (node && node.parentElement && node.parentElement !== root && root.contains(node.parentElement)) {
        node = node.parentElement;
      }
      if (node && node.parentElement === root) return node;
    }
    let node = el;
    for (let level = 0; node && node.parentElement && level < 6; level += 1) {
      if (markerRole(node)) return node;
      node = node.parentElement;
    }
    return el;
  };
  const LEAF = 'p,span,code,em,strong,a,li,h1,h2,h3,h4,h5,h6,blockquote,pre,td,div.md,div.markdown';
  const configuredBubble = el => {
    if (!el || !el.closest) return el;
    let marked = null;
    try { marked = el.closest(MARKER_SELECTOR); } catch (error) { marked = null; }
    if (marked && marked !== el) return marked;
    if (el.matches && el.matches(LEAF) && el.parentElement) return climbToTurn(el);
    return el;
  };

  const markerItems = () => {
    const found = [];
    const seen = new Set();
    for (const el of query(MARKER_SELECTOR)) {
      if (!visible(el) || seen.has(el)) continue;
      const role = markerRole(el);
      if (!role) continue;
      seen.add(el);
      found.push({el, role});
    }
    // Só o balão externo: o pedaço de dentro do mesmo balão não é outro turno.
    const nodes = outermost(found.map(item => item.el));
    const roleOf = new Map(found.map(item => [item.el, item.role]));
    return byDocument(nodes).map(el => ({el, role: roleOf.get(el) || markerRole(el)}))
      .filter(item => item.role === 'user' || item.role === 'assistant');
  };

  const frameworkItems = () => {
    const found = [];
    for (const el of query('[data-message-author-role],div,article,li,section')) {
      if (found.length >= MAX_ITEMS * 2) break;
      if (!visible(el)) continue;
      const role = frameworkRole(el);
      if (!role) continue;
      found.push({el, role});
    }
    const nodes = outermost(found.map(item => item.el));
    const map = new Map(found.map(item => [item.el, item.role]));
    return byDocument(nodes).filter(el => visible(el)).map(el => ({el, role: map.get(el) || ''}));
  };

  const looksLikeTurn = el => {
    if (!el || el.nodeType !== 1) return false;
    if (!visible(el)) return false;
    if (el.matches('button,a,nav,header,footer,aside,[role="navigation"]')) return false;
    if (textOf(el).length === 0) return false;
    return el.getBoundingClientRect().height > 18;
  };

  // Container da conversa: a lista de turnos mais longa que não tem o
  // compositor dentro (barra de digitação não é conversa).
  const transcriptRoot = () => {
    let best = null;
    let bestScore = 0;
    for (const el of query('main,section,div,ol,ul,[role="list"],[role="log"]')) {
      const kids = [...el.children];
      if (kids.length < 2) continue;
      const turns = kids.filter(looksLikeTurn);
      // Três turnos no mínimo: com dois, qualquer par de blocos de texto da
      // página (conversa + compositor) virava "conversa" e a última resposta
      // saía errada.
      if (turns.length < 3) continue;
      const ratio = turns.length / kids.length;
      if (ratio < 0.6) continue;
      // Turno que contém o compositor não é turno de conversa.
      if (turns.some(kid => kid.querySelector(SHELL))) continue;
      // Turnos de uma conversa têm a mesma forma: mesma tag ou a mesma classe.
      // Sem isso, "aside + main" também parecia uma conversa de dois turnos.
      const tags = new Set(turns.map(kid => kid.tagName));
      const classes = new Map();
      for (const kid of turns) {
        for (const name of String(kid.className || '').split(/\s+/)) {
          if (name) classes.set(name, (classes.get(name) || 0) + 1);
        }
      }
      const commonClass = [...classes.values()].some(count => count >= Math.ceil(turns.length * 0.6));
      if (tags.size > 1 && !commonClass) continue;
      const total = turns.reduce((sum, kid) => sum + textOf(kid).length, 0);
      if (total < 20) continue;
      let score = turns.length * 100 * ratio - depth(el);
      score += Math.min(20, total / 200);
      if (el.querySelector(SHELL)) score *= 0.25;
      if (score > bestScore) { best = el; bestScore = score; }
    }
    return best;
  };

  const alignHint = el => {
    let node = el;
    for (let level = 0; node && level < 3; level += 1, node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.justifyContent === 'flex-end' || style.textAlign === 'right') return 'right';
      if (style.alignSelf === 'flex-end' || style.alignSelf === 'end') return 'right';
      if (style.marginLeft === 'auto' && style.marginRight !== 'auto') return 'right';
      if (style.justifyContent === 'flex-start' && level === 0) return 'left';
    }
    return '';
  };

  const structureItems = () => {
    const root = transcriptRoot();
    if (!root) return [];
    const turns = [...root.children].filter(looksLikeTurn).slice(0, MAX_ITEMS);
    if (turns.length < 2) return [];
    const sides = turns.map(alignHint);
    const rightCount = sides.filter(side => side === 'right').length;
    const leftCount = sides.filter(side => side === 'left').length;
    // Alinhamento só desempata: há sites com resposta em card de largura total.
    let startsWithUser = true;
    if (rightCount > leftCount && sides[0] !== 'right') startsWithUser = false;
    if (sides[0] === 'right' && rightCount > 0) startsWithUser = true;
    return turns.map((el, index) => ({
      el, role: (index % 2 === 0) === startsWithUser ? 'user' : 'assistant',
    }));
  };

  const read = (items, layer) => {
    const seen = new Set();
    const list = [];
    const roles = new Map();
    for (const item of items) if (item && item.el) roles.set(item.el, item.role);
    for (const el of byDocument([...roles.keys()])) {
      if (!el || seen.has(el)) continue;
      seen.add(el);
      list.push({el, role: roles.get(el), text: textOf(el), layer});
    }
    return list.filter(item => item.role === 'user' || item.role === 'assistant').slice(0, MAX_ITEMS);
  };

  const counts = items => ({
    user: items.filter(item => item.role === 'user').length,
    assistant: items.filter(item => item.role === 'assistant').length,
  });

  const layeredReading = () => {
    for (const [layer, resolver] of [['marker', markerItems], ['framework', frameworkItems], ['structure', structureItems]]) {
      let items = [];
      try { items = read(resolver(), layer); } catch (error) { items = []; }
      const total = counts(items);
      if (total.user >= 1 && total.assistant >= 1) {
        return {layer, items, counts: total};
      }
    }
    return {layer: 'none', items: [], counts: {user: 0, assistant: 0}};
  };

  const configuredReading = () => {
    // Sobe cada acerto ao balão inteiro: apontar um pedaço não pode capturar
    // um pedaço (foi o defeito relatado com dois <span> na mesma resposta).
    const rawUsers = query(userSelector).filter(visible);
    const rawAnswers = query(assistantSelector).filter(visible);
    const users = outermost(rawUsers.map(configuredBubble).filter(Boolean));
    const answers = outermost(rawAnswers.map(configuredBubble).filter(Boolean));
    const items = [];
    for (const el of users) items.push({el, role: 'user'});
    for (const el of answers) items.push({el, role: 'assistant'});
    const ordered = byDocument(items.map(item => item.el));
    const map = new Map(items.map(item => [item.el, item]));
    const overlap = rawUsers.filter(el => rawAnswers.includes(el)).length
      + users.filter(el => answers.includes(el)).length;
    return {
      items: ordered.map(el => ({role: map.get(el).role, text: textOf(el), layer: 'configured'})),
      overlap,
    };
  };

  const reading = layeredReading();
  let userStateCache = null;
  const api = {
    version: 3,
    layer: () => reading.layer,
    messages: () => reading.items.map(item => ({role: item.role, text: shortened(item.text)})),
    counts: () => reading.counts,
    // Relê na hora: o DOM muda a cada token, e um retrato do momento da
    // instalação nunca confirmaria o envio.
    last: (role, hint) => {
      let item = null;
      let layer = 'none';
      const fresh = layeredReading();
      const list = fresh.items.filter(entry => entry.role === role);
      if (list.length) {
        const ordered = byDocument(list.map(entry => entry.el));
        const target = ordered[ordered.length - 1];
        item = list.find(entry => entry.el === target) || null;
        layer = fresh.layer;
      }
      if (!item && hint) {
        // Sem camada utilizável: cai no que a pessoa apontou, subindo ao balão.
        const hinted = byDocument(outermost(query(hint).filter(visible).map(configuredBubble).filter(Boolean)));
        if (hinted.length) { item = {el: hinted[hinted.length - 1]}; layer = 'configured'; }
      }
      return item ? {html: htmlOf(item.el), text: textOf(item.el), layer} : null;
    },
    // Estado das mensagens do usuário com um seletor apontado como dica.
    // Caminho barato primeiro (uma consulta por marcador); estado do React e
    // layout só quando a página não declara papel — isso roda a cada 50 ms
    // durante a confirmação do envio.
    userState: hint => {
      // Durante a confirmação do envio isto é lido a cada 50 ms. Em página sem
      // marcador, a leitura completa custa caro: reaproveita por 250 ms.
      const now = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
      const cacheKey = String(hint || '');
      if (userStateCache && userStateCache.key === cacheKey && now - userStateCache.at < 250) {
        return userStateCache.value;
      }
      const hinted = outermost(query(hint || '').filter(visible)).filter(el => {
        const role = markerRole(el);
        return role !== 'assistant';
      });
      let chosen = [];
      let layer = 'none';
      try { chosen = markerItems().filter(item => item.role === 'user'); } catch (error) { chosen = []; }
      if (chosen.length) {
        layer = 'marker';
      } else {
        const fresh = layeredReading();
        chosen = fresh.items.filter(item => item.role === 'user');
        layer = fresh.layer;
      }
      if (hinted.length > chosen.length) { chosen = hinted.map(el => ({el})); layer = 'configured'; }
      const ordered = byDocument(chosen.map(item => item.el));
      const last = ordered.length ? ordered[ordered.length - 1] : null;
      const value = {count: ordered.length, last: last ? textOf(last) : null, layer};
      userStateCache = {key: cacheKey, at: now, value};
      return value;
    },
  };
  window.__balCapture = api;
  return {
    version: 3,
    layered: {
      layer: reading.layer,
      items: reading.items.map(item => ({role: item.role, text: shortened(item.text)})),
      counts: reading.counts,
    },
    configured: configuredReading(),
    sources: {
      marker: (() => { try { return outermost(query(MARKER_SELECTOR)).filter(el => markerRole(el)).length; } catch (error) { return 0; } })(),
    },
  };
}"""


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ''
    return ' '.join(value.split())[:MAX_TEXT]


def _items(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    items = []
    for entry in value[:MAX_ITEMS]:
        if not isinstance(entry, dict):
            continue
        role = entry.get('role')
        if role not in ('user', 'assistant'):
            continue
        items.append({'role': role, 'text': _text(entry.get('text'))})
    return items


def _balanced(items: List[Dict[str, str]]) -> bool:
    users = sum(1 for item in items if item['role'] == 'user')
    answers = sum(1 for item in items if item['role'] == 'assistant')
    return users > 0 and answers > 0 and users == answers


def _alternating(items: List[Dict[str, str]]) -> bool:
    return all(items[index]['role'] != items[index - 1]['role'] for index in range(1, len(items)))


def configured_is_clean(items: List[Dict[str, str]], overlap: int) -> bool:
    """A leitura do que a pessoa apontou está limpa?

    Limpa = sem elemento casando nos dois papéis, mesmo número dos dois lados e
    papéis alternados. Fora disso, ela não serve para confirmar envio: contar
    pergunta como resposta é o que gerava falso "envio não confirmado".
    """
    return bool(items) and not overlap and _balanced(items) and _alternating(items)


def choose_reading(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Escolhe entre a leitura apontada e a leitura em camadas.

    Regra (dossiê §3):

    * apontada limpa → ela manda (foi conferida por uma pessoa);
    * apontada suja e camada forte (``marker``/``framework``) equilibrada → a
      camada manda, com aviso explícito;
    * senão → apontada, mesmo suja, para a conferência poder recusar e explicar.
    """
    payload = payload if isinstance(payload, dict) else {}
    layered = payload.get('layered') if isinstance(payload.get('layered'), dict) else {}
    configured = payload.get('configured') if isinstance(payload.get('configured'), dict) else {}
    overlap = configured.get('overlap')
    overlap = overlap if isinstance(overlap, int) and overlap >= 0 else 0
    configured_items = _items(configured.get('items'))
    layer = layered.get('layer')
    layer = layer if layer in LAYERS else 'none'
    layered_items = _items(layered.get('items')) if layer != 'none' else []

    if configured_items and configured_is_clean(configured_items, overlap):
        return {'items': configured_items, 'overlap': overlap, 'layer': 'configured',
                'fallback': False, 'warnings': []}

    if layer in STRONG_LAYERS and _balanced(layered_items) and _alternating(layered_items):
        return {'items': layered_items, 'overlap': 0, 'layer': layer, 'fallback': True,
                'warnings': [
                    'O mapeamento apontado não lê as mensagens de forma coerente '
                    f'({sum(1 for item in configured_items if item["role"] == "user")} pergunta(s) e '
                    f'{sum(1 for item in configured_items if item["role"] == "assistant")} resposta(s)); '
                    f'usando a leitura pelo {_layer_name(layer)} do próprio chat. '
                    'Refaça os balões quando puder.']}

    return {'items': configured_items, 'overlap': overlap, 'layer': 'configured',
            'fallback': False, 'warnings': []}


def _layer_name(layer: str) -> str:
    return {'marker': 'papel declarado na página', 'framework': 'estado do app (React)',
            'structure': 'layout (frágil)'}.get(layer, 'leitura em camadas')


def summarize(report: Dict[str, Any]) -> Dict[str, Any]:
    """Resumo curto do que a página informa — para o painel, sem texto da conversa."""
    report = report if isinstance(report, dict) else {}
    items = report.get('items') or []
    users = sum(1 for item in items if item.get('role') == 'user')
    answers = sum(1 for item in items if item.get('role') == 'assistant')
    return {'layer': report.get('layer', 'none'), 'fallback': bool(report.get('fallback')),
            'users': users, 'answers': answers, 'total': len(items),
            'overlap': report.get('overlap', 0)}


def ensure(page: Any) -> None:
    """Instala o leitor na página (idempotente). Só leitura, nada é alterado.

    A checagem é barata de propósito: isto é chamado a cada leitura de estado
    durante a confirmação do envio, e reavaliar o script inteiro ali custaria
    uma varredura do DOM a cada 50 ms.
    """
    if page is None or not hasattr(page, 'evaluate'):
        return
    try:
        if page.evaluate('() => !!(window.__balCapture && window.__balCapture.version === 3)'):
            return
    except Exception:
        return
    try:
        page.evaluate(CAPTURE_SCRIPT, {'user': '', 'assistant': ''})
    except Exception:
        pass


def report(page: Any, user: str = '', assistant: str = '') -> Dict[str, Any]:
    """Lê a conversa na página somando as duas leituras e escolhendo uma.

    Devolve ``{'items', 'overlap', 'layer', 'fallback', 'warnings'}``. Tolerante
    a páginas de teste que já devolvem um relatório pronto: nada aqui depende do
    formato exato do script para não transformar teste em contrato do DOM.
    """
    if page is None or not hasattr(page, 'evaluate'):
        return {'items': [], 'overlap': 0, 'layer': 'none', 'fallback': False, 'warnings': []}
    try:
        payload = page.evaluate(CAPTURE_SCRIPT, {'user': user or '', 'assistant': assistant or ''})
    except Exception:
        return {'items': [], 'overlap': 0, 'layer': 'none', 'fallback': False, 'warnings': []}
    if not isinstance(payload, dict):
        return {'items': [], 'overlap': 0, 'layer': 'none', 'fallback': False, 'warnings': []}
    if 'layered' not in payload and 'configured' not in payload:
        # Relatório pronto (harness antigo): normaliza e segue.
        items = _items(payload.get('items'))
        overlap = payload.get('overlap')
        return {'items': items, 'overlap': overlap if isinstance(overlap, int) else 0,
                'layer': payload.get('layer') if payload.get('layer') in LAYERS else 'none',
                'fallback': False, 'warnings': list(payload.get('warnings') or [])}
    return choose_reading(payload)


def messages(page: Any, user: str = '', assistant: str = '') -> List[Dict[str, str]]:
    return report(page, user, assistant)['items']


def last_answer(page: Any, selector: str = '') -> Optional[Dict[str, str]]:
    """Balão inteiro da última resposta lida — a captura do texto em si.

    ``selector`` é só o último recurso: quando nenhuma camada reconhece a
    conversa, o que a pessoa apontou é usado (subindo ao balão inteiro).
    """
    if page is None or not hasattr(page, 'evaluate'):
        return None
    try:
        value = page.evaluate('(args) => (window.__balCapture ? window.__balCapture.last("assistant", args.hint) : null)',
                              {'hint': selector or ''})
    except Exception:
        return None
    if not isinstance(value, dict):
        return None
    html = value.get('html')
    text = value.get('text')
    return {'html': html if isinstance(html, str) else '',
            'text': _text(text), 'layer': value.get('layer') if value.get('layer') in LAYERS + ('configured',) else 'none'}


def user_state(page: Any, selector: str = '') -> Dict[str, Any]:
    """Estado das mensagens do usuário — evidência de envio, não histórico."""
    fallback = {'count': 0, 'last': None, 'layer': 'none'}
    if page is None or not hasattr(page, 'evaluate'):
        return fallback
    try:
        value = page.evaluate('(hint) => (window.__balCapture ? window.__balCapture.userState(hint) : null)',
                              selector or '')
    except Exception:
        return fallback
    if not isinstance(value, dict):
        return fallback
    count = value.get('count')
    last = value.get('last')
    layer = value.get('layer')
    return {'count': count if isinstance(count, int) and count >= 0 else 0,
            'last': last if isinstance(last, str) else None,
            'layer': layer if isinstance(layer, str) else 'none'}
