import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM} from 'jsdom';
const script=readFileSync(new URL('../app/src/main/assets/capture.js',import.meta.url),'utf8');
function page(html){
  const dom=new JSDOM('<body>'+html+'</body>',{url:'https://example.com/private?cpf=12345678901#secret',runScripts:'outside-only'});
  dom.window.HTMLElement.prototype.getClientRects=function(){return [this.getBoundingClientRect()];};
  const capture=()=>dom.window.eval(script);
  return {dom,capture};
}
const values=[
  ['text','12345678901'],['password','a_secret_password_42'],['email','maria@example.com'],['tel','+55 91 99999-0000'],
  ['text','123.456.789-01'],['text','12345 00001 54321'],['search','private_search_terms'],['number','987654321'],
  ['text','66000-000'],['date','2026-11-14'],['url','https://private.example/token'],['text','otpauth-secret-123']
];
for(const [type,secret] of values)test('não captura valor de '+type+' '+values.indexOf(values.find(x=>x[1]===secret)),()=>{
  const {dom,capture}=page('<label for="field">Campo</label><input id="field" type="'+type+'">');
  dom.window.document.querySelector('input').value=secret;
  const result=JSON.stringify(capture());
  assert.ok(!result.includes(secret),result); assert.ok(!result.includes('private?')); assert.ok(!result.includes('cpf='));
  dom.window.close();
});
test('textarea e seleção não expõem valores',()=>{
 const {dom,capture}=page('<label for="a">Mensagem</label><textarea id="a">private_text_secret</textarea><select><option value="private_option_secret" selected>private_option_secret</option></select>');
 const result=JSON.stringify(capture()); assert.ok(!result.includes('private_text_secret')); assert.ok(!result.includes('private_option_secret')); dom.window.close();
});
test('CPF, email e telefone em label são saneados',()=>{
 const {dom,capture}=page('<button>Conta ana@example.com 123.456.789-01 +55 (91) 99999-1234</button>');
 const result=JSON.stringify(capture()); for(const secret of ['ana@example.com','123.456.789-01','99999-1234'])assert.ok(!result.includes(secret)); dom.window.close();
});
test('conteúdo editável dentro de botão não sai',()=>{
 const {dom,capture}=page('<button>Salvar <span contenteditable="true">super_secret_user_text</span></button>');
 assert.ok(!JSON.stringify(capture()).includes('super_secret_user_text')); dom.window.close();
});
test('campos hidden, invisíveis e desabilitados são ignorados',()=>{
 const {dom,capture}=page('<input type="hidden" value="secret"><input hidden><input style="display:none"><div aria-hidden="true"><input></div><input disabled><input type="password" aria-label="Senha">');
 assert.equal(capture().nodes.length,1); dom.window.close();
});
test('captura mostra somente se o campo foi preenchido',()=>{
 const {dom,capture}=page('<label for="a">CPF</label><input id="a">');
 let out=capture();assert.equal(out.nodes[0].filled,false);
 const field=dom.window.document.querySelector('input');field.value='12345678901';
 field.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
 out=capture();assert.equal(out.nodes[0].filled,true);assert.equal(out.nodes[0].label,'CPF');dom.window.close();
});
test('retorna null sem mudança e limita 120 alvos',()=>{
 const {dom,capture}=page('<button>Olá</button>'.repeat(150));assert.equal(capture().nodes.length,120);assert.equal(capture(),null);dom.window.close();
});
test('destaque não clica nem modifica valor',()=>{
 const {dom,capture}=page('<input value="secret"><button>Enviar</button>');
 let clicks=0;dom.window.document.querySelector('button').onclick=()=>clicks++;
 capture();dom.window.__farol.mark(1);assert.equal(clicks,0);assert.equal(dom.window.document.querySelector('input').value,'secret');
 assert.equal(dom.window.__farol.overlay.style.pointerEvents,'none');dom.window.__farol.mark(-1);assert.equal(dom.window.__farol.overlay.hidden,true);dom.window.close();
});
test('erros recebem saneamento',()=>{
 const {dom,capture}=page('<div role="alert">Email ana@example.com inválido</div>');
 assert.equal(capture().errors[0],'Email [texto] inválido');dom.window.close();
});
test('marcador oculto de conclusão não conclui o fluxo',()=>{
 const {dom,capture}=page('<section hidden data-farol-complete="true">Fim</section>');
 assert.equal(capture().complete,false);dom.window.close();
});
test('simulação não usa rede nem guarda valores',()=>{
 const html=readFileSync(new URL('../app/src/main/assets/practice.html',import.meta.url),'utf8');
 assert.ok(html.includes("connect-src 'none'"));assert.ok(!html.includes('fetch('));assert.ok(!html.includes('XMLHttpRequest'));
 assert.ok(html.includes("localStorage.setItem('farol-practice-state',name)"));
});
