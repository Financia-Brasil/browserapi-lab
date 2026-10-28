# Dossiê: arquitetura de captura, confirmação e interface do BrowserAPI

**Data:** 2026-10-28 · **Rotas usadas:** busca paralela (4 consultas), leitura direta de
documentação primária (MDN), leitura de PRs/repos open-source, e o **DOM real relatado
pelo usuário** (Arena/LMArena, hoje).
**Pergunta original → operacional.** "A API não funciona, o mapeamento confunde as
mensagens, a janela não abre, a atualização não aplica" →
*qual arquitetura de captura, confirmação e interface adotar para funcionar em chats
arbitrários (Gemini, Arena) com **Playwright + stdlib**, sem seletor por site, sem
falso "envio não confirmado" e sem UI que quebre a página?*

---

## 1. Hipóteses pré-registradas

Congeladas em `pesquisa/2026-10-28-preregistro.md` antes do loop; só a última coluna muda.

| # | Hipótese (afirmativa, testável) | O que a mataria | Fonte-alvo | Kent prévia | Resultado |
|---|---|---|---|---|---|
| H1 | Separar "minha mensagem" de "resposta" **só por estrutura**, sem marcador de papel, com ≥95% de acerto em ≥3 UIs | achado de erro sistemático da heurística estrutural | docs + repos de automação | provável 75±12% | **sobrevive fraca** — estrutura funciona, mas só **ancorada na ordem do DOM**; geometria como filtro duro falha (F6). Não é o melhor caminho: marcador de papel e estado do framework são mais fortes (F7, F10) |
| H2 | Nonce (`request_id`) presente no DOM é confirmação de envio com FP≈0 e FN≈0 | provedor que remove/renderiza o nonce de forma comum | sanitização/markdown dos provedores | quase-certo 93±6% | **confirmada** — nada nos alvos remove texto simples; o próprio usuário viu o JSON com `request_id` na tela (F13). Ganho: elimina a dependência do seletor da pergunta |
| H3 | Fim de streaming = "botão parar ausente" + estabilidade de texto é melhor que tempo fixo | ausência de botão parar em todos os alvos | DOM real | provável 75±12% | **refinada, não morta** — botão parar sozinho é insuficiente: SDKs o escondem **antes** do texto terminar (F4). Correto = parar ausente **E** texto estável por N amostras **E** sem classe de streaming (F3, F5) |
| H4 | Shadow DOM + `position:fixed` + tamanho fixo elimina interceptação e rolagem sem quebrar CSP | CSP `style-src` bloquear estilo inline dentro do shadow root | MDN/CSP | 50±10% | **meio-morta** — `<style>` e `style="…"`/`cssText` **são** bloqueados; atribuir propriedade via CSSOM **não é** (F1). Shadow DOM não é necessário (e quebraria o contrato dos testes): basta DOM normal + CSSOM + `pointer-events` |
| H5 | `MutationObserver`/observers são melhores que polling de 350 ms | observers não dispararem em conteúdo virtualizado | MDN | provável 75±12% | **confirmada** — padrão de dois estágios (F5) e "quiet period" por mutações (F2) |
| H6 | Telemetria agregada persistida sobrevive à atualização sem vazar texto | qualquer caminho em que o arquivo persistido contenha texto | código atual | quase-certo 93±6% | **confirmada** — os campos já são numéricos/enumerados; persistir só eles é seguro |

**Fermi prévio (registrado antes da coleta).** Automação por seletor fixo quebra a cada
~2–8 semanas; por estrutura + nonce, ~1 vez a cada 6 meses. Falsos negativos de
confirmação: ~1 em 20 envios com seletor de papel; <1 em 1 000 com nonce.
**Observado:** o relato de hoje é justamente o caso de 1-em-20 (o seletor da pergunta
não casava com o balão do Arena). Não foi medido em escala — segue como estimativa.

**Baseline da classe.** Todas as ferramentas de exportação/automação de chat
encontradas mantêm lista manual de seletores por site e documentam quebras quando o
site muda (F7, F8, F9). O custo dominante do produto é manutenção de seletor.

---

## 2. Coleta — fichas por sub-pergunta

### Sub-pergunta 2.1 — Como saber qual elemento é "minha mensagem" e qual é "a resposta"?

- **FICHA F7** · 2026 · `github.com/Kohzadi2023/virtual-company-roundtable/pull/28` —
  *"`model-response` (the guessed selector) does match a real element, but its innerText
  includes a visually-hidden 'Gemini said' accessibility label… `<message-content>`…
  holds exactly the markdown answer"*. → O papel vem do **elemento customizado**; o
  ruído vem de rótulo acessível, não do conteúdo. Diagnosticidade: mata "usar innerText
  do balão" e discrimina H1 vs H-framework.
- **FICHA F8** · 2025-10-28 · `forum.obsidian.md/t/…/107355` — *"each user input is in an
  element called `user-query` and Gemini answers are in an element called
  `model-response` (and inside it, another element `message-content` contains the answer,
  undecorated)"*. → Confirma F7 em fonte independente.
- **FICHA F9** · 2026-02-16 · `github.com/arush361/gemini-chat-exporter` — *"Each
  conversation turn is a `.conversation-container` containing two MORE custom elements:
  `<user-query>` and `<model-response>`… Screen reader text pollutes exports — always
  filter out `.screen-reader-only` elements"* + *"Virtual/infinite scrolling is
  adversarial to scrapers"*.
- **FICHA F13** · 2026-10-28 · DOM colado pelo usuário (Arena/LMArena) —
  `ol[data-perf-target="transcript"]`; cartão da resposta `div.bg-surface-primary` com
  `h2` "Message from \<modelo\>"; turno do usuário `div.justify-end` contendo
  `div.bg-surface-raised`; **nenhum** `data-role`/`data-message-author-role`.
  → No Arena o papel **não** está em atributo; está na estrutura/classe utilitária.
- **FICHA F10** · 2026 · `github.com/dexforint/arena-utils` — *"Markdown is taken from
  React props when possible, with a DOM fallback"* e os turnos numerados "1.md, 3.md,
  5.md, … user messages / 2.md, 4.md, 6.md, … model replies".
- **FICHA F11** · 2026 · `github.com/janhalendk/react` — *"`__reactFiber$` and
  `__reactProps$`… followed by the same 10 character long string"*, com `memoizedProps`
  e `stateNode`; receita para achar a chave varrendo `Object.keys(el)`.
- **FICHA F12** · 2026-02-08 · `reddit.com/r/lmarena/…/1qzhsd4` — Arena é *"React /
  TailwindCSS / Vaul etc. SPA"*: o HTML anônimo não traz a conversa.
- **FICHA F6** · 2026 · `github.com/Fiandriananaprime/nova_ai/pull/11` — *"The response
  reader used viewport geometry as a hard filter… Prefer DOM order after the exact
  outgoing message anchor. Use geometry only when DOM order does not establish that a
  candidate follows the anchor."*

**Diagnosticidade.** F6 mata a variante "geometria" de H1. F7/F8/F9 mostram que **onde
existe marcador de papel, ele é o caminho certo**. F13 mata a ideia de que todo site
marca papel em atributo. F10/F11 abrem a rota que nenhuma das hipóteses previa: ler o
**modelo de dados do app**.

### Sub-pergunta 2.2 — Como confirmar que a mensagem foi enviada?

- **FICHA F6** (acima) — ancorar no "outgoing message", não em contagem global.
- **FICHA F13** — o JSON com `request_id` foi renderizado como `<p>` normal, texto puro,
  sem alteração. Nonce sobrevive ao render.
- **FICHA F3** · 2026-06-10 · `dev.to/…/pitfalls-of-testing-llm-long-term-memory…` —
  *"if the stop button is still visible, generation is ongoing… 3 consecutive identical
  samples -> done"*.
- **INFERÊNCIA (mostrar o cálculo).** Se o nonce é texto puro no `<p>` (F13) e o balão é
  o ancestral mais próximo com papel (F7), então `conversation.find(t => t.text.includes(nonce))`
  dá a confirmação **sem depender de seletor de papel**: o nonce só aparece se o envio
  ocorreu. FP exigiria o nonce aparecer sem envio — só aconteceria se o rascunho ficasse
  no campo e o campo fosse lido como mensagem (evitado por F6: turnos do transcript, não
  do composer).

### Sub-pergunta 2.3 — Como saber que a resposta terminou?

- **FICHA F2** · 2026-04-24 · `assrt.ai/t/playwright-auto-retry-assertions` — o "quarto
  primitivo": *"wait_for_stable… a quiet period (e.g. 2s of zero DOM mutations)"* e
  *"networkidle never fires"* com heartbeat SSE; *"You do not know when it stops
  streaming, because the locator only exists once the bubble is appended"*.
- **FICHA F4** · 2026 · `github.com/GetStream/stream-chat-flutter-ai/pull/14` — *"Every SDK
  hides the composer's stop button when the backend finishes, so it disappears while the
  reply is still being revealed."* → **mata H3 na forma "só botão parar"**.
- **FICHA F5** · 2024-08-13 · `fogel.dev/detecting_llm_streaming_completion` — dois
  estágios: observer global para nós novos + observer por nó (`WeakMap`), cuidando de
  duplicidade e de não `disconnect()` geral.

### Sub-pergunta 2.4 — Como injetar interface sem quebrar a página?

- **FICHA F1** · MDN, acesso 2026-10-28 —
  `developer.mozilla.org/…/Content-Security-Policy/style-src`:
  *"Inline style attributes are also blocked… As well as styles that are applied in
  JavaScript by setting the `style` attribute directly, or by setting `cssText`"* e
  *"However, styles properties that are set directly on the element's `style` property
  will not be blocked"*. Também: *"no browser currently blocks these methods"* (CSSOM).
  → Permite manter DOM normal (sem shadow) e estilizar por propriedade. **Proíbe**
  `style.cssText` e `setAttribute('style', …)` — que é o que o painel de seleção usava em
  pelo menos um ponto (`Object.assign(el.style, …)` é seguro; `cssText` não).
- **FICHA F5** — observer por nó também serve para a UI não re-renderizar em laço.

### Sub-pergunta 2.5 — Atualização automática e dados sobrevivendo à atualização

- **FICHA F14** · código atual `updates.py` — `Updater.__init__(interval=21600)`: depois
  de uma falha, a próxima tentativa é 6 h depois; o `/api/updates` (clique na caixinha)
  é o único `wake`. → Explica "só atualiza quando marco/desmarco".
- **FICHA F15** · código atual `telemetry.py` — `deque(maxlen=limit)` em memória, por
  desenho; reinício (e portanto atualização) zera. `TIMING_KEYS` já é lista fechada de
  números → persistir é seguro (sustenta H6).

---

## 3. ACH — evidência × hipóteses

| Evidência | H1 (só estrutura) | H2 (nonce) | H3 (parar+estável) | H4 (shadow) | H5 (observers) | H6 (telemetria) |
|---|---|---|---|---|---|---|
| F6 geometria falha | ⊖ (mata a variante) | — | — | — | — | — |
| F13 Arena sem `data-role` | ⊕ (estrutura é o que sobra) | ⊕ | — | — | — | — |
| F7/F8/F9 marcadores Gemini | ⊖ (existem melhores) | ⊕ | — | — | — | — |
| F10/F11 estado do React | ⊖⊖ (mata como **primária**) | ⊕ | — | — | — | — |
| F1 CSP/CSSOM | — | — | — | ⊖ (shadow desnecessário) | — | — |
| F2/F5 quiet period | — | — | ⊕ | — | ⊕ | — |
| F4 parar some antes | — | — | ⊖ (mata a forma simples) | — | — | — |
| F3 amostras idênticas | — | ⊕ | ⊕ | — | — | — |
| F14/F15 código | — | — | — | — | — | ⊕ |

**Eliminadas.** (a) "geometria como filtro" — F6. (b) "shadow DOM obrigatório" — F1
(CSSOM resolve e shadow quebraria os seletores de teste). (c) "só botão parar" — F4.
(d) "estrutura como mecanismo **primário**" — F10/F11: em app React o estado é melhor.

**Sobrevive.** Arquitetura em **camadas, da mais forte para a mais fraca**:
1. **marcador de papel** (`user-query`/`model-response`/`data-*-role`) — F7/F8/F9;
2. **estado do framework** (`__reactProps$`/`__reactFiber$` → `memoizedProps`, procurando
   `role`/`author`/`id`) — F10/F11/F12;
3. **estrutura ancorada** (transcript container + ordem do DOM + alinhamento como
   desempate) — F6/F13;
e **confirmação por nonce** (F13) com fallback para contagem ancorada (F6).

---

## 4. Premortem do julgamento-chave

Julgamento: *"ler da camada mais forte disponível, ancorado na ordem do DOM, com nonce
para confirmar, é robusto o bastante para ser a base do produto."* Suponha que daqui a um
ano isso fracassou:

1. **Build de produção minifica `memoizedProps`** (chaves `a`, `b`, `c`) e o leitor cai
   sempre na camada 1/3 sem ninguém notar. → **Risco:** degradação silenciosa.
   **Indicador datável:** proporção de leituras resolvidas pela camada 2 (alvo: >0 em
   site React; se 0 por 30 dias, a rota morreu).
2. **O site passa a renderizar a conversa em `<iframe>`/shadow fechado.** → ninguém acha
   turnos. **Indicador:** `conversation()` vazio com página visivelmente cheia; alarme no
   recibo ("não encontrei a conversa"), nunca "envio não confirmado".
3. **O nonce é reformatado** (markdown quebra o identificador em nós com `\u200b`, ou o
   site escapa). → confirmação cai para contagem. **Indicador:** recibo de envio deixa de
   citar "nonce" e passa a "contagem ancorada"; se isso virar padrão em 20 envios, a
   hipótese caiu.

**Linchpin (premissa que sustenta tudo):** *a ordem do DOM dentro do container do
transcript é a ordem cronológica*. Se um dia a lista for virtualizada com prepend
(F9 diz que prepend existe), a contagem desloca sem mensagem nova. **Indicador:** baseline
muda entre leituras sem envio → usar nonce e nunca contagem absoluta.

---

## 5. Resumo executivo (Kent prévia → final)

- **A captura deve ser em camadas, não em seletor por site.** Marcador de papel quando
  existe (Gemini); estado do framework quando existe (Arena é React); estrutura ancorada
  como último recurso. *Kent: provável 75±12% → quase-certo 93±6%.*
- **Confirmação de envio por nonce visível** (o `request_id` que já vai no prompt) é
  superior a contar balões: não depende de seletor de papel. *93±6% → quase-certo.*
- **Fim de resposta** = parar ausente **e** texto estável por N amostras **e** sem classe
  de streaming; observers em vez de polling. Botão parar sozinho não basta (F4).
  *75±12% → provável 75±12% (confirmado com ressalva).*
- **UI do apontamento**: DOM normal, CSSOM por propriedade (CSP-safe), tamanho fixo,
  arrastável, `pointer-events` isolado. Shadow DOM é opcional e não vale o custo.
  *50±10% → provável 75±12%.*
- **Atualização**: backoff curto + verificação manual + aplicação quando ocioso; e
  telemetria agregada persistida para não zerar a cada atualização.

## 6. Surpresa & implicação

- **Esperava:** H1 (estrutura) como base; *provável*, 75±12%, pré-registrado.
- **Veio:** FICHA F10 · `github.com/dexforint/arena-utils` — *"Markdown is taken from
  React props when possible, with a DOM fallback."* Um exportador do **mesmo site** que
  falhou para nós resolve o problema lendo o estado do React, não o DOM. Somado a F11
  (como achar `__reactProps$`) e F12 (Arena é SPA React), a rota existe e é pública.
- **Divergência:** não é fator n×, é **inversão de pilar**: a fonte de verdade deixa de
  ser "adivinhar o DOM" e passa a ser "ler o que o app sabe" — com o DOM como plano B.
- **Implicação:** sem isso, cada redesign do Arena quebra o mapeamento (foi o que
  aconteceu hoje e na 0.9.0). Com isso, o mapeamento manual passa a ser **confirmação**,
  não descoberta — e o teste de compatibilidade deixa de depender do seletor da pergunta.
- **Premortem:** se a camada 2 morrer (minificação), o leitor cai para 1/3 →
  indicador: contagem de leituras por camada no recibo; verificar em 2026-11-30.
- **Confiança final (Kent):** quase-certo 93±6% de que a arquitetura em camadas + nonce é
  melhor que seletor por site; fontes independentes: 3 (Gemini×3, React×3, Playwright×3).

## 7. Alternativas descartadas

| Alternativa | Por que não |
|---|---|
| Lista de seletores por site (o que existe hoje) | quebra a cada redesign; foi a causa dos dois últimos incidentes (F7/F9/código) |
| Só geometria/alinhamento | F6: falha sistematicamente quando o layout discorda da ordem |
| Shadow DOM fechado para a UI | F1: CSSOM já resolve CSP; e quebraria locators dos testes |
| Esperar `networkidle` | F2: SSE/heartbeat nunca ficam idle |
| Tempo fixo para "resposta pronta" | F3/F5: resposta longa estoura, curta espera demais |
| Injetar SDK/JS do site ou recipe de API interna | ADR-008 (só Playwright + stdlib) e risco de quebrar termo de uso; ler props já presentes é leitura, não nova integração |

## 8. Lacunas & incertezas

- **Arena**: só temos o DOM colado pelo usuário (F13); não abrimos a página autenticada.
  A leitura por `__reactProps$` no Arena **não foi verificada ao vivo** — é inferência a
  partir de F10/F11/F12. Precisa de teste no app real do usuário.
- **Gemini**: F7 é teste ao vivo em conta **visitante** (o próprio autor declara que a
  resposta real não foi verificada). Nós também não autenticamos.
- A taxa "quebra a cada 2–8 semanas" é estimativa de classe, não medição.
- Não medimos custo de `MutationObserver` em conversas de 1 000+ turnos.

## 9. Fontes (URL · data · o que sustenta)

1. MDN, *Content-Security-Policy: style-src* — acesso 2026-10-28 — CSSOM não é bloqueado;
   `style attr`/`cssText`/`<style>` são. (F1)
2. assrt.ai, *Playwright auto-retry assertions + waitForStable* — 2026-04-24 — quiet
   period por mutações; `networkidle` não serve com SSE. (F2)
3. dev.to, *Pitfalls of Testing LLM Long-Term Memory* — 2026-06-10 — botão parar +
   3 amostras idênticas. (F3)
4. GitHub, *GetStream/stream-chat-flutter-ai PR #14* — 2026 — parar some antes do texto
   terminar. (F4)
5. fogel.dev, *Detecting LLM streaming completion* — 2024-08-13 — observer em dois
   estágios, `WeakMap`, sem `disconnect` global. (F5)
6. GitHub, *Fiandriananaprime/nova_ai PR #11* — 2026 — ordem do DOM > geometria,
   ancorada na mensagem enviada. (F6)
7. GitHub, *Kohzadi2023/virtual-company-roundtable PR #28* — 2026 — `message-content`
   vs rótulo `cdk-visually-hidden` no Gemini. (F7)
8. Obsidian Forum, *Processing lists… (clip Gemini chats)* — 2025-10-28 — `user-query` +
   `model-response message-content`. (F8)
9. GitHub, *arush361/gemini-chat-exporter* — 2026-02-16 — custom elements, prepend,
   `.screen-reader-only`. (F9)
10. GitHub, *dexforint/arena-utils* — 2026 — "React props when possible, DOM fallback". (F10)
11. GitHub, *janhalendk/react* — 2026 — `__reactFiber$`/`__reactProps$`, `memoizedProps`. (F11)
12. Reddit r/lmarena — 2026-02-08 — Arena é SPA React/Tailwind. (F12)
13. Relato do usuário (DOM colado) — 2026-10-28 — estrutura real do Arena. (F13)
14. Código do próprio repositório, `updates.py` — acesso 2026-10-28 — intervalo 6 h e
    `wake` só no clique. (F14)
15. Código do próprio repositório, `telemetry.py` — acesso 2026-10-28 — histórico em
    memória. (F15)
