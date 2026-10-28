# Decisões Técnicas — browserapi-lab

Formato: ADRs curtas. Cada decisão registra contexto, decisão, consequências e — quando aplicável —
o experimento que a valida ou refuta.

---

## ADR-001 — Playwright Python (API síncrona) como mecanismo base

* **Contexto:** o briefing pede Playwright + Chromium como hipótese inicial, permite comparar com
  Chromium do sistema/Chrome e só admite CDP direto se medição mostrar benefício.
* **Decisão:** começar com `playwright.sync_api`, que é a API mais simples para um laboratório de
  concorrência 1. O canal do navegador é configurável (`chromium` gerenciado pelo Playwright,
  `chrome` do sistema, `chromium` do sistema) e escolhido por medição, não por preferência.
* **Consequências:** código linear e fácil de depurar; se o custo de CPU/RAM do Chromium gerenciado
  for inaceitável no laptop de 4 GB, E-BENCH comparará canais antes de qualquer migração para CDP.
* **Validação:** E-BENCH-1 (startup frio/quente, RSS) nos três canais disponíveis no ambiente.

## ADR-002 — Núcleo em Python puro; JavaScript injetado mínimo

* **Contexto:** o ambiente de desenvolvimento remoto não tem navegador (ver
  `docs/EXPERIMENT_PLAN.md` §3.1). Se toda a lógica vivesse dentro da página, nada poderia ser
  testado fora de um navegador. O briefing também pede "mínimo de dependências" e probes injetados
  automaticamente pelo Playwright.
* **Decisão:** dividir responsabilidades:
  * **JavaScript na página (`probes/chat_probe.js`)**: só o que exige estar dentro do DOM —
    coleta de candidatos (atravessando Shadow DOM/iframes), instalação do `MutationObserver`
    e captura de sinais de UI (`aria-busy`, Stop, Copy).
  * **Python (biblioteca padrão)**: pontuação/ranking, decisão de término, serialização Markdown,
    lock de perfil, agregação de métricas e escrita de relatórios.
* **Consequências:** ~80% da lógica é testável com `unittest` sem navegador; o JS fica pequeno e
  auditável. Custo: o JS e o Python precisam concordar no formato dos candidatos — garantido por um
  contrato de dados versionado (`schema_version`) e testado.
* **Status:** aceita.

## ADR-003 — Extração por serialização fora do DOM real

* **Contexto:** "nunca remova controles do DOM real".
* **Decisão:** o extrator nunca clona nem muta nós vivos para limpar a resposta. Ele recebe uma
  **string HTML** (capturada de um clone descartável) e a serializa em Python com `html.parser`,
  ignorando o que não deve aparecer (controles de feedback, nós ocultos, `aria-hidden`).
* **Consequências:** o DOM real é intocável por construção — a extração nem tem referência a ele.
  Não dependemos de `innerText` (que varia com layout) para o caminho principal, apenas como
  baseline comparada.
* **Validação:** E-EXT-4 (hash do HTML antes/depois da extração).

## ADR-004 — Perfil exclusivo + lock por arquivo

* **Contexto:** "nunca usar o perfil pessoal do Chrome" e "nunca abrir o mesmo `user_data_dir` em
  dois processos".
* **Decisão:** perfil sempre sob `profiles/<nome>/`, e um lock cooperativo com `fcntl.flock` em
  `profiles/<nome>/.lock` contendo pid, host e timestamp. Falha rápida com erro claro se ocupado.
* **Consequências:** protege contra corrupção de perfil por execução concorrente. Não protege
  contra outro processo alheio ao laboratório — documentado como limitação.
* **Validação:** E-SESS-3.

## ADR-005 — Descoberta por pontuação, nunca por seletor fixo

* **Contexto:** "não depender somente de seletores fixos"; seletores de Gemini/LMArena são
  hipóteses, não contratos.
* **Decisão:** o JS coleta sinais por elemento (role, accessible name, `aria-label`, placeholder,
  `name`, `data-testid`, `contenteditable`, tipo do controle, id estável, visibilidade,
  editabilidade, unicidade, proximidade do composer/conversa, comprimento do caminho). O Python
  pontua com pesos explícitos e penaliza classes dinâmicas, caminhos longos, `nth-*`, ambiguidade
  e texto dependente de idioma.
* **Consequências:** o ranking é explicável (cada nota vem com o detalhamento dos sinais), o que é
  essencial para diagnosticar mudanças de DOM. Seletores conhecidos entram como **bônus de
  hipótese** (`known_hint`), nunca como única fonte.
* **Validação:** E-DISC-1..6.

## ADR-006 — Término por combinação de sinais, nenhum sinal é universal

* **Contexto:** "nenhum sinal isolado deve ser considerado universal"; pausa artificial não pode
  finalizar prematuramente.
* **Decisão:** `observer.py` mantém um estado explícito alimentado por eventos (mutações, sinais de
  UI) e três políticas comparáveis — `stability_only`, `ui_signals`, `hybrid`. `hybrid` exige
  **estabilidade + pelo menos um sinal de UI positivo** (ou ausência de sinal de "ocupado"), com
  janelas e timeouts configuráveis, e nunca decide antes de haver conteúdo.
* **Consequências:** a política é determinística e testável com linhas de tempo sintéticas (sem
  navegador): pausa longa, resposta vazia, Copy antes da estabilidade etc.
* **Validação:** E-OBS-3..8.

## ADR-007 — Estratégia de teste em dois níveis

* **Contexto:** sandbox sem navegador; o laptop do usuário é o único lugar para testes headed com
  login; ainda assim é preciso evidência real da integração com navegador.
* **Decisão:**
  1. `tests/` com `unittest` (biblioteca padrão) para todo o núcleo Python — roda em qualquer
     lugar, inclusive sem Playwright instalado (imports de Playwright são tardios).
  2. Integração real com Chromium no **GitHub Actions** (`ubuntu-latest`), que executa a bateria
     completa contra a fixture local e publica os resultados como artefato.
  3. Testes headed com login real ficam em scripts assistidos, executados pelo usuário (M8).
* **Consequências:** nenhum teste de navegador é "simulado"; onde não há navegador, o teste é
  explicitamente `SKIPPED` com motivo, nunca verde.
* **Status:** aceita.

## ADR-008 — Dependências: apenas `playwright`

* **Contexto:** "mínimo de dependências", "sem Docker, banco, Selenium, Node externo, FastAPI".
* **Decisão:** `requirements.txt` contém **somente** `playwright`. Todo o resto é biblioteca
  padrão (`argparse`, `json`, `csv`, `html.parser`, `fcntl`, `statistics`, `unittest`). `pytest`
  **não** será adicionado sem necessidade comprovada.
* **Consequências:** instalação simples no laptop de 4 GB; nenhum serviço extra em memória.

## ADR-009 — Privacidade e sanitização por padrão

* **Contexto:** "nunca registrar cookies, tokens, senhas ou conteúdo privado".
* **Decisão:** o módulo de sessão sanitiza o estado exportado (mantém apenas origens, nomes de
  chaves e contagens; nunca valores). Screenshots/traces são desabilitados por padrão e, quando
  ligados, vão para `results/` (ignorado pelo Git). O texto das mensagens enviadas em sites reais
  não é gravado por padrão — apenas comprimento e hash.
* **Consequências:** o repositório pode ser público sem vazamento; diagnóstico continua útil.
* **Validação:** teste unitário de `sanitize_storage_state` + revisão manual antes de cada commit
  que toque `results/`.

## ADR-010 — Streaming: MutationObserver principal, polling como baseline

* **Contexto:** comparar observador com polling.
* **Decisão:** `MutationObserver` é o mecanismo principal; um poll leve (padrão 100 ms) roda em
  paralelo **apenas como baseline de medição** para E-OBS-2, não como fonte da resposta.
* **Consequências:** medição honesta do custo de cada abordagem; o caminho principal não sofre
  overhead de polling.

## Decisões adiadas (com critério para reabrir)

| Tópico | Quando decidir |
|--------|----------------|
| CDP direto vs Playwright | se E-BENCH mostrar overhead do Playwright > 20% do tempo total por mensagem |
| Canal do navegador (gerenciado vs sistema) | após E-BENCH-1 nos canais disponíveis |
| `pytest` | se `unittest` se mostrar insuficiente (fixtures complexas/parametrização) |
| Modelo de adaptadores por site | no Marco 8, após medir drift real de Gemini e LMArena |

## ADR-011 — Confirmação comportamental e contrato de resposta opt-in

Sugestão do usuário: usar o esvaziamento do composer após envio e a sintaxe de
resposta solicitada para desambiguar os elementos encontrados.

- O esvaziamento é evidência adicional, não contrato universal. É necessário
  observar o valor correto antes, campo vazio depois e nova mensagem do usuário.
  Campo removido do DOM não é considerado vazio. Não experimentar Enter em vários
  candidatos: isso pode enviar mensagens duplicadas ou agir em outro formulário.
- A saída pode usar um contrato JSON opt-in com identificador aleatório novo por
  tentativa e `answer` string. Não alterar o prompt sem consentimento. Sintaxe
  inválida não prova campo errado: o modelo pode simplesmente desobedecer.
- Validar somente mensagens novas do assistente, nunca o prompt ecoado ou um
  ancestral que agregue a conversa inteira. Esperar fim do streaming em separado.
- Se houver mais de uma candidata válida, registrar ambiguidade; não escolher a
  primeira silenciosamente nem enviar outra mensagem automaticamente.
- O contrato não prova veracidade, autoria nem segurança do conteúdo.

Implementação experimental: `validation.py`, com dez testes puros executados.
Ainda **não integrada ao sender/observer nem validada em navegador real**. Próximo
experimento: fixture com decoys, resposta incompleta, resposta antiga, eco do prompt,
recriação do composer e duas mensagens válidas. Comparar taxa de acerto e latência.

## ADR-012 — Navegador escolhido pelo usuário, modelo manual

Usar navegador visível escolhido pelo usuário (primeiro Chromium gerenciado ou
Chrome/Chromium instalado, configurável via `BrowserConfig.channel`). Não há
necessidade de descobrir ou trocar modelos automaticamente: usuário faz login,
seleciona o modelo, confirma prontidão e autoriza o teste real.

"Navegador do usuário" significa o produto/binário escolhido, não reutilizar o
perfil pessoal padrão. Manter perfil exclusivo, lock e processo iniciado pelo
laboratório. Conectar a uma instância pessoal arbitrária não está implementado.
Suporte a outros produtos depende de experimentos de compatibilidade, não é
prometido. Sem varredura de modelos e sem tentativas de contornar autenticação.

## ADR-013 — Consolidação executável e segurança de retry

`verify` roda somente contra fixture local com perfil temporário e uma aba.
Os assets são dados do pacote instalado. O CI testa o console script fora do checkout.
Não ampliar isso para um serviço de produção ou API antecipadamente.

Após tentar ativar envio, falha de confirmação é ambígua: parar sem retry automático,
mesmo se o campo permanecer preenchido. Não existe garantia de exatamente uma entrega
em um site externo sem suporte do próprio site. Esvaziamento do composer é sinal
adicional, não obrigatório para sucesso quando já há nova mensagem comprovada.

Reinstalar o probe de streaming desconecta o observador anterior. Descoberta prioriza
DOM recente com teto de nós/candidatos. Não se considera uma estratégia universal:
composers fora da região recente ainda podem exigir adaptação.

Pin de Playwright 1.64.1 para reproduzir esta rodada. Mudança de versão exige novo CI.
A aprovação final é a do relatório `VALIDATION_REPORT.md`, não uso contínuo 24/7.

## ADR-014 — Metas de produto, configuração assistida e homologação por execução

As seis perguntas do usuário passam a ser gates em `PRODUCT_GOALS.md`.
Implementar seleção de navegador/chat, diagnóstico, recibos e apontamento visual
não autoriza declarar Gemini/LMArena homologados sem autenticação real assistida.

`configure/check/repair/ask` abrem janela visível, usam perfil dedicado por chat,
aguardam login e modelo manuais, e exigem consentimento para uma mensagem.
`status/chats` não abrem navegador nem enviam nada. Não há importação de perfil
pessoal, autoidentificação de modelos, bypass ou retry de envio ambíguo.

O check usa nonce, mensagem nova do usuário e resposta nova com contrato JSON;
conteúdo é mantido somente em memória, nunca no recibo. Configuração alterada
invalida recibos. Budget de captura e funcionalidade são resultados separados;
comparação de API fica `not_measured` até existir evidência equivalente.

Escolha e reparo de campos são por apontamento no navegador, com seletores
relativos ao autor para isolar conteúdo. A hipótese de turnos novos (em vez de
reutilização/virtualização de um único nó) é limitação explícita desta versão.

Dados locais usam arquivos 0600. Relatórios públicos não contêm texto de conversa,
cookies, URL privada ou seletores. O estado de aprovação e limites está em
`PRODUCT_VALIDATION.md`; nenhum gate externo é fechado por simulação local.


## ADR-015 — Painel local e instalação Ubuntu com consentimento

Após o usuário informar que não sabia utilizar o terminal, o fluxo CLI não
pode ser apresentado como facilidade de uso comprovada. Acrescentamos painel
HTTP stdlib servido exclusivamente em loopback, token de sessão no fragmento
inicial, autenticação por cabeçalho, verificação de Host/Origin, CSP, corpo
limitado e conteúdo dinâmico como texto. Não é o servidor de API adiado.
Um worker serializado mantém os objetos Playwright na mesma thread. As
perguntas do assistente usam identificadores únicos, respostas por botões e
consentimento antes de cada envio. Login/modelo permanecem manuais.

O `.deb` só contém aplicação e launcher: sem scripts privilegiados nem rede
durante instalação. Dependências do sistema são declaradas ao gerenciador de
pacotes. A preparação opcional, explicitamente confirmada, cria venv no
usuário e baixa Playwright fixado/Chromium, sem sudo ou shell. O launcher
recusa execução como root. Python 3.11+ permanece obrigatório. Alvo verificado
em CI Ubuntu 24.04, mesma base do Linux Lite 7.2 informado pelo usuário;
instalação gráfica nesse desktop ainda não homologada.

Evidência: Actions 40153757793, código 7020ea3, 244 testes/1 ignorado sem
falhas; montagem e simulação de dependências aprovadas. Não equivale a
compatibilidade autenticada com Gemini/LMArena ou serviço OpenAI pronto.


## ADR-016 — Botão em dois estados e sessão pessoal consentida

O usuário identificou o estado microfone/Enviar e solicitou explicitamente seu
perfil pessoal já logado (escolha confirmada no painel de perguntas). Essa é uma
revisão do escopo anterior que proibia o perfil pessoal. Não passamos a lançar
Playwright sobre o diretório pessoal: conectamos ao Chrome existente apenas
por endpoint publicado pelo próprio Chrome, depois de consentimento explícito.
Chrome 144+ oferece um fluxo nativo com permissão; sua disponibilidade nessa
máquina não é garantida. Nenhuma cópia de cookies, porta remota configurável ou
contorno de bloqueio Google é introduzido. O CDP tem acesso amplo às abas/contas:
o risco é explicado antes da conexão. Falha em ambiguidade de abas/contextos;
a desconexão não fecha o navegador pessoal.

Para apontar Enviar no estado correto, a GUI oferece rascunho temporário
explicitamente autorizado. A seleção continua sem enviar. A limpeza só remove
o rascunho próprio idêntico e preserva conteúdo anterior/edições do usuário.
Indícios explícitos de voz/microfone impedem selecionar/ativar o controle.

A integração permanece stdlib + Playwright, sem MCP/Node/extensão. A validação
sintética CDP não substitui homologar o diálogo de permissão e a sessão real do
Chrome pessoal. Não prometer login ou compatibilidade autenticada com Gemini.


## ADR-017 — Voz como estado negativo ensinado e conexão sem criação de aba

O usuário rejeitou a abertura em visitante e pediu botões separados para
selecionar voz e, após digitação humana, selecionar Enviar. A GUI passa a esse
fluxo, sem rascunho automático. O texto da pessoa é preservado e o apontamento
não dispara teste de saúde. A exclusão de voz combina seletor e fingerprint
do estado: nunca ignorar cegamente o mesmo nó, pois ele pode virar Enviar.

Chats antigos mantinham session_mode do perfil separado apesar de alterações
no formulário de novos chats. Acrescentamos mudança explícita consentida no
chat salvo. O modo CDP só aceita uma aba do chat já aberta. Na ausência dela,
falha sem new_page, lançamento de Chrome ou fallback de perfil; não presume
identidade da conta nem lê cookies para deduzi-la. A seleção de contexto/conta
do Chrome pessoal continua uma limitação externa não homologada.


## ADR-018 — Assistente GUI sem salto da etapa de voz e versões explícitas

O usuário reportou ausência da pergunta de voz durante configuração/correção,
regex HTML inválida no Chrome, favicon 403 e API/task 400. GUI passa sempre pelo
assistente manual, pergunta presença de voz no campo vazio (Sim/Não), seleciona
voz só se presente e obrigatoriamente ensina Enviar após digitação humana.
Não converter isso em envio real nem apagar rascunho da pessoa.

Corrigimos a classe de caracteres HTML para o modo v, favicon público vazio
com Host validado, mensagens controladas de validação e exibição das versões
GUI/runtime. Versões diferentes bloqueiam tarefas e consentimentos na GUI,
sem desativar os mecanismos de segurança do servidor. O diagnóstico não prova
qual versão o usuário executava nem a causa de cada 400 reportado.


## ADR-019 — Medir antes de otimizar; métricas não são conteúdo nem heartbeat

O usuário descreveu uma futura API local com sessões, otimização, atualizações,
contexto/RAG, fallback e dashboard e delegou a escolha do marco inicial. Escolhido
M1: tempos de browser/aba e fases de troca, painel com janela limitada em memória
e estados observados. Não ativar bloqueio de recursos, headless, replay de rede ou
reenvio automático antes de medir estabilidade/correção.

Média/P95 usam somente latências disponíveis, sem substituir ausência por zero;
consumo de tokens é desconhecido. Telemetria usa lista branca, não copia conteúdo
ou exceções. Finalização de métricas e publicação da fase da tarefa são atômicas
para impedir que uma nova tarefa apague o recibo anterior. Observação Online não
é disponibilidade permanente e não dispara mensagem de monitoramento. Configuração
sem novo teste invalida Online anterior. Plano separado em NEXT_ARCHITECTURE.md;
RAG pesquisável de 1M não implica contexto nativo de 1M. API e fallback exigem
contratos e confirmação de envio antes de automatizar decisões potencialmente
duplicantes. Validação deste marco em PRODUCT_VALIDATION.md.


## ADR-020 — Resposta validada é exibida na memória do painel, nunca no recibo

O cartão **Conversa** da 0.7.0 existe porque a resposta só aparecia no log técnico
recolhido. A exibição não pode reabrir os caminhos que os marcos anteriores
fecharam: conteúdo em recibo, telemetria de texto, histórico não solicitado ou
aceitação de resposta antiga.

Decisão: `transcript.Transcript` guarda pares pergunta/resposta por conexão **em
memória do processo**, com orçamento e descarte em pares. `setup.check` recebe um
`record` opcional chamado apenas quando houve mensagem enviada com resposta nova
validada; verificação automática sem mensagem da pessoa nunca entra. Falha ao
exibir não converte envio bem-sucedido em erro nem dispara reenvio. O estado do
painel carrega só contagem/revisão; o texto é buscado por rota autenticada e
limitada à conexão pedida. Renderização usa `textContent`, então HTML da página
não é interpretado.

Não é histórico do site, não é o RAG da API local e não é persistente: reiniciar
apaga; excluir a conexão apaga aquele texto. A API de agentes continua com seu
próprio registro e histórico opt-in, fora desta conversa. Sem autenticação real de
Gemini/Arena, isto é exibição validada em fixture e DOM emulado, não homologação.


## ADR-021 — Confirmação de envio por evidência tolerante, nunca por otimismo

O relato de uso real trouxe “Envio sem confirmação” para uma mensagem que aparecia
na tela. A regra anterior exigia texto idêntico ao preenchido no último balão do
usuário, em 5 s — frágil porque sites re-renderizam mensagens (espaços, `NBSP`,
invisíveis) e podem demorar a pintar o balão.

Decisão: comparar texto normalizado (`NFKC`, invisíveis removidos, espaços
colapsados); aceitar lista virtualizada que atualiza o mesmo nó; esperar até 9 s
(teto `timeout_ms`); e aceitar **mensagem nova com campo esvaziado** como evidência
de que o site consumiu o rascunho. A evidência usada vai no recibo em
`diagnostics.send_evidence`.

O que permanece proibido: reenvio automático, sucesso com texto divergente e
rascunho presente, e tratar campo esvaziado sozinho como envio. A mudança só reduz
falso negativo — não cria caminho para mensagem duplicada. Continua sendo
observação de DOM; não há garantia de exactly-once em site externo.

Também nesta rodada: HTML do painel passou a ser validado por parser nos testes,
depois de uma aspa faltante quebrar o id da aba Atividade na 0.7.0.


## ADR-022 — A chamada da API termina quando o worker termina

`llm_api` contava requisições ativas até o fim do `finally`, depois de escrever a
resposta HTTP. Um cliente que revogava a chave ou apagava o histórico logo após
receber a resposta era recusado com 409 “ocupado”, embora o navegador já estivesse
livre — o teste de histórico do CI mostrou o problema de forma intermitente.

Decisão: liberar o contador assim que a resposta é produzida (antes de escrever o
socket), em todos os caminhos, com liberação idempotente. O limite de concorrência
continua valendo para trabalho real; a transmissão da resposta não é trabalho. Não
houve afrouxamento de autenticação, de limite de corpo ou de recusa por envio
ambíguo.



## ADR-023 — O apontamento de mensagem é do BALÃO, não do pedaço clicado

O usuário apontou a resposta no Gemini e recebeu só “Olá!”: a resposta estava em
dois `<span>` dentro de um `<p class="first-token">`, e o apontamento guardava o
elemento clicado. O seletor resultante (`p.first-token`) recortava a primeira
linha de **todas** as respostas, sem erro visível.

Decisão:

1. no apontamento, o alvo de mensagem sobe ao **marcador de papel** mais externo
   (`user-query`, `model-response`, `[data-message-author-role]`, `[data-role=…]`);
   sem marcador, sobe por sinais de classe/tag sem atravessar compositor, barra de
   ações (`> 2` botões) ou wrapper que misture pergunta e resposta;
2. a faixa do apontamento mostra **o texto que será capturado** antes de confirmar;
3. na leitura, o runtime pede ao probe o **balão inteiro** daquele nó, removendo do
   clone botões, `aria-hidden` e rótulos curtos de papel/avatar/cópia; se o probe
   não existir no frame, usa o elemento casado (limite declarado);
4. casamento aninhado (balão + pedaço) passa a contar como **um** resultado;
5. `Esc`/“Pular este campo” pula só o passo; “Cancelar mapeamento” é explícito.

Alternativas rejeitadas: pedir CSS ao usuário (contraria o produto), capturar
`innerText` do ancestral de maior texto (pegaria a conversa inteira), e confiar em
classes específicas do Gemini (quebrariam em qualquer mudança do site).

## ADR-024 — Leitura da conversa em camadas; o mapeamento é conferência, não descoberta

Contexto: o mapeamento apontado à mão era a **única** fonte de verdade para ler a
conversa. Um seletor apontado num pedaço ou que casava com a pergunta junto com a
resposta passou a produzir dois efeitos ruins: resposta lida errada e **falso
“envio não confirmado”** com a mensagem na tela. Pesquisa registrada em
`pesquisa/2026-10-28-arquitetura-captura-e-ui.md` (pré-registro congelado em
`pesquisa/2026-10-28-preregistro.md`) mostrou que exportadores maduros leem o
**estado do app** quando existe, e que a comparação por texto/estrutura sozinha
quebra a cada mudança de layout.

Decisão — `browserapi_lab/capture.py`, na ordem da força da evidência:

1. **papel declarado** (`user-query`, `model-response`, `data-message-author-role`,
   `data-role`, `data-author`, rótulo acessível);
2. **estado do React** (`__reactProps$…`/`__reactFiber$…` → `memoizedProps`): leitura
   do que já está na página, sem integrar API interna nem injetar script do site;
3. **estrutura** (container do transcript + ordem do DOM; alinhamento só como
   desempate) — último recurso, marcado como frágil.

Regras de escolha:

* se a leitura **apontada** está limpa (sem sobreposição, lados iguais, papéis
  alternados), ela manda — foi conferida por uma pessoa;
* se está suja e existe camada forte equilibrada, a camada assume com **aviso
  explícito** na conferência e no recibo (`fallback: true`);
* a camada **estrutura** sozinha nunca substitui o mapeamento (alternância inventa
  papel quando o site foge do padrão);
* toda leitura sobe ao **balão inteiro** (ADR-023) antes de medir texto.

Confirmação de envio: a mesma fonte de verdade (`capture.user_state`) e, quando há
nonce (`request_id`), o nonce no balão novo é a evidência mais forte. O caminho
antigo por consulta ao seletor apontado ficou como último recurso.

Fim de resposta: além de “sem Stop” e janela de estabilidade, o laço exige
**três leituras estáveis seguidas** (`min_stable_samples`). O botão parar
desaparece antes do texto terminar em vários SDKs.

Alternativas rejeitadas: lista de seletores por site (quebra a cada redesign);
geometria como filtro duro (falha quando o layout discorda da ordem); esperar
`networkidle` (SSE/heartbeat nunca ficam idle); tempo fixo (resposta longa estoura,
curta espera demais); API interna do site (contraria ADR-008).

Indicadores para revisitar: proporção de leituras resolvidas por camada (exposta
no recibo); se a camada 2 ficar em zero por 30 dias em site React, a rota morreu;
se a confirmação passar a citar “contagem” em 20 envios seguidos, a camada 1 caiu.

## ADR-025 — o painel do apontamento nunca intercepta o ponteiro

**Contexto.** O painel passou a ter tamanho fixo, ancorado no canto escolhido
pela geometria do alvo (ADR-024). O CI de navegador mostrou a consequência: com o
campo de mensagem no rodapé, o painel — 392 px de largura, ancorado embaixo —
cobria o próprio elemento que a pessoa devia clicar. O Playwright recusou o
clique com *“`<div id="__browserapi_picker">` subtree intercepts pointer events”*
e o teste ficou 30 s esperando. O uso real teria o mesmo efeito: o painel
bloqueia justamente o alvo.

**Decisão.**

* o **corpo** do painel tem `pointer-events: none`: clicar “através” dele
  atinge a página, então cobrir o alvo deixa de ser um defeito. Só os **botões**
  e a **alça de arraste** (`⠿`, 24 px) voltam a `pointer-events: auto`. O
  primeiro CI mostrou que deixar o título inteiro arrastável era suficiente
  para o `<strong>` do cabeçalho interceptar o clique — por isso a alça;
* a pontuação de canto pesa 12× a sobreposição com o que se precisa clicar
  (campo, botão) contra 1× para blocos grandes: o painel sai da frente do
  campo antes de sair de qualquer container;
* o painel **continua com tamanho fixo e sem rolagem** (`overflow: hidden`); o
  limite de altura é a tela, não a faixa livre (uma faixa curta não pode virar
  barra de rolagem);
* a escolha de canto segue a geometria (menor sobreposição com o alvo), mas
  agora a sobreposição é só visual, não funcional;
* o texto de conferência continua curto (três linhas) porque o corpo não rola.

**Consequências.** O arraste funciona igual, o alvo é sempre clicável, e o painel
não muda de tamanho conforme o canto. O custo é que o conteúdo visualmente
coberto atrás do painel não pode ser lido — por isso o arraste e o botão
“Mover” continuam existindo. Verificado por `scripts/ui_jsdom_check.js`
(29 checagens, incluindo “painel não rouba o clique da página”, “controles
continuam clicáveis” e “painel volta depois de re-render do site”).

**Indicadores para revisitar.** Se a automação voltar a falhar com
*intercepts pointer events*, é porque algum elemento novo dentro do painel ficou
sem `pointer-events: auto`. Se alguém reclamar de não conseguir selecionar texto
atrás do painel, é o preço do arraste — a alternativa (painel fora da tela) foi
rejeitada.
