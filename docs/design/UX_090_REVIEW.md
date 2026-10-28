# Revisão 0.9 — mapeamento guiado

Contrato: [UX_090_SPEC.md](UX_090_SPEC.md). Estilo Ledger preservado; o trabalho é
de fluxo e de captura, não de redesenho visual.

## O que foi inspecionado (leitura de código e execução)

- `picker.js` reescrito: objetivo, passo, dica, prévia do texto, contagem de
  casamentos, camadas, pular e cancelar. Sem `innerHTML` — tudo por `textContent`.
- `chat_probe.js`: `messageContainerOf` e `wholeMessageHtmlOf` (clone descartável,
  DOM real intacto), com remoção de moldura no clone.
- `chat.py`: captura do balão inteiro por elemento casado, ignorando nós aninhados
  e caindo para `inner_html` quando o probe não está no frame.
- `setup.py`: passos numerados, microfone opcional e explicado, pulo por campo,
  prévia “Capturado (…)” no log, refazer no fim.
- `panel.js/html/css`: linha do passo, pontos de progresso e ajuda por pergunta.

## Verificação executada

```text
Núcleo local (sem Chromium neste ambiente): 310 testes, 18 ignorados, OK
jsdom (fora do repositório, /tmp/pickercheck2): 22 checagens, TODAS PASSARAM
```

As checagens em jsdom usam a própria `fixtures/gemini_like.html` com o DOM do
relato e confirmam: subir do `<span>` ao `model-response`, capturar os dois
`<span>` e o segundo parágrafo, remover “Copiar/👍/👎” e o rótulo `assistente`,
mostrar “Vai capturar …” e o passo, aceitar .ql-editor e o botão Enviar, recusar
clique em botão comum, pular com Esc e abortar com o botão explícito.

## Riscos e limites

- **Ainda não rodou em Chromium real**: os testes de navegador deste marco
  (`tests/test_mapping_browser.py`) entram no workflow `lab`; até a leitura do log,
  o comportamento em layout real está verificado só por jsdom.
- A heurística de balão depende de marcadores de papel. Sites que só usam `div`
  com classes genéricas podem cair na camada genérica; nesse caso a prévia mostra
  o texto e o usuário pode escolher “Camada maior”.
- Em iframe o balão não é expandido: a leitura fica no elemento casado.
- A prévia lê texto de uma mensagem existente; não promete que a próxima resposta
  terá o mesmo formato.
- Gemini/Arena autenticados e Chrome pessoal continuam **não homologados**.
