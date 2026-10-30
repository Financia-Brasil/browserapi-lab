# browserapi-lab

Laboratório Python/Linux para validar automação de chats por navegador real.
**Não é um serviço homologado 24/7.** A versão 0.13.0 acrescenta uma API local
experimental e opt-in que fala **Anthropic Messages** (`/v1/messages`) e **OpenAI
Chat/Responses**, com tool calling emulado e **janelas de contexto** (prompt em
blocos, retomada de conversa, saída em blocos) — o suficiente para rodar o
**Claude Code** e outras CLIs de agente. Não é paridade com as APIs oficiais.
Veja [contrato, ativação e limites](docs/LOCAL_API.md) e
[janelas e limites medidos](docs/CONTEXT_WINDOWS.md).


## Baixar (sem terminal)

**[Instalador mais recente (.deb)](https://github.com/Financia-Brasil/browserapi-lab/releases/latest/download/BrowserAPI-Ubuntu.deb)**
— abra pelo gerenciador de arquivos e escolha instalar. O programa instalado se atualiza sozinho quando está ocioso.
Todas as versões ficam em [Releases](https://github.com/Financia-Brasil/browserapi-lab/releases). A pasta `downloads/`
deste código é histórica (0.3.1): não use os arquivos dela.

**Novo na 0.13.7:** o falso **“Há um rascunho no campo”** acabou — o campo é lido
ignorando placeholder e lixo de editor rico, então campo vazio envia. E a
**depuração do Chrome** passou a ser configurada **uma vez**: em Configurações →
*Depuração do Chrome, uma vez*, informe a porta (9222) e clique em *Configurar
uma vez*; o atalho **Chrome com depuração** abre seu Chrome já pronto (mesmo
perfil, nada copiado, porta só em 127.0.0.1) e a conexão pode até abrir o
navegador sozinha. Sem isso, tudo continua como antes.

**Novo na 0.13.1:** o envio passou a **colar** o texto de uma vez em qualquer
chat, em vez de digitar caractere por caractere (era lento e o site recebia a
mensagem pela metade). Antes de clicar em Enviar, o campo é lido e conferido:
texto faltando não é enviado, e um balão publicado pela metade é reportado como
corte, não como sucesso. A resposta ganhou uma **janela de confirmação** para
não terminar numa pausa do modelo. Detalhes em
[colar e completude](docs/PASTE_AND_COMPLETENESS.md).

**Novo na 0.13.0:** a API passou a lidar com o que uma CLI manda **antes** da
primeira pergunta: um pedido medido do Claude Code tem **~46 mil caracteres**
(system + 12 esquemas de ferramentas) e, num arquivo grande, pode passar de
**100 mil**. Agora esse pedido cabe em **1–2 blocos**
(o bloco de ferramentas vai resumido, ~7 mil em vez de ~30 mil), os turnos
seguintes enviam **só o delta** (medido: 326 caracteres no terceiro passo) e,
quando a conversa do site chega na janela, ela é **trocada e retomada** por
escrito — sem perder o pedido atual. Resposta cortada ganha **continuação** e os
blocos são unidos. `usage` deixou de ser zero: é **estimativa rotulada**
(4 caracteres ≈ 1 token), porque zero fazia o agente nunca compactar.
`output_config`, `system` no meio de `messages` e o lembrete de sistema no fim
(a forma real que o CLI envia) passaram a ser aceitos. Envio confirmado cuja
resposta demora não é mais “falhou”: a API **continua esperando e relendo**, com
prazos crescentes, em vez de reenviar a pergunta. Falha **antes de digitar**
é repetida aqui e responde 503 (retentável), não 409 — era isso que fazia o
agente dizer “não está funcionando” e desistir.

**Novo na 0.12.0:** a API local passou a aceitar as CLIs de agente. **`POST
/v1/messages`** (Anthropic) funciona com `x-api-key`, respostas no formato
`message`/`content`/`stop_reason`/`usage`, streaming com `message_start …
message_stop` e `count_tokens`. Para o **Claude Code**:

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:8765"   # sem /v1
export ANTHROPIC_AUTH_TOKEN="<chave do painel>"
export ANTHROPIC_MODEL="<alias do painel>"
claude
```

O painel mostra essas três linhas com o botão **Copiar variáveis**. As **tools são
emuladas por protocolo de texto** (`browserapi.tools: "emulated"`): o modelo é
instruído a responder `{"tool_calls":[…]}` e o programa interpreta; nome fora da
lista nunca vira chamada. Parâmetros sem equivalente (`temperature`,
`max_tokens`, `top_p`, `seed`…) são **aceitos e declarados** em
`browserapi.ignored` e no cabeçalho `X-BrowserAPI-Ignored` — recusá-los era o que
quebrava a CLI com “Parâmetro não suportado”. `usage` vem **zerado com nota**
(o site não informa tokens); nenhuma contagem é inventada. Campo desconhecido de
verdade ainda é 400 com o nome do campo.

**Novo na 0.11.0:** o painel passou a mostrar **um caminho só, com o próximo
passo e um botão**: *conectar → testar → ligar a API*. O nome da conexão é gerado
sozinho (sem digitar nem resolver “nome já salvo”). Na aba **API local** há o
**endereço completo** (`…/v1/chat/completions`) e um **exemplo de curl** prontos
para copiar, e um campo que **explica o erro** de endereço: IP incompleto
(`127.0.0`), porta errada e rota faltando (`Not found`) têm frases diferentes.
O recibo ganhou “Testar de novo”. Nada disso envia mensagem sem a sua
autorização.

**Correção na 0.10.1:** o painel do apontamento passou a **não interceptar o
clique** (o corpo deixa o ponteiro atravessar; só os botões e a faixa de arraste
respondem; arrasta-se pela alça `⠿`) — antes, de tamanho fixo, ele cobria o
próprio campo que a pessoa devia apontar. O painel também **volta sozinho** se o site re-renderizar o
`body`, e a checagem “o painel abriu?” aceita a escolha feita antes dela (o
reparo do botão Enviar parava com “o painel não abriu”). Ainda: a leitura em
camadas não confunde uma barra lateral de formulário com conversa.

**Novo na 0.10.0:** a leitura da conversa passou a ter **camadas** — papel
declarado na página, depois o estado do React (o que o app já sabe), e só por
último o layout. Quando o mapeamento apontado não lê a conversa de forma
coerente, quem manda é a camada, com aviso explícito, em vez de “envio não
confirmado” com a mensagem na tela. O fim da resposta exige **três leituras
estáveis** (o botão parar some antes do texto terminar). Correções do uso real:
a autorização do Chrome pessoal ficou **fora do bloco recolhido** e a recusa abre
com o nome da conexão; a preparação mostra as **últimas linhas de pip/playwright**
em vez de uma frase genérica; a aba **Atividade** grava só números e sobrevive à
atualização; a atualização verifica sozinha a cada 30 min (5 min após falha) e
tem **Verificar agora**; o painel do apontamento ficou de tamanho fixo, sem barra
de rolagem e arrastável. Pesquisa: [dossiê](pesquisa/2026-10-28-arquitetura-captura-e-ui.md)
e [pré-registro](pesquisa/2026-10-28-preregistro.md). Decisão: ADR-024.

**Novo na 0.9.1:** o mapeamento passou a **conferir a leitura da conversa** — exige
três perguntas suas com as três respostas na tela, mostra o texto de cada par, na
ordem, e recusa seletor que mistura pergunta com resposta ou conta a mesma camada
duas vezes. A API local ganhou **Testar conexão** e diz o motivo quando a porta não
abre (inclusive “já está em uso”). A 0.9.0 trouxe o mapeamento guiado de verdade —
 **Passo N de M** com instrução
por campo, prévia **“Vai capturar: …”** antes de confirmar, **Pular este campo**
(sem perder o resto), **refazer** um campo no fim e captura do **balão inteiro**
(a resposta do Gemini vinha partida em vários `<span>`). A 0.8.0 trouxe a
confirmação de envio mais honesta, o **Excluir** visível e a aba **Atividade**
com gráficos. Veja [o que mudou e os limites](docs/design/UX_090_SPEC.md).
A conversa no painel (0.7.0) e o perfil escolhido (0.6.1) continuam valendo.

## Janela para Ubuntu (experimental)

Agora há um painel local com botões de configurar, autorizar, testar e corrigir,
e montagem de instalador `.deb` com entrada no menu. A versão ubuntu4 inclui
**Selecionar botão de voz**, **Digitar e selecionar Enviar / Enter** e mudança
explícita de sessão em chats já salvos. A ubuntu5 integra a pergunta de voz
no assistente completo e mostra as versões da interface e do programa. A versão
**0.3.1** entregou dashboard e atualização automática com rollback. O código
**0.4.0** acrescenta inventário de perfis, API local, recuperação de contexto e
histórico opcional, preservando o atualizador. O instalador estável só muda após
os testes e a publicação automática da release. Veja o [guia sem terminal](docs/UBUNTU.md).
Alvo inicial: Ubuntu 24.04+ com Python 3.11+. A instalação gráfica no desktop do
usuário e os sites autenticados ainda não estão homologados; não é uma API de produção.


## Novo: escolher e verificar um chat

As [seis metas de produto](docs/PRODUCT_GOALS.md) agora orientam o desenvolvimento.
O assistente permite selecionar navegador e chat, fazer login/escolher modelo
manualmente, testar uma mensagem autorizada e reparar campos por apontamento:

```bash
browserapi-lab configure meu-gemini
browserapi-lab check meu-gemini
browserapi-lab status meu-gemini
browserapi-lab repair meu-gemini
browserapi-lab ask meu-gemini
```

## Correções da 0.8.0

- **“Envio sem confirmação” era falso negativo na comparação de texto.** A
  confirmação agora compara o texto normalizado (espaços, `NBSP`, invisíveis),
  aceita lista que reutiliza o mesmo nó e espera até 9 s. Mensagem nova com o campo
  esvaziado também confirma. Texto divergente com rascunho ainda preenchido continua
  sendo ambiguidade, e nada é reenviado automaticamente.
- **Excluir** conexão agora é botão visível em cada chat, com o nome na confirmação.
- **Apontar** pergunta “A SUA PERGUNTA JÁ ENVIADA (não o campo de digitar)” e instrui
  a enviar uma pergunta antes; cada pergunta tem uma linha de ajuda.
- **Atividade** virou seis gráficos em SVG; tokens seguem **Não medido**, com consumo
  real em caracteres e estimativa declarada como grosseira.
- Menos texto em Configurações e em “Sua próxima ação”.

## A resposta na tela (0.7.0)

Depois de **Conversar**, o turno aparece no cartão **Conversa**: “Você enviou” e
“Resposta capturada da página”, com data/hora e o tempo da troca. **Copiar última
resposta** copia o texto completo; **Limpar painel** apaga só a exibição local —
a conversa do site não é apagada e continua com o contexto. O texto fica apenas na
memória do programa (reiniciar apaga), nunca no recibo ou na telemetria, e é
renderizado como texto, sem interpretar HTML da página. Chamadas feitas pela API
local não entram nessa conversa. Limites: [UX_070_SPEC.md](docs/design/UX_070_SPEC.md)
e [revisão 0.7](docs/design/UX_070_REVIEW.md).

Leia o [guia de configuração e reparo](docs/CHAT_GUIDE.md) e o
[estado de validação das metas](docs/PRODUCT_VALIDATION.md). Compatibilidade só é
confirmada para a execução testada; Gemini/LMArena continuam aguardando homologação
assistida real. Seletores conhecidos são hipóteses, não garantia. Não há promessa
medida de equivalência a API ou funcionamento contínuo.

## O que já é executável

Um comando abre um Chromium real, serve uma fixture HTTP local, descobre os
controles, envia com confirmação, observa streaming, extrai Markdown e gera
JSON/CSV com métricas. Não abre sites externos, não faz login e não usa seu perfil
pessoal. Usa uma instância de navegador e uma aba quente, com concorrência 1.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
python -m playwright install chromium
# Somente se faltarem bibliotecas no Debian/Ubuntu; requer autorização administrativa:
python -m playwright install-deps chromium

browserapi-lab doctor
browserapi-lab verify --iterations 10
```

Para usar o Google Chrome instalado ou uma janela visível:

```bash
browserapi-lab verify --channel chrome --iterations 10 --results results/chrome
browserapi-lab verify --headed --results results/headed
```

`--headed` requer sessão gráfica. No CI é testado com display virtual (Xvfb);
isso não equivale a uma avaliação humana de usabilidade no laptop.
Também funciona a partir do checkout: `python -m browserapi_lab.cli verify`.

## Como interpretar o resultado

O comando `verify` imprime um resumo JSON e retorna:

| Código | Significado |
|---|---|
| `0` | Todos os cenários e o orçamento de latência passaram |
| `1` | Falhou algum cenário ou orçamento de latência |
| `2` | Argumentos inválidos, ambiente/navegador indisponível ou falha de inicialização |
| `130` | Interrompido pelo usuário |

Resultados em `results/verify/`:

- `summary.json`: ambiente, falhas, P50/P95, startup/reinício e RSS aproximado.
- `json/`: métricas por execução, sem conteúdo privado.
- `csv/metrics.csv` e `csv/runs.csv`: dados para análise.

**Uma resposta vazia que termina por timeout é um cenário negativo esperado**;
se o comportamento observado for o esperado, o experimento passa. Isso não
transforma timeout em uma resposta válida para um agente.

### Cenários do verificador

- Dez fluxos completos por padrão (configurável de 1 a 1000).
- Pausa de três segundos, Copy prematuro, ausência de Copy, campo input e contenteditable.
- Open Shadow DOM e iframe same-origin.
- Resposta vazia, erro, login expirado e rate limit simulados.
- Comparação `hybrid`, `stability_only` e `ui_signals` na resposta normal.
- Vinte mensagens adicionais na mesma aba/conversa, sem navegar entre mensagens.
- Reinício do perfil e verificação de reúso da aba.
- Preservação de estrutura Markdown e DOM intacto.

O orçamento conservador é **P95 < 2500 ms do último conteúdo até a conclusão da
verificação** na fixture. O tempo total inclui o streaming artificial: não é a
latência de Gemini/LMArena, nem um SLA de produção.

## Desenvolvimento e testes

```bash
python -m unittest discover -s tests -v
```

Para testar o contrato com uma CLI de agente de verdade, sem conta:

```bash
npm i @anthropic-ai/claude-code
python scripts/claude_firetest.py --claude "$PWD/node_modules/.bin/claude"
```

Ele aponta o **Claude Code real** para esta API e roda sete cenários (pergunta
simples, ferramenta, arquivo de 120 KB, janela apertada com compactação e
retomada, página lenta, resposta cortada e mensagem que demora a pintar) contra um chat simulado com os limites observados. Sem o
binário, `--no-cli` exercita o mesmo caminho pela HTTP. A saída fica em
`results/ci/claude-firetest.json` e o passo roda no CI.

Sem Chromium, as classes de integração são ignoradas com motivo explícito. No job
de navegador do GitHub Actions, o navegador é obrigatório: indisponibilidade gera
falha. O CI executa testes reais e testa o pacote instalado fora do checkout,
Chromium, Chrome do sistema e Chromium headed com Xvfb. Os logs e benchmarks
sanitizados ficam em `results/ci/<run_id>/`.

## Segurança e confiabilidade

- Por padrão usa perfil separado com lock cooperativo. A opção experimental de conectar ao Chrome pessoal já aberto exige consentimento explícito; não inicia outro processo no perfil nem copia cookies. Veja [o guia e os riscos de acesso](docs/UBUNTU.md).
- Não repete automaticamente um envio cuja aceitação seja ambígua.
- Campo esvaziado é evidência adicional, não prova isolada de envio.
- Contrato JSON opt-in rejeita saídas antigas e sinaliza múltiplas saídas válidas.
  A validação estrutural é um componente experimental; ainda não é adaptador de site.
- CAPTCHA, login e seleção de modelo são manuais. Não há descoberta automática de modelos.
- Não registra mensagens privadas, cookies ou tokens nos relatórios.
- O estado bruto exportado de sessão é sensível: deve ficar somente em `profiles/`,
  nunca ser anexado a relatórios ou versionado.

## Limites da entrega

**Pronto para uso como laboratório de validação local e CI. Não homologado para
agentes 24/7 ou automação genérica de sites reais.** Ainda é necessário:

1. Executar Gemini e LMArena com autenticação e autorização assistidas.
2. Medir compatibilidade e consumo no laptop de aproximadamente 4 GB.
3. Executar endurance prolongado (horas/dias), com recuperação de rede e sessão.
4. Validar adaptadores contra mudanças reais de DOM; seletores não são contratos.
5. Closed Shadow DOM, iframes cross-origin e CSS externo ocultando conteúdo têm
   limitações: a fixture não demonstra cobertura universal.

A API local da 0.4.0 é um subconjunto textual, opt-in e **não** um serviço 24/7:
não há FastAPI, fila de mensagens nem paridade com a API OpenAI. Rotas, limites e
alertas estão em [docs/LOCAL_API.md](docs/LOCAL_API.md).

## Dashboard e próxima arquitetura

A versão **0.2.0+ubuntu1** acrescenta dashboard local: sucesso/falha, latência
média/P95, fontes pelo último estado observado, fases da execução e até 30 barras
de histórico. Janela de 100 operações em memória, sem conteúdo de mensagens.
Tokens são **Não disponível**, não uma estimativa apresentada como consumo real.
Configurar, testar e conversar continuam exigindo consentimento; nenhuma
mensagem é enviada para monitoramento. Não foram ligados headless, bloqueio de
recursos, replay Fetch/XHR, atualizador ou failover automático.

O [plano da próxima arquitetura](docs/NEXT_ARCHITECTURE.md) descreve sessões,
otimização, releases, API local, fallback seguro e RAG/histórico pesquisável.
Histórico de 1M tokens **não** é contexto nativo de 1M tokens do modelo.
[Instalação gráfica e limites](docs/UBUNTU.md).

## Documentação

- [Relatório de validação](docs/VALIDATION_REPORT.md)
- [Plano de experimentos](docs/EXPERIMENT_PLAN.md)
- [Decisões técnicas](docs/DECISIONS.md)
- [Esquema dos resultados](docs/RESULTS_SCHEMA.md)


## Atualização automática (0.3.0)

O instalador atual inclui supervisor e atualizador: consulta releases estáveis
do repositório, verifica integridade/compatibilidade e aplica código automaticamente
quando não houver tarefa ativa. Mantém a aba, troca o processo com segurança e
restaura a versão anterior se a nova falhar ao iniciar. Não há reenvio de mensagens.
Ativação padrão visível e revogável na GUI; sem root. É necessária uma instalação
inicial porque as versões antigas não tinham esse mecanismo. Não é preciso
reinstalar cada próxima versão ABI 1. Veja [confiança, publicação e limites](docs/UPDATES.md).

O workflow de publicação para main depende dos testes; patch automático, minor/
major por incremento da base. Alterações nesta branch só afetam main depois de
integradas. Inventário de perfis, API, RAG e roteamento não são implementados por
este atualizador e continuam no plano, sem falsa alegação de entrega completa.

## Redesenho 0.5

Conexões primeiro, com abertura nativa de perfil Chrome já existente e permissão
separada; API, atividade e manutenção em áreas próprias. Fontes locais, teclado,
contraste e capturas desktop/375px: [revisão com evidências](docs/design/UI_050_REVIEW.md).
Abertura normal de perfil não implica conta verificada nem autorização CDP.
