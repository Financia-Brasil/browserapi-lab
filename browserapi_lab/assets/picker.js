/* Seleção visual guiada: não digita, não envia e não altera controles do site.
 *
 * Contrato (ADR-023):
 *  - o painel diz o PASSO e o que clicar;
 *  - antes de confirmar, o usuário VÊ o texto que será capturado;
 *  - para mensagens, a seleção sobe ao BALÃO inteiro (o Gemini divide a
 *    resposta em vários <span>: apontar um pedaço não pode virar a resposta);
 *  - "Pular este campo" devolve {cancelled:true} e o mapeamento segue;
 *  - "Cancelar mapeamento" devolve {abort:true} e o fluxo para.
 */
(options) => {
  if (window.__balPickerCleanup) window.__balPickerCleanup();
  window.__balPick = null;

  const config = typeof options === 'string' ? { role: options } : (options || {});
  const role = config.role || 'elemento';
  const step = config.step || '';
  const hint = config.hint || '';
  const composerRole = role === 'campo de mensagem';
  const buttonRole = role === 'botão Enviar' || role === 'botão de comando de voz';
  const messageRole = role === 'mensagem do usuário' || role === 'resposta do assistente';

  const EDITABLE = 'textarea:not([readonly]):not(:disabled),input:not([type]):not([readonly]):not(:disabled),'
    + 'input[type=text]:not([readonly]):not(:disabled),input[type=search]:not([readonly]):not(:disabled),'
    + '[contenteditable]:not([contenteditable=false]),[role=textbox]';
  const CLICKABLE = 'button,[role=button],input[type=submit]';
  const ROLE_MARK = 'user-query,model-response,[data-message-author-role],[data-role="user"],[data-role="assistant"],'
    + '[data-role=user],[data-role=assistant],[data-author]';
  const GENERIC_SIGNAL = /(^|[-_ ])(message|mensagem|response|resposta|answer|markdown|bubble|article)([-_ ]|$)/i;
  const INLINE_TAGS = { SPAN: 1, A: 1, STRONG: 1, EM: 1, B: 1, I: 1, CODE: 1, MARK: 1, SMALL: 1, S: 1, U: 1, TIME: 1 };
  const defaultHint = messageRole
    ? 'Clique em qualquer parte do balão; pegamos o balão inteiro, não só o pedaço.'
    : composerRole ? 'Clique na caixa de texto onde você escreve a mensagem (a de baixo, vazia).'
      : buttonRole ? 'Clique no botão indicado na pergunta. Nada é enviado pelo apontamento.'
        : 'Clique no elemento dentro da janela do chat.';

  const banner = document.createElement('div');
  banner.id = '__browserapi_picker';
  banner.setAttribute('role', 'region');
  banner.setAttribute('aria-label', (step ? 'Passo ' + step + ': ' : '') + 'Selecionar ' + role);
  /* Tamanho fixo e sem barra de rolagem (pedido do uso real: com rolagem o
   * conteúdo saía da vista e o painel cobria o balão). O conteúdo é compacto
   * por construção — três linhas de conferência — e o painel é arrastável.
   * Tudo por propriedade CSSOM: CSP com style-src restrito não bloqueia isto,
   * enquanto style="…"/cssText seria bloqueado. */
  Object.assign(banner.style, { position: 'fixed', top: '16px', right: '16px', width: '392px',
    maxWidth: 'calc(100vw - 32px)', boxSizing: 'border-box', zIndex: '2147483647', background: '#fff',
    color: '#1b3029', border: '2px solid #146c50', borderRadius: '8px', padding: '12px',
    font: '14px/1.4 system-ui', boxShadow: '0 4px 24px #0003', overflow: 'hidden',
    // O painel nunca rouba o clique da página: passar por cima do campo que a
    // pessoa precisa apontar continua funcionando. Só os controles e a faixa
    // de arraste respondem ao ponteiro (definido logo abaixo).
    pointerEvents: 'none' });

  const top = document.createElement('div');
  // A faixa do título é `none` como o resto do corpo: se ela recebesse o
  // ponteiro, o <strong> do título interceptaria o clique no alvo sempre que o
  // painel estivesse por cima dele (foi assim que o CI reprovou: "subtree
  // intercepts pointer events"). Arrasta-se pela alça, que é pequena.
  Object.assign(top.style, { display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'nowrap',
    userSelect: 'none', paddingBottom: '4px', pointerEvents: 'none' });
  const grip = document.createElement('span');
  grip.setAttribute('data-picker-grip', '');
  grip.setAttribute('aria-hidden', 'true');
  grip.textContent = '⠿';
  Object.assign(grip.style, { cursor: 'move', pointerEvents: 'auto', fontSize: '18px',
    lineHeight: '1', padding: '4px 2px', color: '#5d6f66' });
  grip.title = 'Arraste para mover o painel';
  const title = document.createElement('strong');
  title.textContent = 'Selecionar: ' + role;
  title.style.fontSize = '16px';
  top.append(grip, title);
  if (step) {
    const chip = document.createElement('span');
    chip.textContent = 'Passo ' + step;
    Object.assign(chip.style, { fontSize: '12px', fontWeight: '600', letterSpacing: '.04em',
      textTransform: 'uppercase', color: '#146c50', border: '1px solid #9dc3b2', borderRadius: '999px',
      padding: '2px 8px', whiteSpace: 'nowrap' });
    top.append(chip);
  }

  const guide = document.createElement('p');
  guide.textContent = hint || defaultHint;
  Object.assign(guide.style, { margin: '8px 0 4px', color: '#33463e' });

  const previewBox = document.createElement('div');
  Object.assign(previewBox.style, { margin: '8px 0', padding: '8px 10px', borderRadius: '6px',
    background: '#f1f6f3', border: '1px solid #d5e4dc', font: '13px/1.45 system-ui', color: '#1b3029' });
  const previewLabel = document.createElement('span');
  previewLabel.textContent = 'Vai capturar: ';
  previewLabel.style.fontWeight = '600';
  const previewText = document.createElement('span');
  previewText.textContent = 'nada ainda — clique em uma área destacada.';
  Object.assign(previewText.style, { wordBreak: 'break-word', display: '-webkit-box',
    WebkitLineClamp: '2', WebkitBoxOrient: 'vertical', overflow: 'hidden' });
  previewBox.append(previewLabel, previewText);

  const status = document.createElement('p');
  status.setAttribute('aria-live', 'polite');
  Object.assign(status.style, { margin: '8px 0', minHeight: '20px', color: '#33463e' });

  const controls = document.createElement('div');
  Object.assign(controls.style, { display: 'flex', gap: '8px', flexWrap: 'wrap' });
  const secondary = document.createElement('div');
  Object.assign(secondary.style, { display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '12px',
    borderTop: '1px solid #e3ebe7', paddingTop: '10px' });
  banner.append(top, guide, previewBox, status, controls, secondary);

  const marks = document.createElement('div');
  marks.id = '__browserapi_picker_marks';
  Object.assign(marks.style, { position: 'fixed', inset: '0', pointerEvents: 'none', zIndex: '2147483646' });
  document.body.append(marks, banner);

  let chosen = null;
  let selector = '';
  let fragile = false;
  let history = [];

  const visible = el => {
    if (!el || el === document.body || el === document.documentElement || banner.contains(el) || marks.contains(el)) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const textOf = el => ((el.innerText !== undefined ? el.innerText : el.textContent) || '').replace(/\s+/g, ' ').trim();
  // Texto como ele será capturado: sem barra de ações nem rótulos de papel.
  const captureTextOf = el => {
    const clone = el.cloneNode(true);
    clone.querySelectorAll('button,[role=button],script,style,[aria-hidden="true"]').forEach(item => item.remove());
    return ((clone.textContent) || '').replace(/\s+/g, ' ').trim();
  };
  const roleOf = el => {
    if (!el || !el.matches) return '';
    if (el.matches('user-query,[data-role="user"],[data-role=user],[data-message-author-role="user"]')) return 'user';
    if (el.matches('model-response,[data-role="assistant"],[data-role=assistant],[data-message-author-role="assistant"]')) return 'assistant';
    return '';
  };
  const looksLikeMessageContainer = el => {
    if (!el || el.nodeType !== 1) return false;
    const tag = el.tagName.toLowerCase();
    if (['body', 'html', 'main', 'section', 'article'].includes(tag)) return false;
    if (GENERIC_SIGNAL.test(tag)) return true;
    for (const attr of ['class', 'id', 'data-testid', 'data-test-id', 'aria-label']) {
      const value = el.getAttribute(attr);
      if (value && GENERIC_SIGNAL.test(value)) return true;
    }
    return false;
  };
  // Mesma regra do probe (chat_probe.js messageContainerOf) — ver ADR-023.
  function messageContainer(el) {
    if (!el || el.nodeType !== 1) return el;
    let node = el;
    while (node && INLINE_TAGS[node.tagName]) node = node.parentElement;
    if (!node || node === document.body) return el;

    const markers = [];
    for (let up = node; up && up !== document.body; up = up.parentElement) {
      if (up.matches && up.matches(ROLE_MARK) && !up.matches('message-content')) markers.push(up);
    }
    if (markers.length) {
      let base = markers[0];
      for (let i = markers.length - 1; i >= 0; i--) {
        const candidate = markers[i];
        const roles = new Set();
        candidate.querySelectorAll(ROLE_MARK).forEach(item => {
          const found = roleOf(item);
          if (found) roles.add(found);
        });
        const own = roleOf(candidate);
        if (own) roles.add(own);
        if (roles.has('user') && roles.has('assistant')) continue;
        base = candidate;
        break;
      }
      return base;
    }

    let best = node;
    let parent = node.parentElement;
    let depth = 0;
    while (parent && parent !== document.body && depth < 8) {
      if (!parent.matches || parent.querySelector("textarea,input,[contenteditable='true'],[contenteditable='']")) break;
      if (parent.querySelectorAll('button,[role=button]').length > 2) break;
      const sibling = [...parent.children].some(child => child !== best && looksLikeMessageContainer(child));
      if (sibling) break;
      if (looksLikeMessageContainer(parent)) best = parent;
      parent = parent.parentElement;
      depth += 1;
    }
    return best;
  }
  const normalize = el => {
    if (composerRole) return el.closest(EDITABLE) || el;
    if (buttonRole) return el.closest(CLICKABLE) || el;
    if (messageRole) return messageContainer(el) || el;
    return el;
  };
  const query = value => {
    try {
      const items = [...document.querySelectorAll(value)].filter(visible);
      // Um seletor pode casar com o balão E com o pedaço dentro dele. Contar os
      // dois fazia "uma resposta" aparecer como duas na prévia e no mapeamento.
      return items.filter(el => !items.some(other => other !== el && other.contains(el)));
    } catch (error) { return []; }
  };
  // Profundidade do nó escolhido dentro das camadas de mensagem: é o que
  // permite dizer "camada 2 de 3" e voltar para o balão inteiro.
  const layerOf = el => {
    let depth = 1;
    for (let up = el && el.parentElement; up && up !== document.body && depth < 9; up = up.parentElement) {
      if (up.matches && (up.matches(ROLE_MARK) || looksLikeMessageContainer(up))) depth += 1;
    }
    return depth;
  };

  function identify(el) {
    fragile = false;
    if (!messageRole && el.id) return '#' + CSS.escape(el.id);
    for (const attr of ['data-message-author-role', 'data-role', 'data-testid', 'aria-label', 'role']) {
      const value = el.getAttribute(attr);
      if (value && value.length < 120) {
        const s = el.tagName.toLowerCase() + '[' + attr + '=' + JSON.stringify(value) + ']';
        if (messageRole || query(s).length === 1) return s;
      }
    }
    const classes = [...el.classList].filter(c => !/^(ng-|css-)|[0-9a-f]{8,}/i.test(c)).slice(0, 4);
    if (classes.length) {
      let s = el.tagName.toLowerCase() + classes.map(c => '.' + CSS.escape(c)).join('');
      const author = el.closest('user-query,model-response,[data-role=user],[data-role=assistant],[data-message-author-role]');
      if (messageRole && author && author !== el) {
        const attr = ['data-message-author-role', 'data-role'].find(a => author.hasAttribute(a));
        s = (attr ? author.tagName.toLowerCase() + '[' + attr + '=' + JSON.stringify(author.getAttribute(attr)) + ']'
          : author.tagName.toLowerCase()) + ' ' + s;
      }
      if (!messageRole && query(s).length === 1) return s;
      if (messageRole) {
        // Ler a conversa exige o seletor que casa com TODAS as mensagens daquele
        // lado. Se o nome completo casa com uma só, tenta a versão mais curta.
        if (query(s).length > 1) return s;
        for (let take = classes.length - 1; take >= 1; take -= 1) {
          const shorter = tag + classes.slice(0, take).map(c => '.' + CSS.escape(c)).join('');
          const total = query(shorter).length;
          if (total > 1 && total <= 200) return shorter;
        }
        return s;
      }
    }
    const tag = el.tagName.toLowerCase();
    // Em mensagens o seletor DEVE casar com todas as mensagens daquele papel:
    // é assim que o programa conta "uma resposta nova a cada envio".
    if (messageRole && !['div', 'span', 'p', 'section'].includes(tag)) return tag;
    if (!['div', 'span', 'p', 'section'].includes(tag) && query(tag).length === 1) return tag;
    fragile = true;
    const parts = [];
    let node = el;
    while (node && node.parentElement && node !== document.body && parts.length < 12) {
      if (node.id) { parts.unshift('#' + CSS.escape(node.id)); break; }
      const name = node.tagName.toLowerCase();
      const peers = [...node.parentElement.children].filter(n => n.tagName === node.tagName);
      parts.unshift(name + (peers.length > 1 ? ':nth-of-type(' + (peers.indexOf(node) + 1) + ')' : ''));
      node = node.parentElement;
    }
    return 'body ' + parts.join(' > ');
  }

  /* Candidatos por papel: nunca misturar botões com texto.
   *
   * Quando o site marca o papel (user-query/model-response/data-role), são
   * esses os alvos — um quadro por mensagem. Sem marcação, usamos blocos de
   * texto e ficamos só com a camada mais externa de cada grupo aninhado. */
  function candidates() {
    if (composerRole) return query(EDITABLE).slice(0, 60);
    if (buttonRole) return query(CLICKABLE).slice(0, 120);
    const marked = query(ROLE_MARK).filter(el => el !== document.body && !el.matches('message-content'));
    const blocks = marked.length ? marked : query(
      '.markdown,.message-content,.message-body,.query-text,article,[role=article],li,blockquote,pre,p,div');
    const found = blocks.filter(el => {
      if (textOf(el).length < 8) return false;
      if (el.querySelector('textarea,input,[contenteditable="true"],[contenteditable=""]')) return false;
      if (el.querySelectorAll('button,[role=button]').length > 2) return false;
      if ([...el.querySelectorAll(ROLE_MARK)].filter(roleOf).length > 1) return false;
      return el.getBoundingClientRect().bottom >= 0 && el.getBoundingClientRect().top <= innerHeight;
    });
    return found.filter(el => !found.some(other => other !== el && other.contains(el))).slice(0, 40);
  }

  const confirm = button('Usar esta área', () => { if (!confirm.disabled) finish({ selector }); }, 'data-picker-confirm');
  confirm.style.background = '#146c50';
  confirm.style.color = '#fff';
  const outer = button('Camada maior', () => {
    const parent = chosen && chosen.parentElement;
    if (!parent || parent === document.body) return;
    if (messageRole && roleOf(parent) === '' && parent.querySelector(ROLE_MARK)
        && new Set([...parent.querySelectorAll(ROLE_MARK)].map(roleOf)).size > 1) {
      status.textContent = 'Essa camada já mistura pergunta e resposta. Use o balão atual.';
      return;
    }
    preview(parent);
  });
  const inner = button('Camada menor', () => {
    if (!chosen) return;
    const child = [...chosen.children].find(visible);
    if (!child) return;
    preview(child);
  });
  const back = button('Voltar', () => { const el = history.pop(); if (el) preview(el, false); });
  const another = button('Escolher outra', reset);
  const move = button('Mover', () => { manualPos = null; corner = (corner + 1) % CORNERS.length; locked = true; placeBanner(); });
  const skip = button('Pular este campo', () => finish({ cancelled: true }), 'data-picker-skip');
  const abort = button('Cancelar mapeamento', () => finish({ abort: true }), 'data-picker-abort');

  function button(text, onClick, attribute) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = text;
    if (attribute) b.setAttribute(attribute, '');
    Object.assign(b.style, { minHeight: '44px', padding: '8px 16px', border: '1px solid #81978b',
      borderRadius: '6px', background: '#fff', color: '#1b3029', font: 'inherit', cursor: 'pointer',
      // O corpo do painel é `pointer-events: none` (ADR-025): só os controles
      // recebem o ponteiro de volta, por isso isto fica na fábrica.
      pointerEvents: 'auto' });
    b.onclick = onClick;
    return b;
  }

  /* O painel não pode cobrir o que a pessoa precisa clicar. Ele fica na faixa
   * (acima/abaixo) com menos sobreposição e, quando essa faixa é curta, a
   * altura é reduzida para caber nela — sem encolher a ponto de sumir. Em
   * telas estreitas isso é o que mantém o campo visível e clicável. */
  const CORNERS = ['top-right', 'bottom-right', 'bottom-left', 'top-left'];
  const MARGIN = 16;
  const MIN_HEIGHT = 160;
  let corner = 0;
  let locked = false;

  const area = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left))
    * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));

  function targetBoxes() {
    const nodes = (chosen ? query(selector) : candidates()).slice(0, 40);
    const important = 'textarea,[contenteditable="true"],[contenteditable=""],[role="textbox"],'
      + 'input,button,[role="button"]';
    return nodes.map(el => {
      const rect = el.getBoundingClientRect();
      // O que a pessoa precisa clicar (campo, botão) pesa mais que um container
      // grande: o painel sai da frente do campo antes de sair de qualquer bloco.
      let weight = 1;
      try { if (el.matches(important) || (el.closest && el.closest(important))) weight = 12; }
      catch (error) { weight = 1; }
      return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
        width: rect.width, height: rect.height, weight };
    }).filter(r => r.width > 2 && r.height > 2 && r.bottom > 0 && r.top < innerHeight
                   && r.right > 0 && r.left < innerWidth);
  }

  function unionOf(boxes) {
    if (!boxes.length) return null;
    return boxes.reduce((u, r) => ({ left: Math.min(u.left, r.left), top: Math.min(u.top, r.top),
      right: Math.max(u.right, r.right), bottom: Math.max(u.bottom, r.bottom) }),
      { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity });
  }

  function layout(name, boxes, union, natural) {
    const width = Math.min(banner.offsetWidth || 400, innerWidth - 2 * MARGIN);
    // Altura disponível na faixa (acima ou abaixo do que precisa ser clicado).
    const room = !union ? innerHeight - 2 * MARGIN
      : name.startsWith('top') ? union.top - 2 * MARGIN : innerHeight - union.bottom - 2 * MARGIN;
    const height = Math.max(0, Math.min(natural, room));
    const left = name.endsWith('left') ? MARGIN : innerWidth - width - MARGIN;
    const top = name.startsWith('top') ? MARGIN : innerHeight - height - MARGIN;
    const rect = { left, top, right: left + width, bottom: top + height };
    return { index: CORNERS.indexOf(name), height, room,
             score: boxes.reduce((sum, box) => sum + area(rect, box) * (box.weight || 1), 0),
             usable: room >= MIN_HEIGHT || !boxes.length };
  }

  function measureHeight() {
    banner.style.maxHeight = '';
    return Math.min(banner.offsetHeight || 240, innerHeight - 2 * MARGIN);
  }

  function chooseCorner(boxes, union, natural) {
    const plans = CORNERS.map(name => layout(name, boxes, union, natural));
    const current = plans[corner];
    let best = current;
    if (!locked) {
      const usable = plans.filter(plan => plan.usable);
      const pool = usable.length ? usable : plans;
      best = pool.reduce((pick, plan) => (plan.score < pick.score - 1 ? plan : pick), pool[0]);
      // Empate mantém o canto atual: o painel não fica pulando na tela, mas
      // sai da frente assim que passar a cobrir o alvo (ex.: depois de rolar).
      if (current && (current.usable || !usable.length) && current.score <= best.score + 1) best = current;
    }
    return best || plans[0];
  }

  function placeBanner() {
    if (manualPos) { placeAt(manualPos.left, manualPos.top); return; }
    const boxes = targetBoxes();
    const union = unionOf(boxes);
    const natural = measureHeight();
    const best = chooseCorner(boxes, union, natural);
    corner = best ? best.index : corner;
    applyCorner(best, natural);
  }

  let manualPos = null;  // posição escolhida arrastando: manda sobre os cantos

  function clampPosition(left, top) {
    const width = banner.offsetWidth || 392;
    const height = banner.offsetHeight || 240;
    return {
      left: Math.max(8, Math.min(left, innerWidth - width - 8)),
      top: Math.max(8, Math.min(top, innerHeight - Math.min(height, innerHeight - 16) - 8)),
    };
  }

  function placeAt(left, top) {
    const spot = clampPosition(left, top);
    manualPos = spot;
    Object.assign(banner.style, { left: spot.left + 'px', top: spot.top + 'px', right: 'auto', bottom: 'auto' });
  }

  function applyCorner(plan, natural) {
    if (manualPos) { placeAt(manualPos.left, manualPos.top); return; }
    const name = CORNERS[corner];
    Object.assign(banner.style, {
      left: name.endsWith('left') ? MARGIN + 'px' : 'auto',
      right: name.endsWith('right') ? MARGIN + 'px' : 'auto',
      top: name.startsWith('top') ? MARGIN + 'px' : 'auto',
      bottom: name.startsWith('bottom') ? MARGIN + 'px' : 'auto',
    });
    // Tamanho fixo: o limite é a tela, nunca uma faixa curta. Combinado com
    // `pointer-events: none` no corpo do painel, cobrir o alvo não impede o
    // clique; e não existe barra de rolagem.
    banner.style.maxHeight = Math.max(MIN_HEIGHT, Math.min(natural || 0, innerHeight - 2 * MARGIN)) + 'px';
  }

  function describe(el) {
    const text = captureTextOf(el);
    previewText.textContent = text ? '“' + (text.length > 140 ? text.slice(0, 140) + '…' : text) + '”' : '(sem texto legível)';
    const matched = query(selector);
    const count = matched.length;
    previewLabel.textContent = 'Vai capturar: ';
    const parts = [];
    if (count > 1) parts.push(count + ' elementos casam com este seletor');
    if (messageRole) parts.push('camada ' + layerOf(el) + ' (balão inteiro é o menor número)');
    if (fragile) parts.push('seleção por posição: pode precisar de ajuste quando o chat mudar');
    if (messageRole) {
      // Comparar com o papel normalizado: 'assistant' nunca é igual ao rótulo
      // 'resposta do assistente', e a mensagem de camada trocada aparecia
      // sempre, mesmo com a seleção certa.
      const wanted = role === 'mensagem do usuário' ? 'user'
        : role === 'resposta do assistente' ? 'assistant' : '';
      const mixed = wanted ? matched.filter(item => {
        const found = roleOf(item);
        return found && found !== wanted;
      }).length : 0;
      if (mixed) parts.push(mixed + ' do outro papel também casariam: use “Camada menor”/“Camada maior”');
    }
    // Lista numerada: a pessoa confere se são as mensagens certas e na ordem
    // certa antes de confirmar (três ou mais é o mínimo exigido no mapeamento).
    // Três linhas bastam para conferir a ordem; o resto é contagem, não texto.
    const lines = matched.slice(0, 3).map((item, index) =>
      (index + 1) + '. ' + ((captureTextOf(item) || '(sem texto legível)').slice(0, 48)));
    if (count > 3) parts.push('+' + (count - 3) + ' fora da lista');
    status.textContent = [parts.join(' · '), lines.join('\n')].filter(Boolean).join('\n');
    status.style.whiteSpace = 'pre-line';
    confirm.disabled = !count;
  }

  function draw() {
    ensureAttached();
    drawing = true;
    confirm.hidden = !chosen;
    outer.hidden = inner.hidden = back.hidden = !chosen;
    another.hidden = false;
    confirmationState();
    placeBanner();
    marks.replaceChildren();
    const items = chosen ? query(selector) : candidates();
    items.slice(0, 80).forEach((el, index) => {
      const r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return;
      const box = document.createElement('div');
      Object.assign(box.style, { position: 'fixed', left: r.left + 'px', top: r.top + 'px', width: r.width + 'px',
        height: r.height + 'px', boxSizing: 'border-box', border: '2px solid ' + (chosen ? '#146c50' : '#2563eb'),
        background: chosen ? '#146c501a' : 'transparent', borderRadius: '4px', pointerEvents: 'none' });
      const badge = document.createElement('button');
      badge.type = 'button';
      badge.textContent = String(index + 1);
      const snippet = textOf(el).slice(0, 60);
      badge.setAttribute('aria-label', 'Selecionar área ' + (index + 1) + (snippet ? ': ' + snippet : ''));
      Object.assign(badge.style, { pointerEvents: 'auto', position: 'absolute', left: r.left < 14 ? '0' : '-14px',
        top: r.top < 14 ? '0' : '-14px', minWidth: '28px', minHeight: '28px', border: '0', borderRadius: '4px',
        background: chosen ? '#146c50' : '#2563eb', color: '#fff', font: 'bold 13px system-ui', cursor: 'pointer' });
      badge.onclick = () => preview(el);
      box.append(badge);
      marks.append(box);
    });
    drawing = false;
  }
  function confirmationState() {
    for (const b of banner.querySelectorAll('button')) {
      b.style.opacity = b.disabled ? '0.45' : '1';
      b.style.pointerEvents = 'auto';
    }
  }
  function reset() {
    chosen = null;
    locked = false;
    selector = '';
    history = [];
    previewText.textContent = 'nada ainda — clique em uma área destacada em azul.';
    status.textContent = 'Esc pula este campo. Nada é enviado nem alterado no site.';
    confirm.disabled = true;
    draw();
  }
  function preview(el, push = true) {
    if (!el || !visible(el)) return;
    if (composerRole && !el.matches(EDITABLE)) { status.textContent = 'Escolha uma caixa de texto editável (destacada em azul).'; return; }
    if (buttonRole && !el.matches(CLICKABLE)) { status.textContent = 'Escolha um botão (destacado em azul).'; return; }
    if (role === 'botão Enviar' && window.__balVoiceControl && window.__balVoiceControl(el)) {
      status.textContent = 'Esse é o microfone. Digite no campo para aparecer Enviar e clique de novo.';
      return;
    }
    const target = normalize(el);
    if (!target) return;
    if (messageRole && (target.matches(CLICKABLE) || target.closest(CLICKABLE))) {
      status.textContent = 'Isso é um botão. Clique no balão com o texto da mensagem.';
      return;
    }
    if (push && chosen && chosen !== target) history.push(chosen);
    if (chosen !== target) locked = false;
    chosen = target;
    selector = identify(target);
    describe(target);
    draw();
  }
  const click = event => {
    if (event.composedPath().includes(banner) || event.composedPath().includes(marks)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const el = event.composedPath().find(node => node instanceof Element);
    if (el) preview(normalize(el));
  };
  const key = event => {
    if (event.key === 'Escape') { event.preventDefault(); finish({ cancelled: true }); }
    if (event.key === 'Enter' && !event.composedPath().includes(banner)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!confirm.disabled && chosen) finish({ selector });
    }
  };
  /* Redesenho por mutação (ADR-010): antes era um intervalo de 350 ms, que
   * redesenhava sem necessidade e ainda podia perder o instante em que o balão
   * aparece. O observer só agenda quando algo fora do painel muda. */
  let scheduled = false;
  let drawing = false;
  const schedule = () => {
    if (scheduled || drawing) return;
    scheduled = true;
    const run = () => { scheduled = false; if (!drawing) draw(); };
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(run); else setTimeout(run, 16);
  };
  /* Sites que re-renderizam o body (React/Vue recriando o container raiz)
   * removem nós injetados sem avisar. Sem reanexar, o painel desaparece no
   * meio do mapeamento e a próxima checagem diz "o painel não abriu". */
  const ensureAttached = () => {
    if (!banner.isConnected && document.body) document.body.append(banner);
    if (!marks.isConnected && document.body) document.body.append(marks);
  };
  const observer = new MutationObserver(records => {
    if (drawing) return;
    for (const record of records) {
      const target = record.target;
      if (banner.contains(target) || marks.contains(target)) continue;
      ensureAttached();
      schedule();
      return;
    }
  });
  try { observer.observe(document.body, { childList: true, subtree: true, characterData: true }); }
  catch (error) { /* ambiente sem MutationObserver: os eventos de scroll/resize seguem */ }

  // Arrastar pela faixa do título. Clique em botão continua sendo clique.
  let dragging = null;
  const startDrag = event => {
    if (!event.composedPath().includes(grip)) return;
    event.preventDefault();
    const rect = banner.getBoundingClientRect();
    dragging = { dx: event.clientX - rect.left, dy: event.clientY - rect.top };
    locked = true;
    try { top.setPointerCapture(event.pointerId); } catch (error) { /* ok */ }
  };
  const drag = event => {
    if (!dragging) return;
    event.preventDefault();
    placeAt(event.clientX - dragging.dx, event.clientY - dragging.dy);
  };
  const endDrag = () => { dragging = null; };
  banner.addEventListener('pointerdown', startDrag);
  window.addEventListener('pointermove', drag, true);
  window.addEventListener('pointerup', endDrag, true);
  window.addEventListener('pointercancel', endDrag, true);

  function finish(value) {
    window.__balPick = value;
    cleanup();
  }
  function cleanup() {
    try { observer.disconnect(); } catch (error) { /* já desconectado */ }
    banner.removeEventListener('pointerdown', startDrag);
    window.removeEventListener('pointermove', drag, true);
    window.removeEventListener('pointerup', endDrag, true);
    window.removeEventListener('pointercancel', endDrag, true);
    document.removeEventListener('click', click, true);
    document.removeEventListener('keydown', key, true);
    window.removeEventListener('scroll', draw, true);
    window.removeEventListener('resize', onResize);
    banner.remove();
    marks.remove();
    delete window.__balPickerCleanup;
  }
  document.addEventListener('click', click, true);
  document.addEventListener('keydown', key, true);
  window.addEventListener('scroll', draw, true);
  const onResize = () => { locked = false; draw(); };
  window.addEventListener('resize', onResize);
  window.__balPickerCleanup = cleanup;
  window.__balPickerContainer = messageRole ? messageContainer : null;
  if (window.__balTypingCleanup) window.__balTypingCleanup();
  controls.append(confirm);
  secondary.append(outer, inner, back, another, move, skip, abort);
  reset();
}
