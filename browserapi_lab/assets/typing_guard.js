/* A pessoa pode digitar, mas cliques em botões/Enter não enviam durante o ensino. */
() => {
  if (window.__balTypingCleanup) window.__balTypingCleanup();
  window.__balTypingCancelled = false;
  const banner = document.createElement('div');
  banner.id = '__browserapi_typing';
  banner.textContent = 'Digite um rascunho SEM enviar. Volte ao painel e clique em Continuar para selecionar Enviar. Esc cancela.';
  Object.assign(banner.style, {position:'fixed', top:'0', left:'0', right:'0', zIndex:'2147483647', padding:'18px', color:'white', background:'#16324f', pointerEvents:'none', font:'16px system-ui'});
  document.body.append(banner);
  const cleanup = () => {
    document.removeEventListener('click', click, true);
    document.removeEventListener('keydown', key, true);
    banner.remove(); delete window.__balTypingCleanup;
  };
  const key = event => {
    if (event.key === 'Enter') { event.preventDefault(); event.stopImmediatePropagation(); }
    if (event.key === 'Escape') { window.__balTypingCancelled = true; cleanup(); }
  };
  const click = event => {
    if (event.composedPath().some(node => node instanceof Element && node.matches('button,[role=button],input[type=submit]'))) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  };
  document.addEventListener('click', click, true);
  document.addEventListener('keydown', key, true);
  window.__balTypingCleanup = cleanup;
}
