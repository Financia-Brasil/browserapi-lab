/* Checagem do painel sem navegador (jsdom): fluxo rápido, copiar-e-colar e
 * conferência de endereço.
 *
 * Por que existe: os testes de navegador só rodam no CI. Um `id` que deixa de
 * existir no HTML já quebrou o painel antes (aba Atividade) e o erro só aparecia
 * no CI; aqui o painel.js roda de verdade contra um estado falso, então
 * referência quebrada vira falha local em segundos.
 *
 * Uso:
 *   npm install jsdom          # uma vez, fora do repositório
 *   node scripts/panel_jsdom_check.js /caminho/do/repositorio
 *
 * Isto NÃO substitui os testes de navegador: jsdom não tem layout nem CSP real.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const repo = process.argv[2] || process.cwd();
const failures = [];
function check(name, condition, detail) {
  console.log((condition ? 'ok   ' : 'FAIL ') + name
    + (detail === undefined ? '' : ' -> ' + JSON.stringify(detail)));
  if (!condition) failures.push(name);
}

/* O painel recusa operar quando a versão do programa difere do painel; o
 * estado falso usa a versão real para exercitar o caminho normal. */
const PANEL_VERSION = (/PANEL_VERSION = '([^']+)'/.exec(
  fs.readFileSync(path.join(repo, 'browserapi_lab/assets/panel.js'), 'utf8')) || [])[1];

function state(overrides = {}) {
  return {
    version: PANEL_VERSION, phase: 'idle', prompt: null, messages: [], receipt: null,
    chats: [], prepared: true,
    telemetry: {
      requests: 0, successes: 0, failures: 0, denied: 0, operation_errors: 0,
      cancelled: 0, timed_requests: 0, success_rate: null, average_ms: null,
      p95_ms: null, operations: 0, limit: 100, sources: {}, history: [],
      usage: {prompt_chars: 0, response_chars: 0},
    },
    api_service: {
      available: true, enabled: false, port: 8765,
      url: 'http://127.0.0.1:8765/v1',
      chat_url: 'http://127.0.0.1:8765/v1/chat/completions',
      models_url: 'http://127.0.0.1:8765/v1/models',
      example: 'curl http://127.0.0.1:8765/v1/chat/completions',
      messages_url: 'http://127.0.0.1:8765/v1/messages',
      agent_example: 'export ANTHROPIC_BASE_URL="http://127.0.0.1:8765"\n'
        + 'export ANTHROPIC_AUTH_TOKEN="<cole aqui a chave local>"',
      message: 'Desativada. Autorize explicitamente antes de usar agentes.',
      limits: {message_chars: 20000, conversation_chars: 200000, block_chars: 8000,
               max_blocks: 4, max_parts: 24, restore_chars: 14000,
               tool_result_chars: 4000, keep_recent: 6},
      context: {'meu-gemini': {characters: 12000, turns: 3, conversation: 'https://chat'}},
    },
    updates: {managed: false, enabled: false, message: 'Atualização não gerenciada.'},
    ...overrides,
  };
}

async function main() {
  const html = fs.readFileSync(path.join(repo, 'browserapi_lab/assets/panel.html'), 'utf8')
    .replace('<script defer src="/panel.js"></script>', '');
  const script = fs.readFileSync(path.join(repo, 'browserapi_lab/assets/panel.js'), 'utf8');
  let current = state();
  const requests = [];
  const dom = new JSDOM(html, {url: 'http://127.0.0.1:8765/', runScripts: 'outside-only',
    pretendToBeVisual: true});
  const win = dom.window;
  win.fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    requests.push({url, body});
    let data = {ok: true};
    if (url === '/api/state') data = current;
    if (url === '/api/profiles') data = {profiles: []};
    if (url === '/api/chrome-debug') data = {ok: true, port: 9222, auto_launch: true,
      installed: true, listening: false, saved: body.name,
      message: 'Atalho criado para a porta 9222.'};
    if (url === '/api/url-check') {
      const text = String(body.url || '');
      const good = text.endsWith('/v1/chat/completions');
      data = {ok: good, message: good ? 'Endereço completo e correto.' : 'Falta a rota de chat.'};
    }
    return {ok: true, status: 200, json: async () => data};
  };
  Object.defineProperty(win.navigator, 'clipboard', {value: {writeText: async () => {}},
    configurable: true});
  win.confirm = () => false;
  const painted = [];
  win.HTMLElement.prototype.scrollIntoView = () => {};

  // Ponte só do harness: o painel.js roda em modo estrito dentro do eval, então
  // as funções não viram globais sozinhas (em produção é um <script> normal).
  win.eval(script + '\n;window.__harness = {refresh, flowStage, renderQuickFlow};');
  const settle = () => new Promise(resolve => setTimeout(resolve, 30));
  await settle();
  painted.push(win.document.querySelector('#quick-action').textContent);

  const q = id => win.document.getElementById(id);
  check('painel carrega sem referência quebrada',
    ['quick-title', 'quick-detail', 'quick-note', 'api-endpoint', 'url-check-input']
      .every(id => q(id)) && q('quick-title').textContent.length > 0,
    q('quick-title').textContent);
  check('passo 1: orienta a usar o formulário, sem segundo botão Conectar',
    q('quick-action').hidden && q('quick-detail').textContent.includes('clique em Conectar'),
    [q('quick-action').hidden, q('quick-detail').textContent]);
  check('passo 1 marcado na lista',
    q('quick-steps').children[0].dataset.state === 'current');

  // Estado: um chat salvo, ainda sem teste → passo 2.
  current = state({chats: [{name: 'meu-gemini', provider: 'gemini', browser: 'chrome',
    session_mode: 'existing_chrome', compatible: false, conversation: {turns: 0, revision: 0}}]});
  win.__harness.refresh();
  await settle();
  check('passo 2: testar', !q('quick-action').hidden
    && q('quick-action').textContent === 'Testar a conexão',
    q('quick-action').textContent);
  check('nota diz qual conexão está em jogo', q('quick-note').textContent.includes('meu-gemini'),
    q('quick-note').textContent);

  // Mesmo chat testado → passo 3 (ligar API).
  current = state({chats: [{name: 'meu-gemini', provider: 'gemini', browser: 'chrome',
    session_mode: 'existing_chrome', compatible: true, conversation: {turns: 2, revision: 1}}]});
  win.__harness.refresh();
  await settle();
  check('passo 3: ligar API', q('quick-action').textContent === 'Ligar API',
    q('quick-action').textContent);
  check('endereço completo preenchido',
    q('api-endpoint').value === 'http://127.0.0.1:8765/v1/chat/completions', q('api-endpoint').value);
  check('endereço base separado (/v1)',
    q('api-url').value === 'http://127.0.0.1:8765/v1', q('api-url').value);
  check('exemplo copiável aparece', q('api-snippet').textContent.includes('curl'),
    q('api-snippet').textContent);
  check('variáveis do agente aparecem (Claude Code)',
    q('agent-snippet').textContent.includes('ANTHROPIC_BASE_URL')
    && q('agent-snippet').textContent.includes('ANTHROPIC_AUTH_TOKEN'),
    q('agent-snippet').textContent);
  check('rota do agente é /v1/messages',
    q('messages-url-display').textContent === '/v1/messages',
    q('messages-url-display').textContent);
  check('janela de contexto aparece com os dois tetos',
    Number(q('api-message-chars').value) === 20000
    && Number(q('api-conversation-chars').value) === 200000,
    [q('api-message-chars').value, q('api-conversation-chars').value]);
  check('janela mostra o que já foi entregue na sessão',
    q('api-context-status').textContent.includes('meu-gemini')
    && q('api-context-status').textContent.includes('caracteres'),
    q('api-context-status').textContent);

  // Clicar em "Ligar API" leva à aba certa sem enviar nada.
  q('quick-action').click();
  await settle();
  check('botão do fluxo abre a aba API e não envia mensagem',
    !win.document.getElementById('view-api').hidden
    && !requests.some(item => item.url === '/api/task'), requests.map(item => item.url));

  // Conferência de endereço: erro explicado e acerto confirmado.
  q('url-check-input').value = 'http://127.0.0.1:8765';
  q('url-check').click();
  await settle();
  check('endereço incompleto é explicado',
    q('url-check-result').textContent === 'Falta a rota de chat.' && q('url-check-result').dataset.error === 'true',
    q('url-check-result').textContent);
  q('url-check-input').value = 'http://127.0.0.1:8765/v1/chat/completions';
  q('url-check').click();
  await settle();
  check('endereço correto é confirmado',
    q('url-check-result').textContent === 'Endereço completo e correto.'
    && q('url-check-result').dataset.error === 'false', q('url-check-result').textContent);

  // Nome automático: conectar não pede nome nem colide com o já salvo.
  current = state({chats: [{name: 'meu-gemini', compatible: true, conversation: {turns: 0, revision: 0}}]});
  win.__harness.refresh();
  await settle();
  win.document.getElementById('provider').value = 'gemini';
  win.document.getElementById('provider').dispatchEvent(new win.Event('change'));
  check('nome automático evita colisão', q('name').value === 'meu-gemini-2', q('name').value);
  check('nome continua recolhido em Opções', q('name').closest('details') && !q('name').closest('details').open);

  // API ligada: o fluxo não pede mais nada.
  current = state({chats: [{name: 'meu-gemini', compatible: true, conversation: {turns: 0, revision: 0}}],
    api_service: {...state().api_service, enabled: true}});
  win.__harness.refresh();
  await settle();
  check('com a API ligada, o passo é copiar o endereço',
    q('quick-action').textContent === 'Copiar endereço', q('quick-action').textContent);

  // Depuração do Chrome: configurar UMA vez em vez de reabrir chrome://inspect.
  current = state({chats: [{name: 'meu-gemini', provider: 'gemini', browser: 'chrome',
    session_mode: 'existing_chrome', compatible: true, debug_port: 0, auto_launch: false,
    conversation: {turns: 0, revision: 0}}]});
  win.__harness.refresh();
  await settle();
  check('depuração: começa no modo manual', q('debug-badge').textContent === 'Manual'
    && q('debug-port').value === '' && q('debug-install').disabled === false,
    [q('debug-badge').textContent, q('debug-port').value]);
  q('debug-port').value = '9222';
  q('debug-port').dispatchEvent(new win.Event('input'));
  q('debug-auto').checked = true;
  q('debug-install').click();
  await settle();
  const debugRequest = requests.filter(item => item.url === '/api/chrome-debug').at(-1);
  check('configurar uma vez manda porta, atalho e conexão',
    !!debugRequest && debugRequest.body.port === '9222'
    && debugRequest.body.auto_launch === true && debugRequest.body.name === 'meu-gemini'
    && debugRequest.body.install === true, debugRequest && debugRequest.body);
  check('resposta da depuração aparece na tela',
    q('debug-feedback').textContent.includes('porta 9222'),
    q('debug-feedback').textContent);
  // Conexão já configurada: o painel confirma em vez de pedir o passo manual.
  current = state({chats: [{name: 'meu-gemini', provider: 'gemini', browser: 'chrome',
    session_mode: 'existing_chrome', compatible: true, debug_port: 9222, auto_launch: true,
    conversation: {turns: 0, revision: 0}}]});
  win.__harness.refresh();
  await settle();
  check('depuração configurada é mostrada e não pede nada',
    q('debug-badge').textContent === 'Configurada' && q('debug-port').value === '9222'
    && q('debug-auto').checked && q('debug-status').textContent.includes('Sem permissão manual'),
    [q('debug-badge').textContent, q('debug-port').value, q('debug-status').textContent]);
  current = state({chats: [{name: 'outro', provider: 'gemini', browser: 'chromium',
    session_mode: 'dedicated', conversation: {turns: 0, revision: 0}}]});
  win.__harness.refresh();
  await settle();
  check('conexão de perfil separado não oferece depuração do Chrome',
    q('debug-install').disabled && q('debug-status').textContent.includes('perfil separado'),
    [q('debug-install').disabled, q('debug-status').textContent]);

  console.log(failures.length ? '\n' + failures.length + ' falha(s)' : '\ntodas as checagens do painel passaram');
  process.exit(failures.length ? 1 : 0);
}

main().catch(error => { console.error(error); process.exit(1); });
