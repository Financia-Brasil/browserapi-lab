'use strict';
const PANEL_VERSION = '0.2.0+ubuntu1';
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
function incompatible() { return !!state && state.version !== PANEL_VERSION; }
function busy() { return pending || !!(state && ['running','waiting'].includes(state.phase)); }
function controls() {
  for (const id of ['configure','prepare','doctor','browser','provider','name','url','session-mode']) $(id).disabled = busy() || incompatible();
  $('ask').disabled = busy() || incompatible() || !selected;
  $('cancel').disabled = !busy();
  for (const button of $('chats').querySelectorAll('button,input')) button.disabled = busy() || incompatible();
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
      `${chat.browser}${chat.session_mode === 'existing_chrome' ? ' · Chrome já aberto (configurado)' : ' · perfil separado'} · ${chat.compatible ? 'Último teste passou' : 'Precisa testar'}${chat.checked_at ? ' · ' + chat.checked_at : ''}`;
    box.append(info);
    for (const [caption, operation] of [['Usar Chrome já aberto','use_existing'],['Selecionar botão de voz','point_voice'],['Digitar e selecionar Enviar / Enter','point_send'],['Testar agora','check'],['Corrigir campos','repair']]) {
      const button = document.createElement('button'); button.textContent = caption; button.className = 'secondary';
      button.onclick = () => task(operation, {name: chat.name}); box.append(button);
    }
    $('chats').append(box);
  }
}
let metricsSignature = '';
const milliseconds = value => Number.isFinite(value) ? `${Math.round(value)} ms` : 'N/D';
function renderMetrics(value) {
  const t = value.telemetry;
  if (!t) return;
  const signature = JSON.stringify([t,value.chats,value.phase]);
  if (signature === metricsSignature) return;
  metricsSignature = signature;
  $('stat-requests').textContent = t.requests;
  $('stat-success').textContent = Number.isFinite(t.success_rate) ? `${t.success_rate}%` : 'N/D';
  $('stat-average').textContent = milliseconds(t.average_ms);
  $('stat-p95').textContent = milliseconds(t.p95_ms);
  $('stat-cancelled').textContent = t.cancelled;
  $('stat-tokens').textContent = 'Não disponível';
  $('metrics-scope').textContent = `${t.successes} sucessos · ${t.failures} falhas · ${t.denied} sem autorização · ${t.operation_errors} erros de operação · ${t.timed_requests} resultados com latência. Janela: ${t.operations}/${t.limit} operações; inclui verificações e mensagens, não é contagem de chamadas a uma API.`;
  const labels = {online:'Online (observado)',login_required:'Login necessário',auth_blocked:'Login bloqueado',rate_limited:'Limite de uso observado',human_required:'Verificação humana',degraded:'Resposta não confirmada',unavailable:'Não acessível nesta execução',needs_attention:'Precisa de atenção',not_observed:'Configuração/estado a verificar',interrupted:'Interrompida: confira a página',busy:value.phase === 'waiting' ? 'Aguardando você' : 'Operação em andamento'};
  $('source-health').replaceChildren();
  for (const chat of value.chats) {
    const health = t.sources[chat.name];
    const item = document.createElement('li');
    item.textContent = `${chat.name} · ${health ? (health.stale ? 'Observação antiga' : labels[health.state] || 'Não observado') : 'Não observado nesta sessão'}${health?.at ? ' · ' + health.at : ''}`;
    $('source-health').append(item);
  }
  if (!value.chats.length) { const item = document.createElement('li'); item.textContent = 'Nenhum chat configurado.'; $('source-health').append(item); }
  const latest = [...t.history].reverse().find(record => record.status && record.status !== 'not_authorized');
  const stageLabels = {browser_start_ms:'Iniciar/conectar navegador (pode incluir permissão nativa)',page_open_ms:'Abrir ou encontrar aba',preflight_ms:'Pré-voo e preparação',send_pipeline_ms:'Pipeline de envio (inclui confirmação)',fill_ms:'↳ Preencher campo',send_ms:'↳ Ativação do envio',response_wait_ms:'Esperar término da resposta',parse_ms:'Parsing e validação',total_ms:'Fluxo da mensagem (sem login/abertura)',ttft_dom_ms:'Primeiro conteúdo no DOM',capture_overhead_ms:'Tempo desde a última mutação',manual_wait_ms:'Espera por você no painel',operation_wall_ms:'Operação inteira (inclui esperas)'};
  $('stage-timings').replaceChildren();
  for (const [key,label] of Object.entries(stageLabels)) {
    const row = document.createElement('tr'); const title = document.createElement('td'); const duration = document.createElement('td');
    title.textContent = label; duration.textContent = milliseconds(latest?.timings[key]); row.append(title,duration); $('stage-timings').append(row);
  }
  const history = t.history.filter(record => Number.isFinite(record.timings.total_ms)).slice(-30);
  const max = Math.max(1,...history.map(record => record.timings.total_ms));
  $('latency-history').replaceChildren();
  for (const record of history) {
    const item = document.createElement('li'); const bar = document.createElement('meter');
    bar.min = 0; bar.max = max; bar.value = record.timings.total_ms; bar.setAttribute('aria-label',`Latência da execução ${record.id}`);
    item.append(document.createTextNode(`#${record.id} ${record.name || ''} · ${record.status} `),bar,document.createTextNode(milliseconds(record.timings.total_ms)));
    $('latency-history').append(item);
  }
}
function render(value) {
  const oldPrompt = state?.prompt?.id;
  state = value;
  $('version-status').textContent = `Painel ${PANEL_VERSION} · programa ${state.version || 'antigo (sem identificação)'}`;
  if (incompatible()) error('O painel e o programa em execução são de versões diferentes. Não prossiga com os campos. Reinicie o computador e abra BrowserAPI pelo menu; fechar só a aba não encerra a versão antiga.');
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
      for (const id of ['yes','no','continue']) $(id).disabled = incompatible();
      $('continue').textContent = /digite algo/i.test(state.prompt.text) ? 'Já digitei · Selecionar Enviar' : 'Continuar';
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
  renderMetrics(value);
  controls();
}
async function refresh() { render(await api('state')); }
async function poll() {
  try { await refresh(); }
  catch (err) { error(err.message || 'O painel perdeu a conexão. Abra BrowserAPI novamente pelo menu.'); }
  setTimeout(poll, 650);
}
poll();
