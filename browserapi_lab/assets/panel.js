'use strict';
const $ = id => document.getElementById(id);
const token = location.hash.slice(1) || sessionStorage.getItem('browserapi-token') || '';
if (token) sessionStorage.setItem('browserapi-token', token);
history.replaceState(null, '', '/');
let state = null;
let selected = null;
let chatSignature = '';
let pending = false;
function error(text) { $('error').textContent = text; $('error').hidden = !text; }
async function api(path, body) {
  const response = await fetch('/api/' + path, {method: body === undefined ? 'GET' : 'POST',
    headers: {'X-BrowserAPI-Token': token, 'Content-Type': 'application/json'},
    ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Não foi possível concluir.');
  return value;
}
function busy() { return pending || !!(state && ['running','waiting'].includes(state.phase)); }
function controls() {
  for (const id of ['configure','prepare','doctor','browser','provider','name','url','session-mode']) $(id).disabled = busy();
  $('ask').disabled = busy() || !selected;
  $('cancel').disabled = !busy();
  for (const button of $('chats').querySelectorAll('button,input')) button.disabled = busy();
}
async function task(operation, extra = {}) {
  if (busy()) return;
  pending = true; controls(); error('');
  try { await api('task', {operation, ...extra}); await refresh(); }
  catch (err) { error(err.message); }
  finally { pending = false; controls(); }
}
$('configuration').addEventListener('submit', event => {
  event.preventDefault();
  if (state?.chats.some(chat => chat.name === $('name').value)) {
    error('Esse nome já está salvo. Use Corrigir campos, ou escolha outro nome para um novo navegador/chat.'); return;
  }
  task('configure', {name: $('name').value, browser: $('browser').value,
                     provider: $('provider').value, session_mode: $('session-mode').value, url: $('url').value});
});
$('session-mode').addEventListener('change', () => {
  const personal = $('session-mode').value === 'existing_chrome';
  $('personal-warning').hidden = !personal;
  if (personal) { $('browser').value = 'chrome'; $('name').value = 'meu-chrome-logado'; }
});
$('provider').addEventListener('change', () => {
  $('url-box').hidden = $('provider').value !== 'custom';
  $('name').value = 'meu-' + ($('provider').value === 'custom' ? 'chat' : $('provider').value);
});
$('prepare').onclick = () => {
  if (confirm('Baixar componentes e Chromium para seu usuário? Requer internet e espaço em disco. Não instalará o Chrome ou Edge.')) task('prepare');
};
$('doctor').onclick = () => task('doctor');
$('ask').onclick = () => task('ask', {name: selected, message: $('message').value});
$('cancel').onclick = async () => {
  try { await api('cancel', {}); } catch (err) { error(err.message); }
};
async function reply(value) {
  if (!state || !state.prompt) return;
  for (const id of ['yes','no','continue']) $(id).disabled = true;
  try { await api('reply', {id: state.prompt.id, value}); await refresh(); }
  catch (err) { error(err.message); }
}
$('yes').onclick = () => reply('s');
$('no').onclick = () => reply('n');
$('continue').onclick = () => reply('');
function renderChats(chats) {
  const signature = JSON.stringify(chats);
  if (signature === chatSignature) return;
  chatSignature = signature;
  $('chats').replaceChildren();
  $('empty').hidden = chats.length > 0;
  if (!chats.some(chat => chat.name === selected)) selected = chats[0]?.name || null;
  for (const chat of chats) {
    const box = document.createElement('div'); box.className = 'chat';
    const label = document.createElement('label');
    const radio = document.createElement('input'); radio.type = 'radio'; radio.name = 'saved-chat';
    radio.value = chat.name; radio.checked = chat.name === selected;
    radio.onchange = () => { selected = chat.name; controls(); };
    label.append(radio, document.createTextNode(chat.name)); box.append(label);
    const info = document.createElement('small');
    info.textContent = chat.invalid ? 'Configuração inválida. Crie outra com um nome diferente.' :
      `${chat.browser}${chat.session_mode === 'existing_chrome' ? ' · Chrome pessoal conectado' : ' · perfil separado'} · ${chat.compatible ? 'Último teste passou' : 'Precisa testar'}${chat.checked_at ? ' · ' + chat.checked_at : ''}`;
    box.append(info);
    for (const [caption, operation] of [['Testar agora','check'],['Corrigir campos','repair']]) {
      const button = document.createElement('button'); button.textContent = caption; button.className = 'secondary';
      button.onclick = () => task(operation, {name: chat.name}); box.append(button);
    }
    $('chats').append(box);
  }
}
function render(value) {
  const oldPrompt = state?.prompt?.id;
  state = value;
  const labels = {idle:'Pronto',running:'Trabalhando…',waiting:'Aguardando você',done:'Concluído',error:'Precisa de atenção',cancelled:'Interrompido'};
  $('phase').textContent = labels[state.phase] || state.phase;
  $('prepared-label').textContent = state.prepared ? 'Componente de automação disponível. O teste confirma o navegador.' : 'Primeira vez? Clique em Preparar BrowserAPI.';
  renderChats(state.chats);
  $('log').textContent = state.messages.join('\n\n');
  $('prompt').hidden = !state.prompt;
  if (state.prompt) {
    $('question').textContent = state.prompt.text;
    const yesno = state.prompt.kind === 'yesno';
    $('yes').hidden = $('no').hidden = !yesno;
    $('continue').hidden = yesno;
    if (oldPrompt !== state.prompt.id) {
      for (const id of ['yes','no','continue']) $(id).disabled = false;
      (yesno ? $('yes') : $('continue')).focus();
    }
  }
  $('receipt').hidden = !state.receipt;
  if (state.receipt) {
    const receipt = state.receipt;
    $('result-title').textContent = receipt.compatible_in_this_run ? 'Funcionou neste teste ✓' : 'Ainda não funcionou';
    $('result-action').textContent = (receipt.action || '').replaceAll('Execute repair', 'Clique em Corrigir campos').replaceAll('Execute configure ou repair', 'Clique em Abrir e configurar ou Corrigir campos').replaceAll('repita check', 'clique em Testar agora').replaceAll('execute repair', 'clique em Corrigir campos');
    $('result-timing').textContent = receipt.timings?.total_ms !== undefined ? `Tempo observado: ${Math.round(receipt.timings.total_ms)} ms (inclui espera da resposta).` : '';
  }
  controls();
}
async function refresh() { render(await api('state')); }
async function poll() {
  try { await refresh(); }
  catch (err) { error(err.message || 'O painel perdeu a conexão. Abra BrowserAPI novamente pelo menu.'); }
  setTimeout(poll, 650);
}
poll();
