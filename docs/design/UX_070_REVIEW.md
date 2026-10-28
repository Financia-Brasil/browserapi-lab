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

**Navegador real (CI, 2026-10-28).** Execução `lab` [40609553859](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40609553859)
e PR [40609557720](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40609557720), ambos **SUCCESS**:

```text
Integração real com Chromium: Ran 394 tests in 213,268s — OK (skipped=1)
Revisão visual:              Ran  16 tests in  35,958s — OK
Núcleo Python (sem navegador): aprovado
```

- Capturas em Chromium real (fixture local, sem conta): [desktop 1440px](../../results/ci/ui-review-40609553859/ui-redesign/conversation-desktop.png)
  e [375px](../../results/ci/ui-review-40609553859/ui-redesign/conversation-mobile.png).
  Inspecionadas: cartão abaixo de **Meus chats**, turnos com data/hora e ms,
  botões, rodapé de escopo; em 375px o cartão volta a uma coluna e
  `document.scrollWidth - innerWidth <= 0`.
- `test_ask_shows_the_new_answer_in_the_panel_conversation`: **Conversar** →
  pergunta → resposta aparecem na conversa, o log de operação não repete o texto
  e o turno salvo tem tempo medido.
- `test_conversation_text_is_not_executable_and_clear_keeps_the_site`: `<img
  onerror>` aparece como texto, nada executa, cancelar a confirmação mantém a
  conversa e confirmar limpa só a exibição, mantendo o cadastro.
- Correção encontrada pela própria CI: a primeira execução ([40608925770](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40608925770))
  falhou num assert do teste, não no produto — o fixture em modo contrato responde
  JSON a qualquer mensagem, então a checagem por Markdown era inválida. O painel já
  exibia o texto íntegro; o teste passou a conferir o texto capturado (`browserapi-ok`).
- Núcleo local, sem Chromium neste ambiente: **289 testes, 17 ignorados, OK**
  (`BROWSERAPI_SKIP_BROWSER=1`).
- Contrato estático em `test_conversation_ui_contract_renders_text_only`:
  identificadores do cartão, ausência de `innerHTML`/`insertAdjacentHTML` no
  `panel.js`, render por `textContent`, endpoint de conversa, bloqueio por versão
  incompatível e regras responsivas do CSS.
- DOM emulado (jsdom, fora do produto e não versionado) com `fetch` simulado:
  21 checagens aprovadas — dois turnos, HTML como texto, `onerror` sem execução,
  cópia da resposta completa, troca de conexão, estado vazio, limpar com endpoint
  e aviso de “nada foi enviado”. Complementa a captura; não substitui leitor de
  tela nem avaliação humana.

## Riscos e limites assumidos

- O texto só aparece ao fim da resposta validada; não há eco parcial durante o
  streaming. Isso evita mostrar resposta antiga como se fosse nova.
- A captura confirma layout em Chromium do runner, não leitura humana de
  usabilidade, leitor de tela nem o desktop Linux Lite do usuário. Essa avaliação
  continua **aberta**.
- Respostas muito longas são cortadas em 40 mil caracteres com aviso no próprio
  texto; a página permanece com o conteúdo completo.
- Limpar a conversa do painel não limpa o site, e o texto continua na memória até
  a próxima limpeza, o fechamento do programa ou a exclusão da conexão.
- Gemini/Arena autenticados e Chrome pessoal continuam **não homologados**.
