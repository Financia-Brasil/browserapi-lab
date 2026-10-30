# Colar em vez de digitar, e nunca enviar mensagem pela metade

Documento da **0.13.1**. Responde a três queixas do relato:

> *“ele fica escrevendo caractere por caractere em vez de colar como ele fez no
> do Arena”* · *“pra ele ser rápido em qualquer chat”* · *“ele manda a mensagem
> incompleta, e eu não sei se é porque ele demora pra colar a resposta completa”*

## 1. O que estava errado

O envio escolhia a estratégia pelo tipo de campo:

```python
strategies=('type_contenteditable',) if contenteditable else ('fill',)
```

Em campo rico (Gemini, Claude web, ChatGPT, LM Arena) isso é
`press_sequentially`: **uma tecla por vez**, uma ida ao navegador por caractere.
Um pedido de 20 mil caracteres viravam dezenas de segundos — e, no meio do
caminho, o editor descarta ou reagrupa eventos: o texto chega **incompleto**.
Como o site costuma reformatar o balão, a confirmação aceitava “mensagem nova +
campo esvaziado” mesmo quando só um pedaço tinha entrado. Resultado: o site
recebia meia pergunta e a API respondia como se estivesse tudo certo.

## 2. O que passa a acontecer

**Ordem por tipo de campo** (`sender.STRATEGIES_BY_KIND`):

| Campo | Ordem | Por quê |
|---|---|---|
| `textarea` / `input` | `fill` → `paste` → `exec_insert` → `js_set` → `type` | `fill` é nativo e instantâneo |
| `contenteditable` | `paste` → `paste_event` → `exec_insert` → `fill` → `js_set` → `type_contenteditable` | colar é um único evento; digitar fica por último |

- **`paste`** usa `keyboard.insert_text`: um único `Input.insertText`, o mesmo
  evento que um Ctrl+V produz. Editores ricos (ProseMirror, Lexical, Slate,
  Quill) tratam; o custo é **uma** ida ao navegador, não N.
- **`paste_event`** dispara `ClipboardEvent('paste')` com `DataTransfer` — para
  editor que só reage a colagem de verdade.
- **`exec_insert`** usa `document.execCommand('insertText')` / `setRangeText`.
- **`js_set`** (define valor + `input`) e **`type*`** (teclado real) ficam como
  último recurso. Digitação é **recusada acima de 4.000 caracteres**
  (`MAX_TYPE_CHARS`): melhor falhar explicando do que mandar pela metade.

**Conferência antes do clique.** Depois de colocar o texto, o envio lê o campo e
compara **normalizado** (espaços, NBSP, invisíveis) com o que deveria estar lá:

- igual (ou com até 8 caracteres a mais, tipo quebra no fim) → **clica em Enviar**;
- faltando texto → **não clica**, limpa, tenta o próximo caminho;
- nenhum caminho aceitou tudo → `composer_incomplete`, com *“o campo recebeu X de
  Y caracteres”*. Nada foi enviado, então repetir é seguro (HTTP 503).

**Confirmação honesta.** A regra antiga “mensagem nova + campo esvaziado” agora
recusa um balão que seja só um **prefixo** do texto enviado (corte evidente). O
resultado é `send_truncated` — não sucesso, não reenvio (HTTP 409), com instrução
para olhar a conversa.

**Resposta completa.** O fim da geração já exigia três leituras estáveis e o
botão Stop ausente; agora há uma **janela de confirmação** (`confirm_window_ms`,
900 ms no fluxo normal): se o texto voltar a crescer — pausa do modelo, segundo
parágrafo atrasado, ferramenta renderizando — a espera continua em vez de
entregar a resposta pela metade.

## 3. Pré-registro e resultado esperado

| # | Hipótese | Como seria falsificada |
|---|---|---|
| P1 | colar é O(1): um texto de ~20 mil caracteres entra muito abaixo de 1,5 s | se `fill_ms` passar de 1,5 s no Chromium do CI |
| P2 | a mensagem publicada tem o mesmo tamanho do texto enviado | se o balão do usuário sair menor |
| P3 | campo que corta a colagem cai para o próximo caminho e ainda envia inteiro | se ficar em `composer_incomplete` havendo caminho que aceite |
| P4 | nenhum caminho aceitando tudo ⇒ zero cliques em Enviar | se o site receber mensagem parcial |
| P5 | balão publicado pela metade não conta como sucesso | se `evidence_of_send` confirmar prefixo curto |

## 4. Como isso é provado

- `tests/test_sender.py` — campo falso que corta cada caminho, mede cliques e
  teclas: colar ganha, digitar não é usado em texto grande, nada é enviado se
  faltar texto, balão cortado não confirma.
- `tests/test_resilience_browser.py::TestColagemRapida` — **Chromium real**:
  ~19 mil caracteres em `contenteditable` e em `textarea`; exige `fill_ms` abaixo
  de 1,5 s e o balão publicado com o **mesmo tamanho** do texto enviado.
- `tests/test_observer.py` — a janela de confirmação: quando o texto volta a
  crescer depois da estabilidade, a espera continua e a resposta termina maior.

## 5. O que continua não sendo prometido

- site que reescreve o texto no campo (autocorreção, menções) pode ser recusado
  pela conferência — é de propósito: recusar é melhor que enviar torto;
- `send_truncated` não conserta a mensagem já publicada; ele só **avisa**;
- a janela de confirmação aumenta a espera em ~0,9 s por resposta: é o preço de
  não cortar resposta pela metade.
