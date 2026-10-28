# Revisão 0.8 — correções do uso real e Atividade gráfica

Contrato: [UX_080_SPEC.md](UX_080_SPEC.md). Mantém o estilo Ledger (Inter 450,
8pt, 44px de botão) e os tokens de cor existentes.

## Incidente encontrado durante o trabalho

Na 0.7.0, uma edição minha no `panel.html` removeu a aspa de fechamento de
`id="view-activity"`. O parser do navegador absorvia o resto dos atributos no id e
a aba Atividade podia não abrir. Corrigido e coberto por
`test_panel_html_is_valid_and_every_view_is_reachable`, que valida por parser:
tags balanceadas, nenhum valor de atributo começando com aspas, quatro `view-*`
presentes e cada view referenciada no JavaScript. O caso não apareceu nos testes
anteriores porque nenhum deles abria a aba Atividade.

## O que foi inspecionado

- **Configurações**: três cartões (Componentes, Atualização automática, Sobre) com
  uma linha de estado cada; texto longo dentro de “O que este programa não faz”.
- **Sua próxima ação**: pergunta + uma linha de ajuda contextual; botões Sim/Não/
  Continuar; “Detalhes da operação” recolhido.
- **Meus chats**: `Testar agora`, `Corrigir campos`, `Excluir` visíveis; ações de
  voz/Enviar/Chrome em “Ajustar ou excluir”.
- **Atividade**: seis gráficos em cartões; rosca ocupa duas colunas no desktop e
  uma no celular; legendas em texto ao lado dos gráficos.
- **Cores dos gráficos**: verde `#146c50` (sucesso), âmbar `#a3712f` (não confirmado/
  limite), azul-acinzentado `#3f6f9a` (login/consumo enviado), cinza `#8a9a91`
  (sem autorização), marrom `#7a6f5f` (erro de operação). Todo gráfico tem legenda
  ou rótulo numérico — cor não é o único canal.

## Verificação executada

- Núcleo local, sem Chromium neste ambiente: **302 testes, 17 ignorados, OK**
  (`BROWSERAPI_SKIP_BROWSER=1`).
- Novos testes sem navegador:
  - confirmação real (`test_sender.TestEvidenciaReal`, 7 casos): NBSP/invisíveis,
    reuso de nó, campo esvaziado, contraprova de texto divergente;
  - `test_guided_pointing_questions_say_which_element_to_click`;
  - `test_delete_is_visible_and_asks_with_the_connection_name`;
  - `test_activity_is_graphical_and_usage_is_measured_not_invented`;
  - `test_panel_html_is_valid_and_every_view_is_reachable`;
  - telemetria de consumo (`test_usage_*`), inclusive par inválido descartado.
- DOM emulado (jsdom, fora do produto): 33 checagens aprovadas — conversa,
  exclusão visível com nome na confirmação, seis gráficos renderizados, legenda,
  `aria-label`, “Não medido” nos tokens, ausência de tabela, configurações.
- Testes de navegador novos/atualizados (a executar no workflow `lab`):
  reescrita de texto + atraso de renderização confirmando envio; contraprova de
  texto divergente com campo preenchido; capturas `activity-desktop.png`,
  `activity-usage-desktop.png` e `activity-usage-mobile.png`.

## Pendências e riscos

- **Não houve captura em Chromium real nesta rodada** (ambiente sem navegador). As
  imagens da aba Atividade serão geradas pelo workflow de navegador; até a leitura
  delas, o desenho dos gráficos está verificado só em DOM emulado, sem layout real.
- A confirmação mais permissiva (`campo esvaziado + balão novo`) precisa ser
  observada no seu Gemini/Arena para sabermos se reduz o falso negativo na prática.
- Estimativa de tokens é grosseira; o número real do provedor continua indisponível.
- Não há gráficos de CPU/RAM/tráfego: essas métricas não são coletadas nesta versão.

## Primeira rodada de CI desta versão (40620094973) — três achados, todos tratados

1. **Meu teste, não o produto:** a contraprova `test_texto_divergente_sem_campo_
   esvaziado_nao_vira_sucesso` esperava falha, mas o fixture esvazia o campo — o
   caminho “balão novo + campo esvaziado” confirma por projeto. O teste foi dividido
   em dois: um documenta essa regra mais permissiva (com evidência declarada no
   recibo) e outro usa uma contraprova determinística (clique em Enviar
   interceptado: nada é publicado, o campo mantém o texto). A versão intermediária,
   que tentava devolver o rascunho por `setTimeout`, foi descartada por depender do
   timing do fixture.
2. **Flake pré-existente, não relacionado:** `test_same_origin_tab_in_another_browser_
   context_is_never_used` falhou porque o Chrome descartável cria
   `DevToolsActivePort` vazio/parcial antes das duas linhas válidas; o helper do
   teste esperava só o arquivo existir. Agora ele espera o endpoint ficar legível.
   Sem mudança no produto: a leitura estrita de produção continua igual.
3. **Falha silenciosa no teste da conversa** (`#conversation .turn` = 0): o teste
   esperava 5 s por um turno sem dizer por quê. Agora consulta a conversa do painel
   (fonte de verdade de `ask`, que não grava recibo de compatibilidade) e mostra o
   log e as últimas mensagens na falha. A primeira tentativa usou
   `store.status('saved')` — errado por contrato: `ask` não produz recibo, e o teste
   acusou `None` em vez do turno. Corrigido para ler `panel.transcript`.

Nenhum desses pontos foi convertido em prazo maior, reenvio automático ou teste
mais frouxo no produto.

## Corrida encontrada no produto (não só no teste), na 3ª rodada

A execução 40621633923 falhou em `test_persistent_history_requires_opt_in_and_
conversation_id` com “Aguarde a tarefa antes de apagar/revogar”, **sem tarefa em
andamento**. Causa: em `llm_api.do_POST`, o contador `service.active` só caía no
`finally`, depois de escrever a resposta no socket. Quem pedia *apagar histórico*
ou *revogar chave* imediatamente após receber a resposta era recusado.

Corrigido no produto: a chamada é liberada assim que o worker termina de produzir a
resposta (antes de `send_json`/SSE), inclusive nos caminhos de erro. Novo teste
`test_clear_history_right_after_a_response_is_not_rejected_as_busy` cobre o caso
sem nenhuma espera. O limite de 4 chamadas simultâneas continua igual; o que muda é
que a escrita do socket deixou de contar como trabalho do navegador.

