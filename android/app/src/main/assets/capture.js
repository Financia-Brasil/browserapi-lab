/* Farol: captura local, sem ponte nativa, sem ler ou serializar valores. */
(() => {
  const F = window.__farol || (window.__farol = { dirty: true, targets: [], overlay: null });
  const redact = s => String(s || '').replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,'[texto]')
    .replace(/\b\d[\d.() /+\-]{5,}\d\b/g,'[texto]').trim().slice(0,180);
  function visible(el) {
    const style = getComputedStyle(el);
    return !el.hidden && !el.closest('[hidden],[aria-hidden="true"]') &&
      style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
  }
  function text(el) {
    const copy = el.cloneNode(true);
    copy.querySelectorAll('input,textarea,select,[contenteditable],script,style,[hidden]').forEach(n => n.remove());
    return redact(copy.textContent);
  }
  function label(el) {
    return redact(el.getAttribute('aria-label')) ||
      (el.labels && el.labels[0] ? text(el.labels[0]) : '') ||
      (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => {
        const n = document.getElementById(id); return n ? text(n) : '';
      }).filter(Boolean).join(' ').slice(0,180) ||
      (['INPUT','TEXTAREA','SELECT'].includes(el.tagName) ? redact(el.getAttribute('placeholder')) : text(el));
  }
  if (!F.observer) {
    F.observer = new MutationObserver(records => {
      if (records.some(r => !(r.target instanceof Element && r.target.closest('[data-farol-overlay]')))) F.dirty = true;
    });
    F.observer.observe(document.body, {childList:true,subtree:true,characterData:true,attributes:true,
      attributeFilter:['aria-invalid','aria-label','aria-hidden','hidden','disabled']});
    document.addEventListener('input', () => { F.dirty = true; }, true);
    document.addEventListener('change', () => { F.dirty = true; }, true);
    const position = () => {
      if (!F.overlay || !F.target || !F.target.isConnected) { if(F.overlay) F.overlay.hidden=true; return; }
      const r = F.target.getBoundingClientRect();
      Object.assign(F.overlay.style,{left:(r.left-4)+'px',top:(r.top-4)+'px',width:(r.width+8)+'px',height:(r.height+8)+'px'});
    };
    window.addEventListener('scroll',position,true); window.addEventListener('resize',position);
    F.mark = index => {
      if (!F.overlay) {
        F.overlay = document.createElement('div'); F.overlay.setAttribute('data-farol-overlay','');
        F.overlay.setAttribute('aria-hidden','true');
        F.overlay.style.cssText='position:fixed;pointer-events:none;box-sizing:border-box;border:3px solid #FFCD07;outline:1px solid #04183F;border-radius:8px;z-index:2147483647';
        document.body.appendChild(F.overlay);
      }
      F.target=F.targets[index]; F.overlay.hidden=!F.target; position();
    };
  }
  if (!F.dirty && !F.force) return null;
  F.dirty=false; F.force=false;
  const list = Array.from(document.querySelectorAll('input,textarea,select,button,a[href],[role="button"],[role="alert"],[aria-invalid="true"]'))
    .filter(el => visible(el) && !el.disabled && !el.readOnly && !['hidden','file'].includes(el.type)).slice(0,120);
  F.targets = list;
  const nodes = list.map((el,index) => {
    const input = ['INPUT','TEXTAREA','SELECT'].includes(el.tagName);
    const role = el.getAttribute('role') === 'alert' ? 'alert' :
      el.tagName==='SELECT' ? 'combobox' :
      input && !['button','submit','reset','checkbox','radio'].includes(el.type) ? 'textbox' :
      el.tagName==='A' ? 'link' : 'button';
    return {index,role,label:label(el),filled:input ? Boolean(el.value) : false,
      sensitive:el.type==='password'};
  });
  const errors = list.filter(el => el.getAttribute('role')==='alert').map(text).filter(Boolean);
  if (!errors.length && list.some(el => el.getAttribute('aria-invalid')==='true')) errors.push('Campo inválido. Confira o preenchimento.');
  const completed = document.querySelector('[data-farol-complete="true"]');
  return {version:1,origin:location.origin,nodes,errors,complete:!!(completed && visible(completed)),
    frames:document.querySelectorAll('iframe').length};
})()