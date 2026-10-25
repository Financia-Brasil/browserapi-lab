/* Apontamento visual temporário; nunca exige console ou JS manual. */
(role) => {
  if (window.__balPickerCleanup) window.__balPickerCleanup();
  window.__balPick = null;
  const banner = document.createElement('div');
  banner.id = '__browserapi_picker';
  banner.textContent = 'BrowserAPI: clique no ' + role + '. Esc cancela. Nada será enviado.';
  Object.assign(banner.style, {position:'fixed',top:'0',left:'0',right:'0',zIndex:'2147483647',
    background:'#16324f',color:'white',padding:'18px',font:'16px system-ui',pointerEvents:'none'});
  document.body.appendChild(banner);
  const cleanup = () => {
    document.removeEventListener('click', click, true);
    document.removeEventListener('keydown', key, true);
    banner.remove();
    delete window.__balPickerCleanup;
  };
  const key = ev => {
    if (ev.key === 'Enter') { ev.preventDefault(); ev.stopImmediatePropagation(); }
    if (ev.key === 'Escape') { window.__balPick = {cancelled:true}; cleanup(); }
  };
  const escape = value => CSS.escape(value);
  const click = ev => {
    ev.preventDefault(); ev.stopImmediatePropagation();
    let el = ev.composedPath().find(n => n instanceof Element && n !== banner);
    if (!el) return;
    if (role === 'campo de mensagem') el = el.closest('textarea,input,[contenteditable=true]') || el;
    if (role === 'botão Enviar') el = el.closest('button,[role=button]') || el;
    if (role === 'botão Enviar' && window.__balVoiceControl && window.__balVoiceControl(el)) {
      banner.textContent = 'Esse controle é de microfone/voz. Aponte Enviar com um rascunho no campo, ou Esc para cancelar.';
      return;
    }
    if (role === 'mensagem do usuário') el = el.closest('.body,.message-content') || el.closest('user-query,[data-role=user],[data-message-author-role=user]') || el;
    if (role === 'resposta do assistente') el = el.closest('.markdown,.markdown-content,.model-response-text,.body,[data-response-content]') || el.closest('model-response,[data-role=assistant],[data-message-author-role=assistant]') || el;
    // Seletores de mensagem devem capturar todos os turnos, não o ID de um turno antigo.
    let selector;
    const message = ['mensagem do usuário', 'resposta do assistente'].includes(role);
    if (!message && el.id) selector = '#' + escape(el.id);
    for (const attr of ['data-message-author-role','data-role','data-testid','aria-label']) {
      if (selector) break;
      const value = el.getAttribute(attr);
      if (value && value.length < 120) { selector = el.tagName.toLowerCase() + '[' + attr + '=' + JSON.stringify(value) + ']'; break; }
    }
    if (!selector && !message && el.id) selector = '#' + escape(el.id);
    if (!selector && ['MODEL-RESPONSE','USER-QUERY','TEXTAREA'].includes(el.tagName)) selector = el.tagName.toLowerCase();
    if (!selector) {
      const classes = [...el.classList].filter(c => !/^(ng-|css-|sc-)|[0-9a-f]{8,}/i.test(c)).slice(0,3);
      selector = el.tagName.toLowerCase() + classes.map(c => '.' + escape(c)).join('');
    }
    if (message) {
      const author = el.closest('user-query,model-response,[data-role=user],[data-role=assistant],[data-message-author-role]');
      if (author && author !== el) {
        let prefix = author.tagName.toLowerCase();
        for (const attr of ['data-message-author-role', 'data-role']) {
          if (author.hasAttribute(attr)) { prefix += '[' + attr + '=' + JSON.stringify(author.getAttribute(attr)) + ']'; break; }
        }
        selector = prefix + ' ' + selector;
      }
    }
    if (['html','body','div','span','p'].includes(selector)) {
      banner.textContent = 'Seleção muito genérica. Clique no contêiner da mensagem ou pressione Esc.';
      return;
    }
    if (!message && document.querySelectorAll(selector).length !== 1) {
      banner.textContent = 'Esse controle não é único. Clique no campo ou botão exato, ou pressione Esc.';
      return;
    }
    window.__balPick = {selector}; cleanup();
  };
  document.addEventListener('click', click, true);
  document.addEventListener('keydown', key, true);
  window.__balPickerCleanup = cleanup;
}
