/* Visual selection: no typing, submission, or modification of site controls. */
(role) => {
  if (window.__balPickerCleanup) window.__balPickerCleanup();
  window.__balPick = null;
  const banner = document.createElement('div');
  banner.id = '__browserapi_picker';
  banner.setAttribute('role', 'region');
  banner.setAttribute('aria-label', 'Selecionar ' + role);
  Object.assign(banner.style, {position:'fixed',top:'16px',right:'16px',width:'520px',maxWidth:'calc(100vw - 32px)',boxSizing:'border-box',zIndex:'2147483647',background:'#fff',color:'#1b3029',border:'2px solid #146c50',borderRadius:'8px',padding:'16px',font:'15px/1.4 system-ui',boxShadow:'0 4px 24px #0003'});
  const title = document.createElement('strong'); title.textContent = 'Selecione: ' + role;
  const status = document.createElement('p'); status.setAttribute('aria-live','polite');
  Object.assign(status.style,{margin:'8px 0'});
  const controls = document.createElement('div'); Object.assign(controls.style,{display:'flex',gap:'8px',flexWrap:'wrap'});
  banner.append(title,status,controls);
  const marks = document.createElement('div'); marks.id='__browserapi_picker_marks';
  Object.assign(marks.style,{position:'fixed',inset:'0',pointerEvents:'none',zIndex:'2147483646'});
  document.body.append(marks,banner);
  let chosen=null, selector='', fragile=false, history=[];
  const message=['mensagem do usuário','resposta do assistente'].includes(role);
  const editable='textarea,input:not([type=hidden]):not([type=password]):not([type=submit]):not([type=button]),[contenteditable]:not([contenteditable=false]),[role=textbox]';
  const clickable='button,[role=button],input[type=submit]';
  const visible=el=>{
    if (!el || el===document.body || el===document.documentElement || banner.contains(el) || marks.contains(el)) return false;
    const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    return r.width>2 && r.height>2 && s.display!=='none' && s.visibility!=='hidden';
  };
  const normalize=el=>{
    if(role==='campo de mensagem') return el.closest(editable) || el;
    if(['botão Enviar','botão de comando de voz'].includes(role)) return el.closest(clickable) || el;
    return el.closest(message ? '.markdown,.markdown-content,.model-response-text,.body,[data-response-content],user-query,model-response,[data-message-author-role],[data-role=user],[data-role=assistant]' : '*') || el;
  };
  const query=s=>{try{return [...document.querySelectorAll(s)].filter(visible);}catch{return [];}};
  function identify(el){
    fragile=false;
    if(!message && el.id) return '#'+CSS.escape(el.id);
    for(const attr of ['data-message-author-role','data-role','data-testid','aria-label','role']){
      const value=el.getAttribute(attr);
      if(value && value.length<120){
        const s=el.tagName.toLowerCase()+'['+attr+'='+JSON.stringify(value)+']';
        if(message || query(s).length===1) return s;
      }
    }
    const classes=[...el.classList].filter(c=>! /^(ng-|css-|sc-)|[0-9a-f]{8,}/i.test(c)).slice(0,4);
    if(classes.length){
      let s=el.tagName.toLowerCase()+classes.map(c=>'.'+CSS.escape(c)).join('');
      const author=el.closest('user-query,model-response,[data-role=user],[data-role=assistant],[data-message-author-role]');
      if(message && author && author!==el){
        const attr=['data-message-author-role','data-role'].find(a=>author.hasAttribute(a));
        s=(attr ? author.tagName.toLowerCase()+'['+attr+'='+JSON.stringify(author.getAttribute(attr))+']' : author.tagName.toLowerCase())+' '+s;
      }
      if(message || query(s).length===1) return s;
    }
    const tag=el.tagName.toLowerCase();
    if(!['div','span','p','section'].includes(tag) && query(tag).length===1) return tag;
    // Last resort is explicit and previewed, never a silent generic selector.
    fragile=true;
    const parts=[];let node=el;
    while(node && node.parentElement && node!==document.body && parts.length<12){
      if(node.id){parts.unshift('#'+CSS.escape(node.id));break;}
      const tag=node.tagName.toLowerCase();
      const peers=[...node.parentElement.children].filter(n=>n.tagName===node.tagName);
      parts.unshift(tag+(peers.length>1?':nth-of-type('+(peers.indexOf(node)+1)+')':''));
      node=node.parentElement;
    }
    return 'body '+parts.join(' > ');
  }
  const candidates=()=>{
    const css=role==='campo de mensagem'?editable:message?'[data-message-author-role],[data-role=user],[data-role=assistant],user-query,model-response,article,[role=article],.markdown,.message-content,p,div':clickable;
    return [...document.querySelectorAll(css)].filter(el=>visible(el) && el.getBoundingClientRect().bottom>=0 && el.getBoundingClientRect().top<=innerHeight && (!message || (el.innerText || '').trim().length>8 && (el.matches('[data-message-author-role],[data-role=user],[data-role=assistant],user-query,model-response,article,[role=article],.markdown,.message-content') || ![...el.children].some(c=>(c.innerText || '').trim().length>8)))).slice(0,160);
  };
  function draw(){
    confirm.hidden=!chosen;outer.hidden=inner.hidden=!message || !chosen;back.hidden=!history.length;another.hidden=!chosen;
    for(const b of controls.querySelectorAll('button'))b.style.opacity=b.disabled?'0.45':'1';
    marks.replaceChildren();
    const items=chosen?query(selector):candidates();
    items.slice(0,160).forEach((el,index)=>{
      const r=el.getBoundingClientRect();
      if(r.bottom<0 || r.top>innerHeight || r.right<0 || r.left>innerWidth)return;
      const box=document.createElement('div');
      Object.assign(box.style,{position:'fixed',left:r.left+'px',top:r.top+'px',width:r.width+'px',height:r.height+'px',boxSizing:'border-box',border:'2px solid '+(chosen?'#146c50':'#2563eb'),background:chosen?'#146c501a':'transparent',borderRadius:'4px',pointerEvents:'none'});
      const badge=document.createElement('button');badge.type='button';badge.textContent=String(index+1);badge.setAttribute('aria-label','Selecionar área '+(index+1));
      Object.assign(badge.style,{pointerEvents:'auto',position:'absolute',left:r.left<14?'0':'-14px',top:r.top<14?'0':'-14px',minWidth:'28px',minHeight:'28px',border:'0',borderRadius:'4px',background:chosen?'#146c50':'#2563eb',color:'#fff',font:'bold 13px system-ui',cursor:'pointer'});
      badge.onclick=()=>preview(normalize(el));box.append(badge);marks.append(box);
    });
  }
  function reset(){chosen=null;selector='';history=[];status.textContent='Clique em uma área destacada. Nada será enviado.';confirm.disabled=true;outer.disabled=inner.disabled=back.disabled=true;draw();}
  function preview(el,push=true){
    if(!visible(el))return;
    if(role==='campo de mensagem' && !el.matches(editable)){status.textContent='Escolha um campo editável destacado em azul.';return;}
    if(['botão Enviar','botão de comando de voz'].includes(role) && !el.matches(clickable)){status.textContent='Escolha um botão destacado em azul.';return;}
    if(role==='botão Enviar' && window.__balVoiceControl && window.__balVoiceControl(el)){status.textContent='Esse é o microfone. Digite no campo para aparecer Enviar e clique novamente.';return;}
    if(push && chosen)history.push(chosen);
    chosen=el;selector=identify(el);
    const count=query(selector).length;
    status.textContent=count+' área(s) em verde. '+(fragile?'Seleção por posição: pode precisar de ajuste quando o chat mudar. ':'')+(message?'Confirme ou ajuste a camada.':'É o controle certo?');
    confirm.disabled=!count || (!message && count!==1);
    outer.disabled=!message || !visible(el.parentElement);inner.disabled=!message || ![...el.children].some(visible);back.disabled=!history.length;
    draw();
  }
  function button(text,fn,attribute){
    const b=document.createElement('button');b.type='button';b.textContent=text;
    if(attribute)b.setAttribute(attribute,'');
    Object.assign(b.style,{minHeight:'44px',padding:'8px 16px',border:'1px solid #81978b',borderRadius:'6px',background:'#fff',color:'#1b3029',font:'inherit',cursor:'pointer'});
    b.onclick=fn;controls.append(b);return b;
  }
  const confirm=button('Usar esta área',()=>{if(!confirm.disabled){window.__balPick={selector};cleanup();}},'data-picker-confirm');
  confirm.style.background='#146c50';confirm.style.color='#fff';
  const outer=button('Camada maior',()=>preview(chosen?.parentElement));
  const inner=button('Camada menor',()=>preview([...chosen.children].find(visible)));
  const back=button('Voltar',()=>{const el=history.pop();if(el)preview(el,false);});
  const another=button('Escolher outra',reset);
  button('Mover painel',()=>{const bottom=banner.style.top!=='auto';banner.style.top=bottom?'auto':'16px';banner.style.bottom=bottom?'16px':'auto';});
  button('Cancelar',()=>{window.__balPick={cancelled:true};cleanup();});
  const click=ev=>{
    if(ev.composedPath().includes(banner) || ev.composedPath().includes(marks))return;
    ev.preventDefault();ev.stopImmediatePropagation();
    const el=ev.composedPath().find(n=>n instanceof Element);
    if(el)preview(normalize(el));
  };
  const key=ev=>{
    if(ev.key==='Escape'){ev.preventDefault();window.__balPick={cancelled:true};cleanup();}
    if(ev.key==='Enter' && !ev.composedPath().includes(banner)){ev.preventDefault();ev.stopImmediatePropagation();}
  };
  const timer=setInterval(draw,350);
  function cleanup(){clearInterval(timer);document.removeEventListener('click',click,true);document.removeEventListener('keydown',key,true);window.removeEventListener('scroll',draw,true);window.removeEventListener('resize',draw);banner.remove();marks.remove();delete window.__balPickerCleanup;}
  document.addEventListener('click',click,true);document.addEventListener('keydown',key,true);
  window.addEventListener('scroll',draw,true);window.addEventListener('resize',draw);
  window.__balPickerCleanup=cleanup;
  if(window.__balTypingCleanup)window.__balTypingCleanup();
  reset();
}
