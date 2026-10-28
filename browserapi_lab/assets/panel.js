'use strict';
const PANEL_VERSION = '0.8.0';
const $ = id => document.getElementById(id);
const fragment = location.hash.slice(1);
const token = /^[A-Za-z0-9_-]{32,128}$/.test(fragment) ? fragment : sessionStorage.getItem('browserapi-token') || '';
if (token) sessionStorage.setItem('browserapi-token', token);
history.replaceState(null, '', '/');
let state = null;
let selected = null;
let chatSignature = '';
let pending = false;
let conversation = {name: null, revision: -1, data: null};
function error(text) { $('error').textContent = text; $('error').hidden = !text; }
async function api(path, body) {
  const response = await fetch('/api/' + path, {method: body === undefined ? 'GET' : 'POST',
    headers: {'X-BrowserAPI-Token': token, 'Content-Type': 'application/json'},
    ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Não foi possível concluir.');
  return value;
}
function incompatible() { return !!state && state.version !== PANEL_VERSION; }
function busy() { return pending || !!(state && ['running','waiting','updating'].includes(state.phase)); }
function controls() {
  for (const id of ['configure','prepare','doctor','browser','provider','name','url','session-mode','scan-profiles','prepare-shortcut']) $(id).disabled = busy() || incompatible();
  $('ask').disabled = busy() || incompatible() || !selected;
  $('composer-panel').hidden=!selected;
  $('selected-label').textContent=selected || '';
  profileControls();
  $('cancel').disabled = !busy();
  for (const button of $('chats').querySelectorAll('button,input')) button.disabled = busy() || incompatible();
  conversationControls();
}
function conversationSummary() {
  return (state?.chats || []).find(chat => chat.name === selected)?.conversation || null;
}
function conversationData() {
  return conversation.name === selected ? conversation.data : null;
}
function conversationControls() {
  const messages = conversationData()?.messages || [];
  const blocked = busy() || incompatible();
  $('conversation-copy').disabled = blocked || !messages.some(message => message.role === 'assistant');
  $('conversation-clear').disabled = blocked || !messages.length;
}
let conversationSignature = '';
function renderConversation(force = false) {
  $('conversation-card').hidden = !selected;
  if (!selected) {
    conversationSignature = '';
    $('conversation').replaceChildren();
    $('conversation-empty').hidden = false;
    $('conversation-title').textContent = 'Conversa';
    $('conversation-scope').textContent = 'Nada enviado por aqui nesta execução.';
    $('conversation-feedback').textContent = '';
    conversationControls();
    return;
  }
  const data = conversationData();
  const messages = data?.messages || [];
  const signature = JSON.stringify([selected, data?.revision, messages.length, messages.at(-1)?.at]);
  if (force || signature !== conversationSignature) {
    conversationSignature = signature;
    $('conversation-title').textContent = 'Conversa em ' + selected;
    $('conversation').replaceChildren();
    for (const message of messages) {
      const item = document.createElement('li');
      item.className = 'turn ' + (message.role === 'assistant' ? 'assistant' : 'user');
      const head = document.createElement('div'); head.className = 'turn-head';
      const who = document.createElement('strong');
      who.textContent = message.role === 'assistant' ? 'Resposta capturada da página' : 'Você enviou';
      const meta = document.createElement('small');
      meta.textContent = [message.at, Number.isFinite(message.total_ms) ? `${Math.round(message.total_ms)} ms` : ''].filter(Boolean).join(' · ');
      head.append(who, meta);
      const body = document.createElement('div'); body.className = 'turn-body';
      body.textContent = message.text;
      item.append(head, body);
      $('conversation').append(item);
    }
    $('conversation-empty').hidden = messages.length > 0;
    const turns = messages.filter(message => message.role === 'user').length;
    $('conversation-scope').textContent = !data ? 'Carregando a conversa desta conexão…' :
      messages.length
        ? `${turns} ${turns === 1 ? 'pergunta' : 'perguntas'} nesta execução do programa.` + (data.dropped ? ` ${data.dropped} mensagens antigas já não são exibidas.` : '')
        : 'Nada enviado por aqui nesta execução.';
  }
  conversationControls();
}
async function loadConversation(force = false) {
  if (!selected) { renderConversation(); return; }
  const revision = conversationSummary()?.revision ?? 0;
  if (!force && conversation.name === selected && conversation.revision === revision) return;
  const requested = selected;
  try {
    const data = await api('conversation?name=' + encodeURIComponent(requested));
    if (selected !== requested) return;
    conversation = {name: requested, revision: data.revision ?? revision, data};
  } catch (err) {
    if (selected !== requested) return;
    conversation = {name: requested, revision, data: null};
    error(err.message);
  }
  renderConversation();
}
async function task(operation, extra = {}) {
  if (busy() || incompatible()) return;
  pending = true; controls(); error('');
  try { await api('task', {operation, ...extra}); await refresh(); }
  catch (err) { error(err.message); }
  finally { pending = false; controls(); }
}
$('configuration').addEventListener('submit', event => {
  event.preventDefault();
  if($('session-mode').value==='existing_chrome' && !$('personal-profile').value){
    profileFeedback('Abra seu Chrome e atualize a lista. Nenhum perfil será criado no lugar do seu.',true);return;
  }
  if (state?.chats.some(chat => chat.name === $('name').value)) {
    error('Esse nome já está salvo. Use Corrigir campos, ou escolha outro nome para um novo navegador/chat.'); return;
  }
  task('configure', {name: $('name').value, browser: $('browser').value,
                     provider: $('provider').value, personal_profile:$('personal-profile').value, session_mode: $('session-mode').value, url: $('url').value});
});
let currentView='connections';
function navigate(view){
  currentView=view;
  for(const panel of document.querySelectorAll('.view')) panel.hidden=panel.id!=='view-'+view;
  for(const item of document.querySelectorAll('[data-view]')){
    const active=item.dataset.view===view;
    item.classList.toggle('active',active);
    if(active) item.setAttribute('aria-current','page'); else item.removeAttribute('aria-current');
  }
  $('current-view').textContent={connections:'Conexões',activity:'Atividade',api:'API local',settings:'Configurações'}[view];
  document.title='BrowserAPI · '+$('current-view').textContent;
}
for(const item of document.querySelectorAll('[data-view]')) item.onclick=()=>navigate(item.dataset.view);
$('add-chat').onclick=()=>{navigate('connections');$('connection-form').scrollIntoView({block:'start'});$('session-mode').focus();};
$('prepare-shortcut').onclick=()=>{navigate('settings');$('prepare').focus();};
function sessionFields(){
  const personal=$('session-mode').value==='existing_chrome';
  $('personal-fields').hidden=!personal;
  (personal ? $('personal-fields') : $('common-chat-slot')).appendChild($('chat-fields'));
  document.querySelector('.profile-actions').hidden=!personal;
  $('dedicated-fields').hidden=personal;
  $('configure').textContent=personal?'Conectar →':'Abrir e configurar →';
  if(personal){$('browser').value='chrome';if(!profileRows.length)scanProfiles();}
  controls();
}
$('session-mode').addEventListener('change',sessionFields);
$('browser').addEventListener('change',()=>{
  if($('browser').value!=='chrome'){$('session-mode').value='dedicated';sessionFields();}
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
  if (!state || !state.prompt || incompatible()) return;
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
  $('chat-count').textContent=chats.length;
  if (!chats.some(chat => chat.name === selected)) selected = chats[0]?.name || null;
  for (const chat of chats) {
    const box = document.createElement('div'); box.className = 'chat';
    const label = document.createElement('label');
    const radio = document.createElement('input'); radio.type = 'radio'; radio.name = 'saved-chat';
    radio.value = chat.name; radio.checked = chat.name === selected;
    radio.onchange = () => { selected = chat.name; $('conversation-feedback').textContent = ''; controls(); loadConversation(); };
    label.append(radio, document.createTextNode(chat.name)); box.append(label);
    const info = document.createElement('small');
    info.textContent = chat.invalid ? 'Configuração inválida. Crie outra com um nome diferente.' :
      `${chat.browser}${chat.session_mode === 'existing_chrome' ? ' · Chrome já aberto (configurado)' : ' · perfil separado'} · ${chat.compatible ? 'Último teste passou' : 'Precisa testar'}${chat.checked_at ? ' · ' + chat.checked_at : ''}`;
    if (chat.personal_profile) info.textContent += ` · perfil indicado: ${chat.personal_installation}/${chat.personal_profile} (conta não verificada)`;
    box.append(info);
    const actions=document.createElement('div');actions.className='chat-actions';
    const advanced=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Ajustar ou excluir';advanced.append(summary);
    for (const [caption, operation] of [['Testar agora','check'],['Corrigir campos','repair'],['Usar Chrome já aberto','use_existing'],['Selecionar botão de voz','point_voice'],['Digitar e selecionar Enviar / Enter','point_send']]) {
      const button = document.createElement('button'); button.textContent = caption; button.className = 'secondary';
      button.onclick = () => task(operation, {name: chat.name, ...(operation==='use_existing' ? {personal_profile:$('personal-profile').value}: {})});
      (operation==='point_voice' || operation==='point_send' ? advanced : actions).append(button);
    }
    const remove=document.createElement('button');remove.type='button';remove.className='text-button danger';remove.textContent='Excluir';
    remove.onclick=async()=>{
      if(busy() || incompatible() || !confirm(`Excluir a conexão "${chat.name}"? Isso remove só o cadastro e a conversa exibida no BrowserAPI. Seu Chrome, sua conta e suas conversas no site não são apagados.`))return;
      pending=true;controls();
      try{await api('chat/delete',{name:chat.name});await refresh();}
      catch(err){error(err.message);}
      finally{pending=false;controls();}
    };
    actions.append(remove);
    box.append(actions,advanced);$('chats').append(box);
  }
}
let metricsSignature = '';
const SVG_NS = 'http://www.w3.org/2000/svg';
const milliseconds = value => Number.isFinite(value) ? `${Math.round(value)} ms` : 'N/D';
const compact = value => value >= 1e6 ? (value / 1e6).toFixed(1) + 'M' : value >= 1e3 ? (value / 1e3).toFixed(1) + 'k' : String(value);
const STATUS_SHORT = {success:'Sucesso', not_authorized:'Sem autorização', login_required:'Login', google_login_blocked:'Bloqueio de login',
  rate_limit:'Limite', captcha:'Verificação', timeout:'Tempo esgotado', send_unconfirmed:'Envio não confirmado', send_missing:'Botão não achado',
  composer_missing:'Campo não achado', draft_present:'Rascunho', ambiguous_output:'Ambíguo', contract_invalid:'Formato', wrong_origin:'Endereço',
  page_unavailable:'Página', output_invalid:'Leitura', send_is_microphone:'Voz', not_configured:'Configuração'};
const STATUS_COLOR = {success:'#146c50', not_authorized:'#8a9a91', cancelled:'#b58a2b', operation_error:'#7a6f5f',
  send_unconfirmed:'#a3712f', timeout:'#a3712f', login_required:'#3f6f9a', google_login_blocked:'#3f6f9a',
  rate_limit:'#8a5f2b', captcha:'#8a5f2b', wrong_origin:'#6f5f9a', page_unavailable:'#8a5f2b'};
function statusColor(key) { return STATUS_COLOR[key] || '#a33c2f'; }
function node(tag, attrs = {}) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  return element;
}
function mark(tag, attrs = {}) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  return element;
}
function canvas(container, label, width = 320, height = 132) {
  container.replaceChildren();
  const figure = mark('svg', {viewBox: `0 0 ${width} ${height}`, class: 'chart-svg', role: 'img',
    'aria-label': label, preserveAspectRatio: 'none'});
  container.append(figure);
  return figure;
}
function emptyChart(container, text) {
  container.replaceChildren();
  const paragraph = node('p', {class: 'chart-empty'});
  paragraph.textContent = text;
  container.append(paragraph);
}
function barLabel(figure, x, y, text, anchor = 'middle') {
  const label = mark('text', {x, y, class: 'chart-label', 'text-anchor': anchor});
  label.textContent = text;
  figure.append(label);
}
function statusKey(record) {
  if (record.status) return record.status;
  if (record.phase === 'cancelled') return 'cancelled';
  if (record.phase === 'error') return 'operation_error';
  return 'no_result';
}
function renderStatusChart(history) {
  const counts = new Map();
  for (const record of history) {
    const key = statusKey(record);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const container = $('chart-status');
  const legend = $('status-legend');
  legend.replaceChildren();
  if (!entries.length) { emptyChart(container, 'Sem operações ainda.'); return; }
  const total = entries.reduce((sum, entry) => sum + entry[1], 0);
  const figure = canvas(container, `Resultados por tipo: ${entries.map(([key, value]) => `${STATUS_SHORT[key] || key} ${value}`).join(', ')}`, 300, 132);
  const radius = 46, cx = 66, cy = 66, circumference = 2 * Math.PI * radius;
  let offset = 0;
  for (const [key, value] of entries) {
    const length = (value / total) * circumference;
    const arc = mark('circle', {cx, cy, r: radius, fill: 'none', stroke: statusColor(key), 'stroke-width': 22,
      'stroke-dasharray': `${Math.max(0, length - 2)} ${circumference}`, 'stroke-dashoffset': -offset,
      transform: `rotate(-90 ${cx} ${cy})`});
    const title = mark('title'); title.textContent = `${STATUS_SHORT[key] || key}: ${value}`;
    arc.append(title); figure.append(arc); offset += length;
  }
  const number = mark('text', {x: cx, y: cy + 2, class: 'chart-total', 'text-anchor': 'middle'});
  number.textContent = total; figure.append(number);
  const caption = mark('text', {x: cx, y: cy + 20, class: 'chart-label', 'text-anchor': 'middle'});
  caption.textContent = 'operações'; figure.append(caption);
  entries.slice(0, 6).forEach(([key, value], index) => {
    const item = node('li');
    const swatch = node('span', {class: 'legend-dot'});
    swatch.style.background = statusColor(key);
    item.append(swatch, document.createTextNode(`${STATUS_SHORT[key] || key} · ${value}`));
    legend.append(item);
  });
}
function renderLatencyChart(history) {
  const values = history.filter(record => Number.isFinite(record.timings?.total_ms)).slice(-14);
  const container = $('chart-latency');
  if (!values.length) { emptyChart(container, 'Sem tempos medidos.'); return; }
  const max = Math.max(1, ...values.map(record => record.timings.total_ms));
  const figure = canvas(container, `Duração das últimas ${values.length} operações, máximo ${Math.round(max)} ms`);
  const width = 320 / values.length;
  values.forEach((record, index) => {
    const height = Math.max(2, (record.timings.total_ms / max) * 92);
    const rect = mark('rect', {x: index * width + 3, y: 100 - height, width: Math.max(2, width - 6), height,
      rx: 2, fill: record.status === 'success' ? '#146c50' : '#a3712f'});
    const title = mark('title');
    title.textContent = `#${record.id} ${record.name || ''} · ${milliseconds(record.timings.total_ms)}`;
    rect.append(title); figure.append(rect);
  });
  barLabel(figure, 2, 14, `${Math.round(max)} ms`, 'start');
  barLabel(figure, 2, 120, `#${values[0].id}`, 'start');
  barLabel(figure, 318, 120, `#${values[values.length - 1].id}`, 'end');
}
function renderUsageChart(history) {
  const values = history.filter(record => record.prompt_chars || record.response_chars).slice(-12);
  const container = $('chart-usage');
  const note = $('usage-note');
  if (!values.length) {
    emptyChart(container, 'Sem consumo medido.');
    note.textContent = 'O site não informa tokens; medimos caracteres enviados e recebidos.';
    return;
  }
  const max = Math.max(1, ...values.map(record => Math.max(record.prompt_chars || 0, record.response_chars || 0)));
  const figure = canvas(container, `Caracteres por operação, ${values.length} operações`);
  const width = 320 / values.length;
  values.forEach((record, index) => {
    const sent = ((record.prompt_chars || 0) / max) * 84;
    const received = ((record.response_chars || 0) / max) * 84;
    figure.append(mark('rect', {x: index * width + 4, y: 96 - sent, width: Math.max(2, width / 2 - 4), height: Math.max(1, sent), rx: 2, fill: '#3f6f9a'}));
    figure.append(mark('rect', {x: index * width + width / 2, y: 96 - received, width: Math.max(2, width / 2 - 4), height: Math.max(1, received), rx: 2, fill: '#146c50'}));
  });
  barLabel(figure, 2, 14, compact(max), 'start');
  barLabel(figure, 2, 120, 'enviado', 'start');
  barLabel(figure, 318, 120, 'recebido', 'end');
  const usage = state?.telemetry?.usage || {};
  const total = (usage.prompt_chars || 0) + (usage.response_chars || 0);
  const estimate = Math.round(total / 4);
  note.textContent = `Nesta sessão: ${compact(usage.prompt_chars || 0)} enviados + ${compact(usage.response_chars || 0)} recebidos. `
    + `≈ ${compact(estimate)} tokens por estimativa grosseira (4 caracteres/token), não é o número do provedor.`;
}
function renderStagesChart(history) {
  const latest = [...history].reverse().find(record => record.status && record.status !== 'not_authorized');
  const container = $('chart-stages');
  const details = $('stage-details');
  details.replaceChildren();
  const labels = {browser_start_ms:'Navegador', page_open_ms:'Aba', preflight_ms:'Pré-voo', send_pipeline_ms:'Envio',
    fill_ms:'↳ digitar', send_ms:'↳ clicar', response_wait_ms:'Espera', parse_ms:'Leitura', total_ms:'Fluxo',
    ttft_dom_ms:'1º conteúdo', capture_overhead_ms:'Atraso', manual_wait_ms:'Sua espera', operation_wall_ms:'Operação'};
  if (!latest) { emptyChart(container, 'Sem resultado medido.'); return; }
  const entries = Object.entries(labels).map(([key, label]) => [label, latest.timings?.[key]])
    .filter(([, value]) => Number.isFinite(value));
  if (!entries.length) { emptyChart(container, 'Sem etapas medidas.'); return; }
  const max = Math.max(1, ...entries.map(([, value]) => value));
  const figure = canvas(container, `Etapas do último resultado: ${entries.map(([label, value]) => `${label} ${Math.round(value)} ms`).join(', ')}`,
    320, entries.length * 22 + 10);
  entries.forEach(([label, value], index) => {
    const width = Math.max(2, (value / max) * 190);
    figure.append(mark('rect', {x: 96, y: index * 22 + 4, width, height: 12, rx: 2,
      fill: label.startsWith('↳') ? '#8aa79a' : '#146c50'}));
    barLabel(figure, 90, index * 22 + 14, label, 'end');
    barLabel(figure, 96 + width + 4, index * 22 + 14, `${Math.round(value)} ms`, 'start');
  });
  for (const [label, value] of entries) {
    const item = node('li'); item.textContent = `${label}: ${milliseconds(value)}`; details.append(item);
  }
}
function renderSuccessChart(history) {
  const requests = history.filter(record => record.status && record.status !== 'not_authorized');
  const container = $('chart-success');
  if (!requests.length) { emptyChart(container, 'Sem resultados.'); return; }
  const figure = canvas(container, 'Taxa de sucesso acumulada por operação', 320, 120);
  const points = [];
  let hits = 0;
  requests.forEach((record, index) => {
    if (record.status === 'success') hits += 1;
    const x = 8 + (index / Math.max(1, requests.length - 1)) * 296;
    const y = 96 - (hits / (index + 1)) * 80;
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  });
  figure.append(mark('line', {x1: 8, y1: 96, x2: 312, y2: 96, stroke: '#dfe7e2', 'stroke-width': 1}));
  figure.append(mark('polyline', {points: points.join(' '), fill: 'none', stroke: '#146c50', 'stroke-width': 2.5,
    'stroke-linejoin': 'round'}));
  const last = requests[requests.length - 1];
  const rate = Math.round((hits / requests.length) * 100);
  barLabel(figure, 8, 16, `${rate}%`, 'start');
  barLabel(figure, 312, 16, `${requests.length} resultados`, 'end');
  barLabel(figure, 8, 112, last.at ? String(last.at).slice(11, 19) : '', 'start');
}
function renderMetrics(value) {
  const t = value.telemetry;
  if (!t) return;
  const signature = JSON.stringify([t, value.chats, value.phase]);
  if (signature === metricsSignature) return;
  metricsSignature = signature;
  $('stat-requests').textContent = t.requests;
  $('stat-success').textContent = Number.isFinite(t.success_rate) ? `${t.success_rate}%` : 'N/D';
  $('stat-average').textContent = milliseconds(t.average_ms);
  $('stat-p95').textContent = milliseconds(t.p95_ms);
  $('stat-cancelled').textContent = t.cancelled;
  $('stat-tokens').textContent = 'Não medido';
  $('metrics-scope').textContent = `${t.successes} sucessos · ${t.failures} falhas · ${t.denied} sem autorização · ${t.operation_errors} erros de operação · ${t.timed_requests} com latência. Janela ${t.operations}/${t.limit}; inclui verificações e mensagens, não chamadas a uma API.`;
  const labels = {online:'Online (observado)', login_required:'Login necessário', auth_blocked:'Login bloqueado',
    rate_limited:'Limite de uso', human_required:'Verificação humana', degraded:'Resposta não confirmada',
    unavailable:'Não acessível', needs_attention:'Precisa de atenção', not_observed:'A verificar',
    interrupted:'Interrompida', busy:value.phase === 'waiting' ? 'Aguardando você' : 'Em andamento'};
  $('source-health').replaceChildren();
  for (const chat of value.chats) {
    const health = t.sources[chat.name];
    const state = health ? (health.stale ? 'Observação antiga' : labels[health.state] || 'Não observado') : 'Não observado';
    const item = node('li');
    const swatch = node('span', {class: 'legend-dot'});
    swatch.style.background = health && !health.stale && health.state === 'online' ? '#146c50' : '#a3712f';
    item.append(swatch, document.createTextNode(`${chat.name} · ${state}`));
    $('source-health').append(item);
  }
  if (!value.chats.length) { const item = node('li'); item.textContent = 'Nenhum chat configurado.'; $('source-health').append(item); }
  renderStatusChart(t.history);
  renderLatencyChart(t.history);
  renderUsageChart(t.history);
  renderStagesChart(t.history);
  renderSuccessChart(t.history);
}
function render(value) {
  if (value.updates?.managed && value.version !== PANEL_VERSION && sessionStorage.getItem('browserapi-reloaded-version') !== value.version) {
    sessionStorage.setItem('browserapi-reloaded-version', value.version);
    location.reload();
    return;
  }
  $('updates-status').textContent = [value.updates?.message,value.updates?.rollback_notice].filter(Boolean).join(' ') || 'Atualização não gerenciada.';
  $('auto-update').checked = !!value.updates?.enabled;
  $('auto-update').disabled = !value.updates?.managed;

  const oldPrompt = state?.prompt?.id;
  const previousPhase = state?.phase;
  state = value;
  if (state.phase === 'error') error(state.messages[state.messages.length - 1] || 'Não foi possível conectar. Tente novamente.');
  else if (previousPhase === 'error') error('');
  $('version-status').textContent = `Painel ${PANEL_VERSION} · programa ${state.version || 'antigo (sem identificação)'}`;
  if (incompatible()) error('O painel e o programa em execução são de versões diferentes. Não prossiga com os campos. Reinicie o computador e abra BrowserAPI pelo menu; fechar só a aba não encerra a versão antiga.');
  const labels = {idle:'Pronto',running:'Trabalhando…',waiting:'Aguardando você',done:'Concluído',error:'Precisa de atenção',cancelled:'Interrompido',updating:'Aplicando atualização…'};
  $('phase').textContent = labels[state.phase] || state.phase;
  $('prepared-label').textContent = state.prepared ? 'Componente de automação disponível. O teste confirma o navegador.' : 'Primeira vez? Clique em Preparar BrowserAPI.';
  renderChats(state.chats);
  loadConversation();
  $('log').textContent = state.messages.join('\n\n');
  document.querySelector('.progress').hidden=!state.prompt && !state.receipt && !state.messages.length && !['running','waiting'].includes(state.phase);
  $('prompt').hidden = !state.prompt;
  if (state.prompt) {
    $('question').textContent = state.prompt.text;
    const help = [
      [/A SUA PERGUNTA JÁ ENVIADA/i, 'Clique no balão com a pergunta que você enviou. Não é o campo de digitar.'],
      [/A RESPOSTA DO CHAT/i, 'Clique no balão com a resposta do chat.'],
      [/campo onde você digita/i, 'Clique dentro da caixa de texto vazia do chat.'],
      [/digite algo SEM enviar/i, 'Escreva uma frase no chat, sem enviar, e volte para clicar em Continuar.'],
      [/Autoriza/i, 'Nada é enviado sem este Sim.'],
    ].find(([pattern]) => pattern.test(state.prompt.text));
    $('prompt-help').textContent = help ? help[1] : 'Clique no elemento dentro da janela do chat. Esc cancela.';
    const yesno = state.prompt.kind === 'yesno';
    $('yes').hidden = $('no').hidden = !yesno;
    $('continue').hidden = yesno;
    if (oldPrompt !== state.prompt.id) {
      for (const id of ['yes','no','continue']) $(id).disabled = incompatible();
      $('continue').textContent = /digite algo/i.test(state.prompt.text) ? 'Já digitei · Selecionar Enviar' : 'Continuar';
      document.querySelector('.progress').scrollIntoView({block:'nearest'});
      (yesno ? $('yes') : $('continue')).focus();
    }
  }
  $('receipt').hidden = !state.receipt;
  if (state.receipt) {
    const receipt = state.receipt;
    $('result-title').textContent = receipt.compatible_in_this_run ? 'Funcionou neste teste ✓' : (receipt.message || 'Ainda não funcionou');
    $('result-action').textContent = (receipt.action || '').replaceAll('Execute repair', 'Clique em Corrigir campos').replaceAll('Execute configure ou repair', 'Clique em Abrir e configurar ou Corrigir campos').replaceAll('repita check', 'clique em Testar agora').replaceAll('execute repair', 'clique em Corrigir campos');
    const stages = {not_started:'antes do teste',navigation:'verificação do endereço',preflight:'verificação antes do envio',send_pipeline:'envio',response_wait:'espera da resposta',parse:'leitura da resposta',completed:'concluído'};
    const stopped = receipt.send_state === 'not_sent';
    const timing = receipt.timings?.total_ms;
    const origins = receipt.diagnostics?.expected_origin && receipt.diagnostics?.observed_origin
      ? ` Esperado: ${receipt.diagnostics.expected_origin}. Aberto: ${receipt.diagnostics.observed_origin}.` : '';
    const profile = receipt.diagnostics?.profile_directory ? ` Perfil confirmado pelo Chrome: ${receipt.diagnostics.profile_directory}. A conta do site continua por sua conferência.` : '';
    $('result-timing').textContent = (stopped
      ? `Nenhuma mensagem enviada. Etapa: ${stages[receipt.stage] || 'antes do envio'}. Não houve medição de resposta do modelo.`
      : (timing !== undefined ? `Tempo do fluxo: ${Math.round(timing)} ms (envio e observação; não é latência de API).` : 'Confira a conversa antes de repetir: o envio pode ter ocorrido.')) + origins + profile;
  }
  renderMetrics(value);
  renderService(value);
  controls();
}
async function refresh() { render(await api('state')); }
async function poll() {
  try { await refresh(); }
  catch (err) { error(err.message || 'O painel perdeu a conexão. Abra BrowserAPI novamente pelo menu.'); }
  setTimeout(poll, 650);
}
poll();

$('auto-update').addEventListener('change', async () => { try { await api('updates',{enabled:$('auto-update').checked}); await refresh(); } catch (err) { error(err.message); } });

let profileRows=[];
async function scanProfiles(){
  const previous=$('personal-profile').value;
  $('scan-profiles').disabled=true;
  try{
    const data=await api('profiles');profileRows=data.profiles;
    $('personal-profile').replaceChildren();
    const supported=profileRows.filter(p=>p.connectable);
    if(!supported.length)$('personal-profile').append(new Option('Nenhum perfil do Chrome encontrado',''));
    for(const p of supported){
      const installation={chrome:'Chrome','chrome-beta':'Chrome Beta','chrome-unstable':'Chrome Dev'}[p.installation];
      $('personal-profile').append(new Option(`${p.directory} · ${p.label} · ${installation}`,p.id));
    }
    if(supported.some(p=>p.id===previous))$('personal-profile').value=previous;
    profileNote();
  }catch(err){profileFeedback(err.message,true);}
  finally{$('scan-profiles').disabled=busy() || incompatible();profileControls();}
}
function profileNote(){
  const p=profileRows.find(p=>p.id===$('personal-profile').value);
  $('profiles-note').hidden=!!p && p.openable!==false;
  $('profiles-note').textContent=!p?'Nenhum perfil disponível. Abra seu Chrome normalmente e atualize a lista. Não criaremos um perfil vazio no lugar.':
    p.openable===false?'Perfil encontrado, mas o executável do Chrome não está disponível. Abra-o pelo menu do computador e depois conecte.':
    p.endpoint_available?'Conexão local encontrada. Ainda é necessário autorizar no Chrome e conferir a conta.':
    'Perfil encontrado. Abra-o e configure a permissão antes de conectar (Chrome 144+).';
  profileControls();
}
function profileControls(){
  const p=profileRows.find(p=>p.id===$('personal-profile').value);
  for(const id of ['open-profile','open-permission']) $(id).disabled=busy() || incompatible() || !p || p.openable===false;
  $('personal-profile').disabled=busy() || incompatible();
}
function profileFeedback(text,failed=false){
  $('profile-feedback').textContent=text;$('profile-feedback').hidden=!text;
  $('profile-feedback').dataset.error=String(failed);
}
async function openProfile(destination){
  if(busy() || incompatible())return;
  pending=true;controls();profileFeedback('Pedindo ao Chrome para abrir o perfil…');
  try{
    await api('profile',{profile:$('personal-profile').value,destination,provider:$('provider').value,url:$('url').value});
    profileFeedback(destination==='permission'?'No Chrome que abriu, digite chrome://inspect/#remote-debugging na barra de endereço (o Chrome não deixa programas abrirem essa página) e ative a Depuração remota. Depois volte e conecte.':'Chrome solicitado. Confira sua conta e clique em Conectar.');
  }catch(err){profileFeedback(err.message,true);}
  finally{pending=false;controls();}
}
$('personal-profile').onchange=()=>{profileFeedback('');profileNote();};
$('scan-profiles').onclick=scanProfiles;
$('open-profile').onclick=()=>openProfile('chat');
$('open-permission').onclick=()=>openProfile('permission');
let serviceSignature='';
function renderService(value){
  const a=value.api_service || {};
  $('api-status').textContent=a.message || 'API não disponível neste modo de execução.';
  $('api-toggle').textContent=a.enabled ? 'Desativar API' : 'Autorizar e iniciar API';
  $('api-toggle').disabled=!a.available || incompatible() || (!a.enabled && busy());
  $('api-url').value=a.url || ''; $('api-key').value=a.key || '';
  $('copy-api-url').disabled=!a.url; $('copy-api-key').disabled=!a.key; $('api-show').disabled=!a.key;
  const signature=JSON.stringify([a.enabled,a.names,a.headless,a.lightweight,a.retrieval,a.fallback,a.remember,a.personal_consent,value.chats]);
  if(signature!==serviceSignature){
    serviceSignature=signature;
    const old=[...$('api-models').selectedOptions].map(o=>o.value);
    $('api-models').replaceChildren();
    for(const chat of value.chats){
      const option=new Option(`${chat.name}${chat.compatible ? '' : ' · testar primeiro'}`,chat.name);
      option.disabled=!chat.compatible;
      option.selected=(a.names?.length ? a.names : old.length ? old : [value.chats.find(c=>c.compatible)?.name]).includes(chat.name);
      $('api-models').append(option);
    }
    for(const [id,key] of [['api-headless','headless'],['api-lightweight','lightweight'],['api-retrieval','retrieval'],['api-fallback','fallback'],['api-personal','personal_consent'],['api-remember','remember']]) $(id).checked=!!a[key];
  }
  for(const id of ['api-models','api-headless','api-lightweight','api-retrieval','api-fallback','api-personal','api-remember']) $(id).disabled=!!a.enabled || busy() || incompatible();
}
$('api-show').onclick=()=>{$('api-key').type=$('api-key').type==='password' ? 'text':'password';};
$('api-toggle').onclick=async()=>{
  const active=!!state?.api_service?.enabled;
  if(!active && !confirm('Autorizar agentes com esta chave a enviar mensagens pelos chats selecionados, sem confirmação por chamada? Mantenha login/modelo corretos. Não compartilhe a chave.')) return;
  try {
    await api('service',{enabled:!active,names:[...$('api-models').selectedOptions].map(o=>o.value),headless:$('api-headless').checked,lightweight:$('api-lightweight').checked,retrieval:$('api-retrieval').checked,fallback:$('api-fallback').checked,personal_consent:$('api-personal').checked,remember:$('api-remember').checked});
    await refresh();
  } catch(err){error(err.message);}
};

$('api-clear').onclick=async()=>{
  if(!confirm('Apagar histórico RAG e desativar a API? Não apaga conversas no provedor nem cópias fora do programa. Aguarde tarefas em andamento.')) return;
  try{await api('service',{enabled:false,clear_history:true});await refresh();}catch(err){error(err.message);}
};
$('api-rotate').onclick=async()=>{
  if(!confirm('Revogar a chave e o registro de idempotência? Reconfigure os agentes. Isso não desfaz envios; não repita pedidos antigos sem conferir a página.')) return;
  try{await api('service',{enabled:false,rotate:true});await refresh();}catch(err){error(err.message);}
};

async function copyValue(id){
  try{await navigator.clipboard.writeText($(id).value);$('copy-feedback').textContent=id==='api-key'?'Chave copiada. Não compartilhe.':'Endereço copiado.';}
  catch(err){$(id).focus();$(id).select();$('copy-feedback').textContent='Selecione e copie o campo com Ctrl+C.';}
}
$('copy-api-url').onclick=()=>copyValue('api-url');
$('copy-api-key').onclick=()=>copyValue('api-key');

$('conversation-copy').onclick=async()=>{
  const last=[...((conversationData()?.messages)||[])].reverse().find(message=>message.role==='assistant');
  if(!last) return;
  try{await navigator.clipboard.writeText(last.text);$('conversation-feedback').textContent='Resposta copiada.';}
  catch(err){$('conversation-feedback').textContent='Não foi possível copiar. Selecione o texto na conversa e use Ctrl+C.';}
};
$('conversation-clear').onclick=async()=>{
  if(busy() || incompatible() || !selected) return;
  if(!confirm('Limpar a conversa exibida no painel? A conversa do site NÃO será apagada; o painel só deixa de mostrar este texto.')) return;
  try{
    await api('conversation/clear',{name:selected});
    conversation={name:null,revision:-1,data:null};
    $('conversation-feedback').textContent='Conversa do painel limpa. Nada foi enviado.';
    await refresh();
    await loadConversation(true);
  }catch(err){error(err.message);}
};
sessionFields();
