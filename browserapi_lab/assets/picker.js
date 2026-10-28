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
  Object.assign(banner.style, { position: 'fixed', top: '16px', right: '16px', width: '400px',
    maxWidth: 'calc(100vw - 32px)', boxSizing: 'border-box', zIndex: '2147483647', background: '#fff',
    color: '#1b3029', border: '2px solid #146c50', borderRadius: '8px', padding: '12px',
    font: '14px/1.4 system-ui', boxShadow: '0 4px 24px #0003', maxHeight: 'calc(100vh - 32px)', overflow: 'auto' });

  const top = document.createElement('div');
  Object.assign(top.style, { display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' });
  const title = document.createElement('strong');
  title.textContent = 'Selecionar: ' + role;
  title.style.fontSize = '16px';
  top.append(title);
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
    WebkitLineClamp: '3', WebkitBoxOrient: 'vertical', overflow: 'hidden' });
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
    try { return [...document.querySelectorAll(value)].filter(visible); } catch (error) { return []; }
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
      if (messageRole || query(s).length === 1) return s;
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
  const move = button('Mover', () => { corner = (corner + 1) % CORNERS.length; placeBanner(true); });
  const skip = button('Pular este campo', () => finish({ cancelled: true }), 'data-picker-skip');
  const abort = button('Cancelar mapeamento', () => finish({ abort: true }), 'data-picker-abort');

  function button(text, onClick, attribute) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = text;
    if (attribute) b.setAttribute(attribute, '');
    Object.assign(b.style, { minHeight: '44px', padding: '8px 16px', border: '1px solid #81978b',
      borderRadius: '6px', background: '#fff', color: '#1b3029', font: 'inherit', cursor: 'pointer' });
    b.onclick = onClick;
    return b;
  }

  /* O painel não pode cobrir o que a pessoa precisa clicar: fica no canto com
   * menos sobreposição com as áreas destacadas. "Mover" troca de canto. */
  const CORNERS = ['top-right', 'bottom-right', 'bottom-left', 'top-left'];
  let corner = 0;
  function placeBanner(force) {
    if (!force && banner.dataset.placed === '1') return;
    const size = banner.getBoundingClientRect();
    const width = size.width || 400;
    const height = size.height || 240;
    const boxes = candidates().slice(0, 40).map(el => el.getBoundingClientRect());
    let best = corner;
    let bestOverlap = Infinity;
    CORNERS.forEach((name, index) => {
      const left = name.endsWith('left') ? 16 : innerWidth - width - 16;
      const top = name.startsWith('top') ? 16 : innerHeight - height - 16;
      const right = left + width;
      const bottom = top + height;
      const overlap = boxes.reduce((sum, box) => {
        const w = Math.max(0, Math.min(right, box.right) - Math.max(left, box.left));
        const h = Math.max(0, Math.min(bottom, box.bottom) - Math.max(top, box.top));
        return sum + w * h;
      }, 0);
      if (overlap < bestOverlap) { bestOverlap = overlap; best = index; }
    });
    corner = best;
    const name = CORNERS[corner];
    Object.assign(banner.style, {
      left: name.endsWith('left') ? '16px' : 'auto',
      right: name.endsWith('right') ? '16px' : 'auto',
      top: name.startsWith('top') ? '16px' : 'auto',
      bottom: name.startsWith('bottom') ? '16px' : 'auto',
    });
    banner.dataset.placed = '1';
  }

  function describe(el) {
    const text = captureTextOf(el);
    previewText.textContent = text ? '“' + (text.length > 140 ? text.slice(0, 140) + '…' : text) + '”' : '(sem texto legível)';
    const count = query(selector).length;
    previewLabel.textContent = 'Vai capturar: ';
    const parts = [];
    if (count > 1) parts.push(count + ' elementos casam com este seletor');
    if (fragile) parts.push('seleção por posição: pode precisar de ajuste quando o chat mudar');
    if (messageRole && count > 1) parts.push('as outras mensagens do mesmo tipo também serão lidas');
    status.textContent = parts.join(' · ') || 'Confira o texto acima e clique em “Usar esta área”.';
    confirm.disabled = !count;
  }

  function draw() {
    confirm.hidden = !chosen;
    outer.hidden = inner.hidden = back.hidden = another.hidden = !chosen;
    confirmationState();
    placeBanner(false);
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
  }
  function confirmationState() {
    for (const b of banner.querySelectorAll('button')) b.style.opacity = b.disabled ? '0.45' : '1';
  }
  function reset() {
    chosen = null;
    selector = '';
    history = [];
    banner.dataset.placed = '0';
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
  const timer = setInterval(draw, 350);
  function finish(value) {
    window.__balPick = value;
    cleanup();
  }
  function cleanup() {
    clearInterval(timer);
    document.removeEventListener('click', click, true);
    document.removeEventListener('keydown', key, true);
    window.removeEventListener('scroll', draw, true);
    window.removeEventListener('resize', draw);
    banner.remove();
    marks.remove();
    delete window.__balPickerCleanup;
  }
  document.addEventListener('click', click, true);
  document.addEventListener('keydown', key, true);
  window.addEventListener('scroll', draw, true);
  window.addEventListener('resize', draw);
  window.__balPickerCleanup = cleanup;
  window.__balPickerContainer = messageRole ? messageContainer : null;
  if (window.__balTypingCleanup) window.__balTypingCleanup();
  controls.append(confirm);
  secondary.append(outer, inner, back, another, move, skip, abort);
  reset();
}
