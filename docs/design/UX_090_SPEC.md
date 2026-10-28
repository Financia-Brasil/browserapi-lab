# 0.9 — mapeamento guiado que não perde o usuário nem o texto

Relato do usuário que originou este marco (resumo fiel):

1. “O Gemini separou em 2 tags a resposta
   `<p data-path-to-node="0" class="first-token"><span>Olá!</span><span> Como posso
   ajudar você hoje?</span></p>`” — a resposta capturada vinha cortada.
2. “Bug ao selecionar Sim na primeira pergunta sobre o microfone: ele já vai pro
   campo de mensagem, aí é cancelar e responder de novo.”
3. “Ele identifica um monte de botão ao ter que selecionar um texto e não
   identifica os próprios textos.”
4. “Não há instruções bem trabalhadas no processo de mapeamento; UI confusa e
   desconexa.”

## 1. A resposta partida em vários elementos

**Causa.** O apontamento guardava o **elemento clicado**. Um `<span>` (ou o
`<p class="first-token">` do primeiro token) casa com *um pedaço* da resposta; o
programa então lia só aquele pedaço, e o seletor `p.first-token` ainda repetia esse
recorte em todas as respostas. Nada indicava o erro: a resposta exibida parecia
legítima.

**O que mudou**

| Antes | Agora |
|---|---|
| seletor = o elemento clicado | seletor = **balão da mensagem** (`model-response`, `user-query`, `[data-role=…]`) |
| sem prévia | faixa mostra **“Vai capturar: …”** com o texto real antes de confirmar |
| captura = `inner_html` do nó | captura = **balão inteiro**, com a barra de ações e rótulos de papel removidos |
| configuração antiga continuava cortando | o runtime sobe ao balão mesmo com seletor antigo apontado num pedaço |
| contava balão + pedaço como duas respostas | ignora nó aninhado dentro de outro casado pelo mesmo seletor |

**Limite explícito:** a subida ao balão usa marcadores de papel (`user-query`,
`model-response`, `data-message-author-role`, `data-role=user|assistant`) e, na
falta deles, heurística de classe/camada. Não é uma promessa sobre qualquer site;
continua exigindo a checagem com uma mensagem autorizada. Em iframes, o balão
inteiro não é expandido (o probe só existe no frame principal) — a leitura fica no
elemento casado.

## 2. “Sim” no microfone jogava para o campo de mensagem

**Causa.** O fluxo perguntava o microfone **antes** do campo Enviar e sem
numeração; responder “Sim” levava ao passo seguinte (digitar no campo) e não havia
volta — só cancelar tudo e começar de novo.

**O que mudou**

- Cada pergunta começa com `Passo N de M · Título — …`; o painel desenha o passo,
  os pontos de progresso e a dica do elemento.
- O microfone continua antes do Enviar (é preciso saber qual botão ignorar), mas a
  pergunta agora explica as duas respostas e aceita **Não** sem drama.
- `Esc` e **Pular este campo** pulam **só** o passo atual; **Cancelar mapeamento**
  é o único que encerra tudo (e diz isso no botão).
- No fim, cada campo capturado pode ser refeito, um Sim/Não por campo.

## 3. Botões destacados no lugar dos textos

**Causa.** Para papéis de mensagem a lista de candidatos incluía `p`, `div`,
`article` e o normalizador podia cair no elemento clicado; a página tem dezenas de
botões, e as caixas destacadas se sobrepunham.

**O que mudou**

- Ao apontar texto, os alvos são **balões** (marcadores de papel) — nunca botões.
  Sem marcadores, usa blocos de texto e mantém só a camada mais externa de cada
  grupo, um quadro por mensagem.
- Clicar num botão durante o apontamento de texto é recusado com aviso; não vira
  seleção.
- Cada área destacada tem rótulo com o começo do texto, e a faixa diz quando o
  seletor casa com mais de uma mensagem (o esperado para “todas as respostas”).

## 4. Instruções e continuidade

- Título do passo, dica de onde clicar e o que **não** é o alvo (“não o campo de
  digitar”, “não é a conversa”).
- Resumo ao final (“Mapeamento concluído: campo de digitação, …”) e lista dos
  campos pulados.
- O log continua recolhido em “Detalhes da operação”; nada de parede de texto na
  tela principal.

## O que **não** mudou (de propósito)

- Nada de reenvio automático, login, CAPTCHA ou contorno de proteção.
- O apontamento não digita, não envia e não altera controles do site.
- Escolher “Sim” para o microfone não promete que existe microfone: se você pular,
  o programa avisa que o botão de voz pode ser confundido com Enviar.
- Implementado ≠ testado em CI ≠ homologado no seu Gemini/Arena.

## Testes deste marco

- `tests/test_mapping_browser.py` (8): DOM no estilo Gemini com a resposta em dois
  `<span>` — clicar no pedaço seleciona `model-response`, a prévia mostra o texto
  inteiro, a captura inclui o segundo parágrafo e o balão inteiro; contraprova com
  seletor antigo (`p.first-token`) provando que o runtime não corta a resposta;
  candidatos não incluem botões da página; Esc pula, cancelar aborta; passos
  numerados; pular não cancela os outros; refazer sem reiniciar.
- `fixtures/gemini_like.html`: fixture do DOM relatado (custom elements, barra de
  ações com quatro botões, seis botões na página).
- `tests/test_gui.py`: contrato do painel (passo, pontos de progresso).
