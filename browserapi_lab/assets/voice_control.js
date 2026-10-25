/* Indício explícito de voz: falhar sem clicar, nunca escolher por exclusão. */
(el) => {
  const nodes = [el, ...el.querySelectorAll('mat-icon,svg title,[data-testid],[data-icon],[aria-label]')].slice(0, 24);
  const text = nodes.map(node => [node.getAttribute('aria-label'), node.getAttribute('title'),
    node.getAttribute('data-testid'), node.getAttribute('data-icon'), node.textContent].filter(Boolean).join(' ')).join(' ');
  return /[🎤🎙]|\b(microphone|microfone|mic|voice|voz|dictation|ditado|dictate|record|recording|gravação|gravacao)\b/i.test(text);
}
