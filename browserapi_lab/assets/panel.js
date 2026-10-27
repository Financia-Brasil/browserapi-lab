'use strict';
const PANEL_VERSION = '0.5.1';
const $ = id => document.getElementById(id);
const fragment = location.hash.slice(1);
const token = /^[A-Za-z0-9_-]{32,128}$/.test(fragment) ? fragment : sessionStorage.getItem('browserapi-token') || '';
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
function busy() { return pending || !!(state && ['running','waiting','updating'].includes(state.phase)); }
function controls() {
  for (const id of ['configure','prepare','doctor','browser','provider','name','url','session-mode','scan-profiles','prepare-shortcut']) $(id).disabled = busy() || incompatible();
  $('ask').disabled = busy() || incompatible() || !selected;
  $('composer-panel').hidden=!selected;
  $('selected-label').textContent=selected || '';
  profileControls();
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
    radio.onchange = () => { selected = chat.name; controls(); };
    label.append(radio, document.createTextNode(chat.name)); box.append(label);
    const info = document.createElement('small');
    info.textContent = chat.invalid ? 'Configuração inválida. Crie outra com um nome diferente.' :
      `${chat.browser}${chat.session_mode === 'existing_chrome' ? ' · Chrome já aberto (configurado)' : ' · perfil separado'} · ${chat.compatible ? 'Último teste passou' : 'Precisa testar'}${chat.checked_at ? ' · ' + chat.checked_at : ''}`;
    if (chat.personal_profile) info.textContent += ` · perfil indicado: ${chat.personal_installation}/${chat.personal_profile} (conta não verificada)`;
    box.append(info);
    const actions=document.createElement('div');actions.className='chat-actions';
    const advanced=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Ajustar campos e botão de voz';advanced.append(summary);
    for (const [caption, operation] of [['Usar Chrome já aberto','use_existing'],['Selecionar botão de voz','point_voice'],['Digitar e selecionar Enviar / Enter','point_send'],['Testar agora','check'],['Corrigir campos','repair']]) {
      const button = document.createElement('button'); button.textContent = caption; button.className = 'secondary';
      button.onclick = () => task(operation, {name: chat.name, ...(operation==='use_existing' ? {personal_profile:$('personal-profile').value}: {})});
      (operation==='point_voice' || operation==='point_send' ? advanced : actions).append(button);
    }
    box.append(actions,advanced);$('chats').append(box);
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
  if (value.updates?.managed && value.version !== PANEL_VERSION && sessionStorage.getItem('browserapi-reloaded-version') !== value.version) {
    sessionStorage.setItem('browserapi-reloaded-version', value.version);
    location.reload();
    return;
  }
  $('updates-status').textContent = [value.updates?.message,value.updates?.rollback_notice].filter(Boolean).join(' ') || 'Atualização não gerenciada.';
  $('auto-update').checked = !!value.updates?.enabled;
  $('auto-update').disabled = !value.updates?.managed;

  const oldPrompt = state?.prompt?.id;
  state = value;
  $('version-status').textContent = `Painel ${PANEL_VERSION} · programa ${state.version || 'antigo (sem identificação)'}`;
  if (incompatible()) error('O painel e o programa em execução são de versões diferentes. Não prossiga com os campos. Reinicie o computador e abra BrowserAPI pelo menu; fechar só a aba não encerra a versão antiga.');
  const labels = {idle:'Pronto',running:'Trabalhando…',waiting:'Aguardando você',done:'Concluído',error:'Precisa de atenção',cancelled:'Interrompido',updating:'Aplicando atualização…'};
  $('phase').textContent = labels[state.phase] || state.phase;
  $('prepared-label').textContent = state.prepared ? 'Componente de automação disponível. O teste confirma o navegador.' : 'Primeira vez? Clique em Preparar BrowserAPI.';
  renderChats(state.chats);
  $('log').textContent = state.messages.join('\n\n');
  document.querySelector('.progress').hidden=!state.prompt && !state.receipt && !state.messages.length && !['running','waiting'].includes(state.phase);
  $('prompt').hidden = !state.prompt;
  if (state.prompt) {
    $('question').textContent = state.prompt.text;
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
    $('result-title').textContent = receipt.compatible_in_this_run ? 'Funcionou neste teste ✓' : 'Ainda não funcionou';
    $('result-action').textContent = (receipt.action || '').replaceAll('Execute repair', 'Clique em Corrigir campos').replaceAll('Execute configure ou repair', 'Clique em Abrir e configurar ou Corrigir campos').replaceAll('repita check', 'clique em Testar agora').replaceAll('execute repair', 'clique em Corrigir campos');
    $('result-timing').textContent = receipt.timings?.total_ms !== undefined ? `Tempo observado: ${Math.round(receipt.timings.total_ms)} ms (inclui espera da resposta).` : '';
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
      $('personal-profile').append(new Option(`${p.label} · ${installation} (${p.directory})`,p.id));
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
    profileFeedback(destination==='permission'?'No Chrome, habilite Depuração remota. Depois volte, atualize a lista e conecte.':'Chrome solicitado. Confira sua conta e clique em Conectar.');
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
sessionFields();
