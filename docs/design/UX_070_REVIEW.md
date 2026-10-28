# Revisão 0.7 — conversa no painel

Contrato: [UX_070_SPEC.md](UX_070_SPEC.md). Base visual: estilo Ledger da 0.5/0.6,
sem fonte, cor ou espaçador novo.

## O que foi inspecionado

- Cartão **Conversa** como terceiro item do `connection-layout`: fica na coluna
  direita, abaixo de **Meus chats**; em telas até 640px volta a uma coluna
  (`grid-column:auto`), sem rolagem horizontal.
- Turnos com rótulo textual (“Você enviou” / “Resposta capturada da página”),
  data/hora e milissegundos em fonte monoespaçada de dados. O número é complemento,
  não a única indicação: o texto do rótulo diz o que é cada bloco.
- Botões com altura mínima de 44px, **Copiar última resposta** secundário e
  **Limpar painel** como ação de texto; ambos desabilitados sem conteúdo ou durante
  tarefa/versão incompatível.
- Lista com `max-height` e rolagem própria, para uma resposta longa não empurrar
  o resto da página.
- Estados: sem conexão (cartão oculto), sem mensagens (frase de vazio), carregando,
  com turnos e após limpar.

Cores: o cartão reaproveita `--ink`, `--muted`, `--line`, `--accent` e o fundo
`#f4f8f5` já usado pelos recibos. Não há par de cor novo; a medição de contraste
da 0.6 para esses tokens continua sendo a referência documentada.

## Verificação executada neste marco

- Núcleo Python: **289 testes, 17 ignorados, OK** (`BROWSERAPI_SKIP_BROWSER=1`).
  Sem navegador neste ambiente, as classes de integração são ignoradas com motivo.
- Contrato estático no teste `test_conversation_ui_contract_renders_text_only`:
  identificadores do cartão, ausência de `innerHTML`/`insertAdjacentHTML` no
  `panel.js`, render por `textContent`, endpoint de conversa, bloqueio por versão
  incompatível e as regras responsivas do CSS.
- DOM emulado (jsdom, fora do produto e não versionado) com `fetch` simulado:
  21 checagens aprovadas — dois turnos renderizados, HTML da resposta aparece
  como texto, `onerror` não executa, milissegundos exibidos, cópia envia o texto
  completo, troca de conexão recarrega, estado vazio, limpar chama o endpoint e
  apaga a exibição, aviso de “nada foi enviado”.
- Não houve captura em Chromium real desta jornada neste ambiente. Os testes de
  navegador novos (`test_ask_shows_the_new_answer_in_the_panel_conversation`,
  `test_conversation_text_is_not_executable_and_clear_keeps_the_site`) gravam
  `results/ci/ui-redesign/conversation-*.png` quando o workflow de navegador os
  executar. Até lá, captura e leitura humana continuam **pendentes**.

## Riscos e limites assumidos

- O texto só aparece ao fim da resposta validada; não há eco parcial durante o
  streaming. Isso evita mostrar resposta antiga como se fosse nova.
- O DOM emulado verifica a lógica de renderização, não layout real, foco por
  teclado nem leitor de tela. Avaliação humana de usabilidade continua aberta.
- Respostas muito longas são cortadas em 40 mil caracteres com aviso no próprio
  texto; a página permanece com o conteúdo completo.
- Limpar a conversa do painel não limpa o site, e o texto continua na memória até
  a próxima limpeza, o fechamento do programa ou a exclusão da conexão.
