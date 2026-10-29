# Janelas do navegador: prompt grande, blocos, saída em blocos e retomada

Documento de pré-registro e de decisão da **0.13.0**. Ele existe porque o pedido
foi *“system prompts gigantes iniciais de CLIs, arquivos gigantes que excedem o
limite de caracteres no campo de prompt, reverter contexto, prompts em bloco,
saídas em bloco, manutenção e restauração de contexto — pesquise sobre esse e
mais limites”*. Aqui ficam as medidas, as hipóteses (antes do código), a decisão
e o que continua **não** sendo prometido.

## 1. O que foi medido, não suposto

Rodamos o **Claude Code de verdade** (v2.1.312, `npm i @anthropic-ai/claude-code`)
contra um servidor de captura local que fala o dialeto Anthropic. Um pedido
trivial — `claude -p "responda apenas OK"` — manda:

| Componente | Tamanho |
|---|---|
| corpo da requisição | **46.125 bytes** |
| `system` (3 blocos de texto) | 5.985 caracteres |
| `tools` (12 ferramentas) | 29.995 caracteres |
| `messages` (2 itens) | 665 + **9.258** caracteres |
| papéis em `messages` | `[user, system]` — o último é um lembrete de sistema |
| `max_tokens` | 128.000 |
| chaves extras | `context_management`, `output_config`, `thinking`, `metadata.user_id` |
| cabeçalhos | `anthropic-version: 2023-06-01`, `anthropic-beta: claude-code-20250219,interleaved-thinking-2025-05-14,context-management-2025-06-27,mid-conversation-tool-changes-2026-07-01,thinking-token-count-2026-05-13,advanced-tool-use-2025-11-20,effort-2025-11-24` |

Ou seja: **~46 mil caracteres antes de qualquer conversa** — mais do que qualquer
campo de mensagem de chat aceita. E `output_config` **não estava** na lista de
parâmetros aceitos: o primeiro pedido real de uma CLI teria morrido em 400.

Comportamento do CLI diante de erro (medido, mesmo servidor de captura):

| Resposta do servidor | O que o Claude Code faz |
|---|---|
| 400 `prompt is too long: N tokens > M maximum` (1º turno) | **1 requisição**, `terminal_reason: prompt_too_long`, sai com erro — **não** tenta fatiar (a mensagem dele sugere “reduza arquivos/ferramentas”, porque “uma conversa de um turno não pode ser compactada”) |
| 400 de parâmetro (`max_tokens: … > …`) | **6 requisições**, corpo cresce de 46k para 74k, depois desiste |
| 400 `Parâmetro não suportado: …` (nosso erro antigo) | **2 requisições** e desiste com “API Error” |
| 500 | **9 requisições** com espera; o processo fica pendurado (>120 s) |
| 429 / 529 | 9 requisições (429, pendura) / **3** requisições (529, mensagem clara) |
| SSE cortado sem `message_stop` | 3 requisições: tenta de novo **sem streaming** e reporta o corte |
| `stop_reason: max_tokens` | o CLI **continua sozinho** por 4 turnos e então falha (“exceeded the output maximum”) |
| 200 com SSE completo | funciona; `tool_use` → executa Bash → 2º pedido com `tool_result` → resposta final |

Duas conclusões que mudam o desenho:

1. **não dá para empurrar o problema para o CLI**: no primeiro turno ele não
   compacta nem fatia — ele para. Quem precisa fatiar é esta API;
2. **4xx é terminal** (exceto 429): devolver 409 para “o navegador não estava
   pronto” faz o agente parar e dizer que não funciona. É exatamente o relato.

Limites do outro lado (pesquisa, fontes ao final):

| Onde | Limite observado |
|---|---|
| campo de mensagem do Gemini web | ~30.000 caracteres por envio |
| campo de mensagem do ChatGPT web | ~25.000–32.000 caracteres |
| janela de contexto do consumidor | 32k tokens (grátis) a 128k–1M (pago) |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | 32.000 por padrão, teto 64.000 |
| `MAX_MCP_OUTPUT_TOKENS` | 25.000–50.000 tokens (resultado de ferramenta) |
| `BASH_MAX_OUTPUT_LENGTH` | 30.000 caracteres |
| leitura de arquivo no CLI | 25.000 tokens por leitura |
| `usage` do CLI | vem de `message_start.input_tokens`; zerar faz o agente **nunca** compactar e entrar em laço de “prompt too long” |
| `prompt is too long: N tokens > M maximum` | é lido e usado para cortar turnos antigos (2.1.283+) |
| API Responses | cliente espera `code: context_length_exceeded` |

## 2. Hipóteses pré-registradas (antes do código)

| # | Hipótese | Como seria falsificada |
|---|---|---|
| H1 | mandar **só o delta** por turno mantém a conversa do site linear (cresce pelo tamanho do turno, não pelo histórico inteiro) | se o número de envios crescer com o histórico, ou se cada turno reenviar tudo |
| H2 | o primeiro pedido real do Claude Code cabe em **≤ 3 blocos** de 20k com o protocolo de ferramentas resumido | se precisar de mais de 3 partes |
| H3 | uma falha **antes de digitar** (página ainda carregando) pode ser repetida internamente e virar sucesso sem o CLI ver erro | se o CLI ainda receber erro nesse cenário |
| H4 | uma chamada de ferramenta cortada no meio pode ser completada com **um** envio de continuação e então interpretada | se continuar inválida depois da continuação |
| H5 | informar `usage` estimado (4 caracteres ≈ 1 token), rotulado, faz o medidor do CLI sair de zero | se o CLI continuar mostrando zero/`null` |

## 3. Decisão

**D1 — um envio nunca passa de `message_chars` (padrão 20.000).** O menor teto
observado em chat web é 25k; 20k deixa margem para o cabeçalho de parte e para a
digitação. Configurável de 4.000 a 30.000 no painel.

**D2 — prompt grande vira blocos numerados com confirmação.** `[parte 1/3]` pede
apenas `recebido 1/3`; só a última parte carrega o pedido de verdade. A
confirmação obriga o site a processar antes do próximo envio (o fluxo já espera
a resposta terminar) e evita empilhar texto em um campo que ainda está
processando.

**D3 — modo `delta` depois de um início verificado.** O histórico completo fica
com o CLI (ele já o tem); o site recebe o *início* (system + protocolo de
ferramentas + histórico inicial) e, nos turnos seguintes, só as mensagens novas
mais um **lembrete curto** do protocolo. Consequência declarada: o site não é a
fonte de verdade do histórico.

**D4 — livro-caixa + rotação + retomada.** A API guarda o que **acredita** ter
entregue (hash de cada mensagem, caracteres, identidade da conversa). Quando
(a) o total passaria de `conversation_chars` (padrão 200.000), ou (b) o cliente
reescreveu o histórico (compactação do próprio CLI), a conversa é **trocada por
uma nova** e o contexto é **retomado** de forma determinística: system e
protocolo inteiros, turnos recentes inteiros, turnos antigos como uma linha cada
(“pedido anterior: …”), com o número de omitidos declarado. Nada é resumido por
modelo escondido.

**D5 — `usage` é estimativa rotulada, não zero.** `input_tokens` ≈
`ceil(caracteres/4)` do pedido recebido, `output_tokens` ≈ o mesmo da resposta,
com `browserapi.usage.source = 'estimativa por caracteres'`. Zero fazia o CLI
nunca compactar; inventar número exato seria mentira. A estimativa é conservadora
(conta o pedido inteiro, não só a janela do site).

**D6 — erro no vocabulário do cliente, e só quando é verdade.** Se nem fatiando
couber: Anthropic recebe `prompt is too long: <N> tokens > <M> maximum` (com
`browserapi.note` dizendo que N e M são estimativas); OpenAI recebe
`code: context_length_exceeded`. Nunca antes de tentar os blocos.

**D7 — falha antes de digitar é repetida aqui, não no CLI.** Espera ativa de
prontidão (campo visível, editável, sem rascunho) com recarga única, e até dois
novos envios internos enquanto `send_state == 'not_sent'`. Depois disso, o HTTP é
**503/529** (retentável), não 409. 409 fica reservado para “pode ter sido
enviado”.

**D8 — saída em blocos com continuação.** Resposta que bate no teto do bloco,
com cerca de código aberta ou com JSON de ferramenta incompleto ganha um envio
`[continuação] Continue exatamente de onde parou`. Os blocos são unidos com
remoção de sobreposição. `stop_reason`/`finish_reason` = `max_tokens`/`length`
quando foi o nosso teto que parou; `end_turn`/`stop` quando o modelo terminou.

**D9 — resultado de ferramenta gigante é reduzido, não engolido.** Resultados
antigos (fora dos últimos turnos) são cortados em cabeça e cauda com marcador
`[reduzido localmente: N caracteres omitidos]`; o mais recente fica inteiro. O
total reduzido aparece em `browserapi.reduced`.

## 4. Premortem (o que pode dar errado e a defesa)

| Falha | Defesa |
|---|---|
| modo `delta` responder com base em conversa alheia | início só em conversa **verificada vazia**; se não for possível, envia o contexto inteiro (autossuficiente) e marca `conversation: 'shared'` |
| blocos dobrarem custo e latência | só quando passa do teto; confirmações são curtas; número de partes no relatório |
| retomada perder instrução crítica | system, protocolo e pedido atual nunca são cortados; omitidos só os turnos do meio, com contagem |
| continuação duplicar texto e quebrar código | remoção de sobreposição + cerca de código; se continuar aberta, `continuation: 'incomplete'` e nada é inventado |
| repetição duplicar mensagem no site | só com `send_state == 'not_sent'`; depois de digitar, nunca |
| estimar tokens virar “inventar tokens” | rótulo em toda resposta, no cabeçalho e na documentação; nunca chamado de medição |

## 5. Surpresa e implicação

**Surpresa:** o CLI não protege o primeiro turno. Um 400 `prompt is too long`
(que parecia o “erro correto” a devolver) encerra a sessão em uma requisição.
**Implicação:** fatiar não é otimização, é requisito de funcionamento; e o erro
de contexto só pode ser usado como último recurso.

**Surpresa 2:** `output_config` derrubaria o primeiro pedido real — o teste com o
CLI de verdade encontrou em segundos o que o teste sintético não encontrava.
**Implicação:** o teste de fogo com o binário real entra no CI.

**Surpresa 3:** `usage: 0` não é “honesto”, é uma armadilha: o medidor do agente
nunca enche e ele nunca compacta. Honestidade aqui é **rotular a estimativa**.

## 6. Resultados (depois do código)

Teste de fogo: **Claude Code 2.1.312 de verdade** (`scripts/claude_firetest.py`,
execução de 75 s) apontado para esta API, com um chat simulado que recusa o que um
chat real recusa (campo de 20.000 caracteres por envio; janela de 200.000, e de
**24.000** no cenário que força a rotação) e que **falha “antes de digitar”** para
simular a página carregando. **Sete cenários**, todos `exit 0` e nenhuma recusa
do site:

| Cenário | O que prova | Envios ao site |
|---|---|---|
| pergunta simples | pedido de ~46k vira **2 blocos** de ~19,2k | 2 |
| ferramenta | `tool_use` → Bash → `tool_result` → resposta | 2 (2º turno em **delta**) |
| **arquivo de 120 KB** | arquivo muito maior que o campo vai pela entrada padrão e é **fatiado em 9 blocos**, remontado sem perda | **9**, maior 19,9k |
| **janela pequena (24k)** | 2ª sessão (`--continue`) dispara **retomada**: conversa nova (`rotate`), contexto reescrito em 2 envios | 2 + 2 |
| **janela apertada (22k)** | o 1º turno **compacta** em vez de ser recusado; o 2º dispara **retomada** (`restore`) | 2 + 2 |
| **página lenta** (4 falhas antes de digitar) | repetição interna + reespera; o CLI **não vê erro** | 2 |
| **resposta cortada** | cerca de código aberta → continuação pedida e blocos unidos | 3 |
| **mensagem que demora a pintar** | envio confirmado, 1º veredito `timeout` → **reespera** (`harvest`) e o CLI recebe a resposta | 2 |

Medido no total: maior envio **19.901 caracteres** (teto 20.000), nenhuma recusa,
`página_lenta=2` absorvidas.

| # | Hipótese | Veredito |
|---|---|---|
| H1 | delta mantém a conversa linear | **confirmada** — numa sessão retomada (`--continue`) o turno novo foi de **326 caracteres** em vez de ~46k |
| H2 | 1º pedido real cabe em ≤ 3 blocos de 20k | **confirmada com folga** — 2 blocos (com o protocolo resumido em ~7,3k em vez de ~30k de esquema) |
| H3 | falha antes de digitar é repetida e vira sucesso | **confirmada** — até **4** falhas de prontidão no cenário “página lenta”, `site_refused: []`, CLI com `exit 0` |
| H4 | continuação recupera saída cortada | **confirmada nos dois níveis** — unitário e no cenário “resposta cortada” do teste de fogo (cerca aberta → 3 envios, texto unido) |
| H5 | `usage` estimado sai de zero | **confirmada** — `input_tokens`/`output_tokens` > 0, `estimated: true` |

Três defeitos reais apareceram **só** no teste de fogo, e cada um quebrava a
primeira requisição do CLI:

1. `output_config` recusado como parâmetro desconhecido;
2. mensagem com papel `system` **dentro** de `messages` (beta
   `mid-conversation-tool-changes`) recusada;
3. a última mensagem da lista é um lembrete de **sistema** (`[user, system]`), e
   a regra “a última precisa ser do usuário” recusava a chamada.

Também caíram **dois** erros de desenho na mesma decisão. Primeiro, decidir “a
página está vazia, mande tudo” pela contagem de itens do DOM: conversa com
carregamento preguiçoso parece vazia e o contexto ia **duas vezes** ao site.
Depois, usar a **URL** como identidade da conversa: sites trocam o endereço ao
criar a conversa, e aí o delta ia para uma página recarregada — o CI mostrou
`AssertionError: 109 != 0` exatamente nisso. A identidade agora é o **documento**
(`performance.timeOrigin`): recarregar muda a marca, trocar a URL não. Os dois
casos têm teste (`two_turns` em `tests/test_conversation.py`).

## 7. O que continua não sendo prometido

- não há contagem de tokens do provedor; tudo é estimativa por caracteres;
- o modo `delta` depende de o site manter a conversa; se a página for recarregada
  ou trocada, a API detecta pela identidade da conversa e retoma do zero;
- “reverter contexto” é **abrir uma conversa nova e retomar por escrito** — não
  é desfazer o que já foi dito no site;
- a redução de resultado de ferramenta é corte com marcador, não sumarização;
- nenhum teste aqui usa conta real: o teste de fogo usa o binário real do CLI
  contra um chat **simulado**, em CI.

## Fontes

- `code.claude.com/docs/en/settings` (variáveis de limite de saída) e relatos de
  `anthropics/claude-code` #24055, #10738, #6158, #57296;
- `router-for-me/CLIProxyAPI` #6869 (`context_length_exceeded` na Responses) e
  `weave-os/router` #1876 (o CLI fatia turnos ao ler `prompt is too long`);
- `headroomlabs-ai/headroom` #3998 (esconder `usage` faz a sessão girar em
  “prompt is too long”);
- limites de campo de chat web: ~30k (Gemini), ~25k–32k (ChatGPT);
- `MAX_MCP_OUTPUT_TOKENS`, `BASH_MAX_OUTPUT_LENGTH`, leitura de arquivo: docs do
  CLI e #47 de `m4rocks/claudiu`;
- medidas próprias: servidor de captura + Claude Code 2.1.312 (tabela da seção 1).
