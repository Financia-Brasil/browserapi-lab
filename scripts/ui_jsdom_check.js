/* Checagem de interface e leitura sem navegador (jsdom).
 *
 * Por que existe: o ambiente de desenvolvimento não tem Chromium. Estes dois
 * harnesses exercitam o que é puro DOM — o leitor de camadas (capture.py) e o
 * painel do apontamento (picker.js) — antes de depender do CI com navegador.
 *
 * Uso:
 *   npm install jsdom          # uma vez, fora do repositório
 *   node scripts/ui_jsdom_check.js /caminho/do/repositorio
 *
 * Isto NÃO substitui os testes de navegador: jsdom não tem layout real.
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

/* jsdom não calcula layout: uma caixa plausível deixa as camadas de geometria
 * exercitáveis sem esconder regressão de lógica. */
function boxFor(win) {
  win.Element.prototype.getBoundingClientRect = function () {
    const text = (this.textContent || '').length;
    const height = this.matches('body,html,main,section,div,ol,ul')
      ? 200 : Math.max(20, Math.min(120, text / 4));
    return { width: 400, height, top: 0, left: 0, right: 400, bottom: height, x: 0, y: 0 };
  };
}

function load(fixture) {
  const html = fs.readFileSync(path.join(repo, 'fixtures', fixture), 'utf8');
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true });
  boxFor(dom.window);
  return dom.window;
}

const source = fs.readFileSync(path.join(repo, 'browserapi_lab/capture.py'), 'utf8');
const start = source.indexOf('CAPTURE_SCRIPT = r"""') + 'CAPTURE_SCRIPT = r"""'.length;
const captureScript = source.slice(start, source.indexOf('"""', start));

function read(win, user, assistant) {
  return win.eval('(' + captureScript + ')')({ user: user || '', assistant: assistant || '' });
}

console.log('— leitura da conversa (capture.py) —');

// ---------------- gemini_like ----------------
{
  const win = load('gemini_like.html');
  const out = read(win, 'user-query', 'model-response');
  check('gemini: camada por papel declarado', out.layered.layer === 'marker', out.layered.layer);
  check('gemini: 1 pergunta e 1 resposta',
    out.layered.counts.user === 1 && out.layered.counts.assistant === 1, out.layered.counts);
  check('gemini: leitura apontada limpa',
    out.configured.overlap === 0 && out.configured.items.length === 2, out.configured);
  check('gemini: resposta sem barra de ações',
    !out.layered.items.some(item => item.text.includes('Copiar')));

  // Fragmento apontado (o defeito relatado): sobe ao balão inteiro.
  const fragment = read(win, 'user-query', 'p.first-token');
  const answer = fragment.configured.items.find(item => item.role === 'assistant');
  check('gemini: pedaço apontado vira balão inteiro',
    !!answer && answer.text.includes('Belém') && answer.text.includes('Fica na região Norte'),
    answer && answer.text);
  check('gemini: balão inteiro não duplica a pergunta',
    fragment.configured.items.filter(item => item.role === 'assistant').length === 1,
    fragment.configured.items.length);

  const mixed = read(win, 'user-query', 'user-query, model-response');
  check('gemini: seletor misturado é detectado',
    mixed.configured.overlap > 0 || mixed.configured.items.length > 2, mixed.configured);

  const api = win.__balCapture;
  const before = api.userState('user-query');
  const conversation = win.document.querySelector('.conversation-container');
  const turn = win.document.createElement('div');
  turn.className = 'conversation-turn';
  turn.innerHTML = '<user-query><div class="user-query-container">'
    + '<p class="query-text">pergunta nova</p></div></user-query>';
  conversation.appendChild(turn);
  // O leitor guarda o estado por 250 ms para não varrer o DOM a cada 50 ms
  // durante a confirmação; aqui esperamos a janela passar.
  const until = Date.now() + 300;
  while (Date.now() < until) { /* espera curta e determinística */ }
  const after = api.userState('user-query');
  check('gemini: estado do usuário cresce após o envio', after.count === before.count + 1, [before, after]);
  check('gemini: último texto é o enviado', after.last === 'pergunta nova', after.last);

  const last = api.last('assistant', 'model-response');
  check('gemini: última resposta legível', !!last && last.text.includes('Belém'), last && last.text);
}

// ---------------- página sem conversa parecida: não inventar turnos ----------------
{
  const win = load('fake_chat.html');
  // Um balão só + barra lateral cheia de <label>: antes, os rótulos uniformes
  // da lateral eram lidos como "turnos" e a última resposta saía da barra.
  const lonely = read(win, '', '');
  check('fake: página com um balão só não inventa conversa',
    lonely.layered.layer === 'none' && lonely.layered.items.length === 0, lonely.layered);
}

// ---------------- fake_chat: papéis por atributo, seletores num pedaço ----------------
{
  const win = load('fake_chat.html');
  win.eval(`(function(){
    const conv = document.querySelector('#conversation');
    const first = document.createElement('div');
    first.className = 'message';
    first.setAttribute('data-role', 'user');
    first.innerHTML = '<div class="role">Você</div><div class="body"><p>pergunta do teste</p></div>';
    conv.insertBefore(first, conv.firstChild);
  })()`);
  const out = read(win, '[data-role="user"] .body', '[data-role="assistant"] .body');
  check('fake: camada por papel declarado', out.layered.layer === 'marker', out.layered.layer);
  check('fake: papéis alternados',
    out.layered.items.length === 2 && out.layered.items[0].role === 'user', out.layered.items);
  const configured = out.configured.items;
  check('fake: leitura apontada sobe ao balão (sem duplicar pedaço)',
    configured.length === 2 && configured.every(item => item.text.length > 10), configured);
}

// ---------------- estrutura: conversa sem marcador nenhum ----------------
{
  const html = `<!DOCTYPE html><html><body>
    <main><ol id="transcript">
      <li><div class="justify-end"><p>pergunta um</p></div></li>
      <li><div><p>resposta um</p></div></li>
      <li><div class="justify-end"><p>pergunta dois</p></div></li>
      <li><div><p>resposta dois</p></div></li>
    </ol>
    <form><textarea></textarea><button type="submit">Enviar</button></form></main>
  </body></html>`;
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true });
  const win = dom.window;
  win.Element.prototype.getBoundingClientRect = function () {
    return { width: 400, height: 40, top: 0, left: 0, right: 400, bottom: 40, x: 0, y: 0 };
  };
  const out = read(win, '', '');
  check('estrutura: reconhece ordem com papéis alternados', out.layered.layer === 'structure', out.layered.layer);
  check('estrutura: 2x2 turnos',
    out.layered.counts.user === 2 && out.layered.counts.assistant === 2, out.layered.counts);
  check('estrutura: primeira pergunta é do usuário',
    out.layered.items[0] && out.layered.items[0].role === 'user'
    && out.layered.items[0].text === 'pergunta um', out.layered.items);
}

console.log('— painel do apontamento (picker.js) —');

{
  const pickerScript = fs.readFileSync(path.join(repo, 'browserapi_lab/assets/picker.js'), 'utf8');
  const win = load('gemini_like.html');
  win.eval(pickerScript)({ role: 'resposta do assistente', step: '5 de 5', hint: 'Clique no balão.' });

  const banner = win.document.querySelector('#__browserapi_picker');
  check('painel abre', !!banner);
  check('sem barra de rolagem', win.getComputedStyle(banner).overflow === 'hidden',
    win.getComputedStyle(banner).overflow);
  check('largura fixa', banner.style.width === '392px', banner.style.width);
  const grip = win.document.querySelector('[data-picker-grip]');
  check('alça de arraste existe e é a única parte arrastável',
    !!grip && win.getComputedStyle(grip).cursor === 'move'
    && win.getComputedStyle(banner.firstChild).pointerEvents === 'none',
    grip && [win.getComputedStyle(grip).cursor, win.getComputedStyle(banner.firstChild).pointerEvents]);
  check('título não intercepta o clique', win.getComputedStyle(banner.querySelector('strong')).pointerEvents !== 'auto',
    win.getComputedStyle(banner.querySelector('strong')).pointerEvents);
  check('painel não rouba o clique da página', banner.style.pointerEvents === 'none',
    banner.style.pointerEvents);
  check('controles continuam clicáveis',
    win.document.querySelector('[data-picker-confirm]').style.pointerEvents === 'auto',
    win.document.querySelector('[data-picker-confirm]').style.pointerEvents);

  const target = win.document.querySelector('model-response .markdown p');
  target.dispatchEvent(new win.MouseEvent('click', { bubbles: true, cancelable: true }));
  const text = banner.textContent;
  check('mostra que vai capturar o balão',
    text.includes('Belém') && text.includes('capital do Pará'), text.slice(0, 160));
  check('lista curta (até 3 linhas)', (text.match(/\n/g) || []).length <= 6, text);

  // Site que re-renderiza o body apaga nós injetados. O painel precisa voltar
  // sozinho — sem isso, o mapeamento morre com "o painel não abriu".
  banner.remove();
  win.dispatchEvent(new win.Event('scroll'));
  check('painel volta depois de re-render do site',
    !!win.document.querySelector('#__browserapi_picker'));

  win.document.querySelector('[data-picker-confirm]').click();
  check('confirma o seletor do balão', win.__balPick && win.__balPick.selector === 'model-response',
    win.__balPick);
  check('painel sai da página depois de confirmar',
    !win.document.querySelector('#__browserapi_picker'));
}

console.log(failures.length ? '\n' + failures.length + ' falha(s)' : '\ntodas as checagens passaram');
process.exit(failures.length ? 1 : 0);
