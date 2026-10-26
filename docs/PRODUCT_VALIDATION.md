# Estado das seis metas de produto

Data: 2026-10-24. Critérios originais: [PRODUCT_GOALS.md](PRODUCT_GOALS.md).
Guia operacional: [CHAT_GUIDE.md](CHAT_GUIDE.md).

## Regra central

Uma função implementada não é o mesmo que compatibilidade comprovada com um site
real. Não responderemos SIM às seis perguntas enquanto faltarem evidências. Este
marco entrega o caminho assistido de configuração, checagem e reparo, sem inventar
homologação externa.

## O que foi entregue

- Escolha de navegador e chat, com configurações independentes e perfil dedicado.
- Comandos `configure`, `check`, `status`, `repair`, `ask` e `chats`.
- Login, CAPTCHA e escolha do modelo exclusivamente manuais.
- Apontamento visual do campo, envio, mensagem do usuário e resposta; sem console,
  JavaScript manual ou edição de CSS pelo usuário.
- Teste de uma mensagem somente após consentimento explícito.
- Desafio JSON com identificador aleatório, comparação de saídas novas e rejeição
  de respostas antigas, formato incorreto ou saídas ambíguas.
- Mensagens em português que explicam falha e ação sugerida.
- Recibo sanitizado de compatibilidade com data, navegador/versão e latências;
  mudança de configuração invalida o recibo anterior.
- Desempenho separado da compatibilidade: orçamento de captura de 900 ms; equivalência
  a API permanece `not_measured` quando não foi comparada de verdade.
- Mutação em relógios/sidebars fora da resposta não atrasa a conclusão.
- Seleção de conteúdo de mensagem com escopo de autor para não confundir usuário,
  resposta, rótulos e controles.

## Painel de metas

| Pergunta | Estado comprovado neste marco | Gate ainda aberto |
|---|---|---|
| Usa meu navegador? | Chrome/Chromium instalados/gerenciados exercitados no CI; escolha de Edge/binário Chromium implementada | Homologar Edge/binários específicos e a máquina do usuário; não há suporte anunciado a Firefox/Safari nem importação de perfil pessoal |
| Posso escolher o chat? | Menu Gemini/LMArena/URL própria; salvar/listar vários chats e perfis separados | Executar Gemini e LMArena autenticados; URLs/seletores conhecidos são hipóteses |
| Avisa se conseguiu? | Fluxo completo de desafio/recibo testado em chat controlado; não aceita só campo apagado ou resposta velha | Comprovar resposta nova nos sites reais e repetir após mudanças de DOM |
| Consigo corrigir? | Reparo por apontamento e regressões de campo quebrado testados; falhas têm ação concreta; não há retry cego | Testar reparo em DOMs reais; closed Shadow DOM, virtualização e bloqueios do site podem exigir adaptação |
| É próximo de API? | Overhead do novo check medido em dez desafios locais, separado do tempo do modelo | Comparação com API real equivalente autorizada e P95 no chat real; sem acesso não há como afirmar equivalência |
| É simples? | Assistente em cinco etapas, comandos documentados e execução da CLI em janela real de display virtual | Avaliação humana de usabilidade no laptop e primeira configuração real |

## Evidência final deste marco

[Execução 40150600028](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40150600028):

```text
Ran 232 tests in 102.441s
OK (skipped=1)
```

O teste ignorado verifica ausência de navegador, situação que não se aplica ao
runner. As classes de integração exigem navegador real e falham caso indisponível.

Novo caminho `exchange(..., health_check=True)` na mesma conversa, configuração
padrão de estabilidade de 1200 ms:

| Métrica, n=10 | Resultado local controlado |
|---|---:|
| Falhas | 0 |
| Tempo total, mediana | 818,8 ms |
| Tempo total, P95 | 932,7 ms |
| Overhead de captura, P95 | 497,1 ms |
| Orçamento de captura | 900 ms |

Dados: `results/ci/40150600028/product-flow.json`.
Esses números usam uma **resposta sintética curta**, não latência de modelos reais.
São diferentes do benchmark Markdown longo do laboratório. Os tempos do novo
check começam após autorização e não incluem login, seleção manual ou startup.

## Testes adicionais da jornada

- Configuração completa com perguntas/seleções simuladas e navegador real.
- Apontamento visual com interceptação de clique e limpeza da faixa de seleção.
- Rascunho preenchido não é sobrescrito.
- Ausência de autorização e origem diferente não enviam mensagem.
- Mensagem antiga não faz uma resposta vazia passar no teste.
- Campo quebrado → diagnóstico → reparo → resposta validada.
- Login, rate limit e erro simulados retornam diagnóstico e ação.
- CLI `check` e `status` invocados como processos reais sob Xvfb; negar consentimento
  retorna um recibo de não envio.
- Configuração alterada invalida status; recibo não contém prompt, resposta,
  seletores ou URL privada.
- Campos de usuário/assistente usam seletores independentes do fixture original.

A regressão final aponta no navegador tanto a mensagem do usuário como a resposta
do assistente, salva os seletores gerados e executa outro desafio com sucesso.
Também preenche um rascunho antes de apontar Enviar, verificando que o clique de
seleção não dispara envio. Ambos os jobs da rodada final foram aprovados.

Código testado: `0b8bf21`. As alterações posteriores deste fechamento são documentação.
O CI também repetiu os 113 experimentos do laboratório nos três modos de navegador,
instalação fora do checkout e execução headed em display virtual.

## Pendências externas e limites

- O CI não usa contas reais, cookies de usuário ou perfis pessoais.
- Compatibilidade com Gemini/LMArena permanece **não homologada** até teste assistido.
- Não há API OpenAI-compatible, serviço de agentes 24/7 nem fila neste marco.
- A CLI atual abre/fecha o navegador em cada invocação; a sessão em disco persiste,
  mas isso não equivale a manter uma página quente entre comandos.
- Não há comparação com API de modelo real; nenhuma promessa desse tipo foi validada.
- O novo assistente usa seletores do documento principal. Cross-origin, Shadow DOM
  e mensagens virtualizadas/reutilizadas podem exigir adaptadores específicos.
- Páginas que bloqueiam automação não serão contornadas. Reparo não garante que
  toda restrição técnica ou de acesso seja resolvível.

## Próximo gate para fechar as metas

Em ambiente com navegador visível do usuário: configurar um chat, aguardar login
e seleção manual do modelo, autorizar uma mensagem, conferir o recibo sanitizado,
validar reparo e repetir medições. Sem essa etapa, trocar os estados acima por
"SIM em chats reais" seria uma afirmação sem prova.


## Complemento: janela Ubuntu / Linux Lite 7.2

O usuário não conseguia usar o fluxo de terminal. Foi acrescentado um painel
local com formulário e botões, worker único, confirmação explícita de envio,
reparo por apontamento e instalador `.deb` com entrada no menu. Isso substitui
a orientação de uso por comandos, não as limitações externas anteriores.

Validação do código `7020ea3`: [Actions 40153757793](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40153757793),
**SUCCESS, 244 testes em 127,108 s, 1 ignorado**, Ubuntu 24.04; evidência `b013f0d`.
Jornada gráfica completa e consentimento testados com Chromium real e chat
sintético. A montagem/extração do `.deb` e a simulação de dependências passaram.
Não houve instalação num desktop Linux Lite, nem login em site real.
Veja [instruções sem terminal e limites do instalador](UBUNTU.md).


## Correção após relato de uso real — versão 0.1.0+ubuntu2

O usuário reportou recusa do login Google no navegador controlado e falha de
reconhecimento de Enviar mesmo após apontamento. O bloqueio do Google continua
sem solução garantida: o programa apenas reconhece o aviso conhecido e impede
continuar a configuração nesse estado. Nenhum mecanismo de autenticação ou
proteção foi contornado.

Foi corrigido um defeito reproduzível: exigir Enviar visível antes de preencher.
Agora, após autorização, preenche e só ativa um botão único, visível e habilitado,
com espera limitada. Se falhar, não ativa nem reenvia e informa possível rascunho.
Isso não demonstra que essa era a única causa do erro no Gemini do usuário.

Validação: [Actions 40156336579](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40156336579),
**SUCCESS, 248 testes em 120,867 s, 1 ignorado**, código `9a59cf6`. Inclui botão
oculto/ausente até digitar, ambiguidade sem envio, rascunho preservado e recusa
Google em página sintética UTF-8 antes do apontamento. O código de execução do
instalador publicado é idêntico ao desse commit; mudanças seguintes só adicionam
documentação, evidências e teste de aviso em inglês (não incluído nessa bateria
completa). Montagem/extração do pacote e simulação de dependências aprovadas.
Não houve novo login autenticado no Google nem execução no computador do usuário.


## Dois estados do controle e perfil pessoal consentido — ubuntu3

O usuário confirmou que deseja seu perfil pessoal, revisando a regra anterior
de usar exclusivamente perfil separado. Foi implementada conexão opt-in ao
Chrome já aberto por CDP com o fluxo de permissão nativo, sem lançar outro
processo no diretório pessoal, copiar cookies ou usar Node/MCP/extensão.
A permissão é ampla sobre as abas/contas e exige aviso explícito.

O apontamento gráfico agora oferece rascunho temporário autorizado para expor
o estado Enviar. Indícios explícitos de microfone impedem seleção/ativação.
Limites e instruções estão no [guia Ubuntu](UBUNTU.md).


### Evidência da versão ubuntu3

[Actions 40157983637](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40157983637), código `8b11752`: **SUCCESS, 257 testes em 124,149 s, 1 ignorado**.

Exercitados com navegador real e fixture: controle que muda de microfone para
Enviar, recusa de clique em microfone, apontamento real que rejeita voz, rascunho
temporário (consentido/negado/cancelado), preservação de rascunho anterior e de
edições, conexão CDP a um processo já aberto, reconexão sem recarregar a página,
não fechamento do processo/abas e recusa de múltiplas abas do mesmo chat.
O navegador CDP desse teste é um Chromium temporário controlado, não um perfil
pessoal real. O diálogo nativo de permissão do Chrome pessoal, disponibilização
do endpoint em cada versão e a sessão Google do usuário **não foram homologados**.
Também passaram testes de autorização negada antes de conectar, validação de
endpoint local/UID/symlink e montagem/extração do `.deb` com simulação de
dependências Ubuntu 24.04. O pacote publicado contém o mesmo código de execução
do commit validado; mudanças posteriores desta publicação são documentação e
artefato de instalação.


## Relato de visitante e apontamento voz → Enviar — ubuntu4

O usuário informou que a conexão não chegou ao Chrome sincronizado e pediu
botões independentes para ensinar o controle de voz e, depois de digitar, o
controle Enviar. A GUI foi alterada para esse fluxo manual. A mudança de sessão
para um chat já salvo agora é explícita e consentida; o modo CDP não cria aba
na ausência de uma aba correspondente já aberta. Isso fecha caminhos internos
de confusão/fallback, sem deduzir identidade de conta a partir de cookies.


### Validação da versão ubuntu4

Código `670bd10`, [Actions 40205878425](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40205878425): **SUCCESS, 262 testes em 117,706 s, 1 ignorado**.
Navegador real com fixture: seleção de voz, digitação humana simulada, bloqueio
de clique/Enter durante o ensino, seleção posterior de Enviar sem envio,
preservação do rascunho e envio autorizado posterior. Estado de voz sem rótulo
reconhecido é bloqueado; cancelamento limpa a proteção sem apagar o texto.
Também foram exercitados os botões reais do painel, troca consentida do modo
de chat salvo sem abrir navegador, recusa de aba inexistente sem criar outra e
reuso de aba já aberta sem recarregá-la/fechar o processo CDP.
O teste CDP usa um Chromium temporário, não o Chrome sincronizado do usuário.
O relato de visitante não foi reproduzido no computador real; não se afirma
identificação/correção universal de perfil pessoal, login Google ou contexto
que cada versão do Chrome expõe. O `.deb` passou montagem/extração e simulação
de dependências. Nesta publicação o código do pacote é o mesmo que passou a
CI; as mudanças posteriores são documentação e instalador gerado.


## Pergunta de voz no assistente completo e erros de console — ubuntu5

O relato do usuário levou à remoção do salto da revisão na GUI, à pergunta de
presença de voz no campo vazio e ao ensino obrigatório de Enviar após digitação
humana. Corrigiram-se regex HTML moderna e favicon, adicionaram-se mensagens
seguras de validação e diagnóstico de versões do painel/runtime, sem afrouxar
autenticação das APIs nem remover 400 de pedidos inválidos.


### Evidência ubuntu5

[Actions 40207783784](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40207783784), código `0f2de45`: **SUCCESS, 267 testes em 138,647 s, 1 ignorado**.

O teste de GUI da configuração percorreu presença de voz **Sim**, seleção do
microfone, digitação simulada pela pessoa e seleção de Enviar antes da
autorização de uma mensagem. O teste de **Corrigir campos** percorreu presença
**Não**, remoção de estado de voz antigo, digitação e seleção de Enviar, sem
enviar mensagem. São janelas/navegadores reais com fixture local e interações
sintéticas; não uma sessão autenticada do Gemini.

Passaram também validação HTML de nomes válidos/inválidos no Chromium moderno,
console sem erro de regex/favicons na carga válida, resposta pública vazia do
favicon com proteção de Host, mensagens controladas dos 400, bloqueio de ações
quando o runtime é antigo e pacote montado/extraído com simulação de dependências.

A primeira execução, [40207331990](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40207331990), passou pelos novos testes de GUI,
mas falhou em timeout de um teste legado de CLI. A causa desse timeout não foi
identificada. Não se aumentou o prazo de produção/teste nem se inseriu reenvio;
acrescentaram-se verificações do cenário curto da fixture CLI e a bateria
completa foi executada novamente, com o resultado aprovado acima. Isso não
prova ausência universal de instabilidade.

O instalador publicado contém o mesmo código de execução validado. As alterações
seguintes são documentação e o `.deb` gerado. A escolha do perfil pessoal e o
Google real permanecem fora desta homologação.


## Marco M1 — métricas e dashboard, 0.2.0+ubuntu1

Escolha delegada pelo usuário em 2026-10-25: medir gargalos antes de otimizar.
Implementação `5e2c52e`, distribuição `28dadb1515c429adbc961d84aeff08cdd704efff`.
[Actions 40262196504](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40262196504)
**SUCCESS**: **279 testes em 143,910 s, 1 ignorado** (teste que exige ausência de
navegador; este ambiente tinha navegador). Evidências em
[`results/ci/40262196504/`](../results/ci/40262196504/), commit `f81de60`.
Local: **190 testes em 17,357 s, 16 ignorados**, incluindo suites dependentes de
navegador indisponível localmente; não tratados como testes gráficos executados.

Validação nova:
- Janela limitada, média/P95 e denominadores, tokens desconhecidos, latência
  ausente não convertida em zero, cancelamento/negação/erro separados.
- Lista branca de conteúdo, números inválidos/imensos descartados, snapshot
  independente e leituras concorrentes com limite respeitado.
- Worker termina métricas e estado atomicamente: próxima tarefa não pode apagar
  recibo anterior; doctor sem resultado não repete sucesso antigo. Mock de envio
  chamado uma vez; erro anterior ao recibo não expõe exceção nem vira sucesso.
- Chromium real: sucesso com fases sequenciais dentro de total_ms; rascunho
  privado causa falha medida antes do envio, sem fases de resposta inventadas.
- GUI real: configuração autorizada → dashboard com 1 resultado, 100%, Online
  observado, tokens indisponíveis e 1 barra → nova verificação autorizada → 2
  resultados/2 barras. Tempos de browser/aba presentes. Mantidos os testes de voz,
  Enviar, console, consentimento e versão do runtime.
- Jobs completos: pacote construído e dependências simuladas no Ubuntu 24.04;
  biblioteca instalada fora do checkout; verify em Chromium, Chrome e modo com
  janela sob Xvfb. Não equivale à instalação gráfica num Linux Lite pessoal.

O `.deb` publicado foi extraído e todos os módulos/assets comparados byte a byte
com o código validado. Versão interna `0.2.0+ubuntu1`, checksum em
`downloads/SHA256SUMS`. Não exige terminal do usuário.

**Limites:** testes usam fixture local, não autenticação Gemini/LMArena nem Chrome
pessoal sincronizado. Não se demonstra aceleração por este marco; ele fornece as
medições para comparações futuras. A execução Gemini em 9838 ms foi relatada pelo
usuário em perfil separado, não repetida pelo assistente. Tokens, CPU/RAM/tráfego,
API OpenAI, inventário de perfis, atualizador, contexto/RAG e failover não estão
implementados. Nenhum bloqueio de recursos ou Fetch/XHR foi ativado. Plano e gates:
[NEXT_ARCHITECTURE.md](NEXT_ARCHITECTURE.md).


## Atualização automática — 0.3.1

- Código do atualizador em `a6dcc75`, recuperação/CSP em `dfed84a`, preservação
  do runtime privado em `d8bd409`.
- [CI branch 40266147199](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40266147199):
  **SUCCESS, 294 testes em 145,075 s, 1 ignorado**; instalado fora do checkout e
  janela sob Xvfb aprovados. [PR 40266160123](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40266160123)
  também aprovado. Local: **204 testes em 15,168 s, 16 ignorados** (sem browser).
- [Primeira publicação em main 40265527657](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40265527657):
  SUCCESS, incluindo job de release. Publicou `v0.3.0`, commit de release
  `56b77e0f2909cf5f950bfc39753dc606b2320fe3`, após os testes. Download público
  sem token, resolução de tag/commit, hash, identidade e extração do runtime
  verificados de fato via o cliente do aplicativo (96883 bytes).
- Provas locais completas em [local-updater-20261026](../results/ci/local-updater-20261026/):
  supervisor real e dois processos GUI, atualização 0.3.0 → 0.3.1, mesma porta e
  token, troca ociosa, confirmação após 30 segundos e zero mensagens de chat.
  Segunda prova usa o supervisor da release pública 0.3.0 e cria uma venv após
  sua abertura; worker atualizado importa um módulo de teste disponível somente
  nessa venv. Não é apenas mock de Popen ou comparação de versão.
- Testes unitários cobrem desativação persistida, pending não ativado após opt-out,
  offline, hash/ABI inválidos, traversal/symlink, assets completos, rollback após
  falha inicial, rejeição de versão defeituosa, staging interrompido, preferências
  inválidas fail-closed, roteamento HTTP autenticado e bloqueio durante atualização.
- GUI Chromium confirma recarga automática e manutenção da autorização. Sem
  unsafe-eval, mudança de CSP ou reenvio. Estado ocioso validado com servidor real.

Histórico de falhas preservado: 40263812348 detectou eval sob CSP no teste de
navegação (corrigido com locator assertion); 40264132751 encontrou ENOTEMPTY na
limpeza de Chromium descartável (encerramento gracioso somente no teste). O PR
40264516455 também falhou; seus logs não puderam ser obtidos pela rota disponível,
portanto a causa não é afirmada como diagnosticada. Acrescentou-se diagnóstico
legível para PRs de origem confiável, e baterias completas posteriores passaram.
Não se aumentou timeout de produção nem se adicionou retry de mensagem. Os
resultados não demonstram estabilidade universal ou no computador do usuário.

Confiança e limites: [UPDATES.md](UPDATES.md). Código/GUI ABI 1 se atualiza; sistema,
Chrome, dependências incompatíveis e supervisor não são substituídos silenciosamente.
Métricas em memória zeram com a troca de processo. Perfil pessoal/Google real,
API de LLM, RAG/contexto, otimização de recursos e fallback continuam sem nova
homologação/implementação por este marco; não são anunciados como entregues.
