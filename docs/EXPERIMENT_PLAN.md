# Plano de Experimentos — browserapi-lab

Status: **validação dos Marcos 1–6 em andamento** — documento vivo, atualizado a cada marco.

## 1. Objetivo do laboratório

Descobrir, medir e provar — com evidência observável — como automatizar interfaces web reais de
chats de IA (primeiros alvos: **Gemini** e **LMArena**), para que no futuro exista uma API local
compatível com OpenAI.

Este repositório **não é** o aplicativo final. Não haverá FastAPI, `/v1/chat/completions`, SSE ou
fila neste repositório. O que se produz aqui são **componentes medidos e reutilizáveis**.

## 2. Perguntas que o laboratório precisa responder

As 12 perguntas do briefing, convertidas em experimentos com critério de sucesso mensurável:

| # | Pergunta | Experimento | Critério de sucesso |
|---|----------|-------------|---------------------|
| P1 | Como localizar o campo de mensagem? | E-DISC-1 a E-DISC-5 | Campo correto é o 1º colocado no ranking, nos 3 cenários (DOM comum, open Shadow DOM, iframe) |
| P2 | Como localizar o botão de envio? | E-DISC-2 | Botão correto no top-3 e envio confirmado por nova mensagem do usuário |
| P3 | Como identificar mensagens do usuário e do assistente? | E-DISC-4 / E-OBS-1 | ≥ 95% de acerto na fixture em 10 execuções |
| P4 | Como enviar em `textarea`, `input` e `contenteditable`? | E-SEND-1 a E-SEND-6 | Cada controle tem ≥ 1 estratégia com evidência observável |
| P5 | Como lidar com open Shadow DOM e iframes? | E-DISC-3 / E-DISC-5 | Candidatos internos são encontrados; closed Shadow DOM registrado como limitação |
| P6 | Como observar streaming com `MutationObserver`? | E-OBS-1 / E-OBS-2 | Observador registra ≥ 90% das mutações comparado ao poll de 50 ms |
| P7 | Como detectar o término sem sinal único? | E-OBS-3 a E-OBS-8 | `hybrid` não finaliza antes da pausa artificial e não excede o timeout |
| P8 | Como extrair texto limpo e Markdown? | E-EXT-1 a E-EXT-4 | Código, listas, links e tabela preservados; DOM original intacto |
| P9 | Como preservar login e preferências? | E-SESS-1 a E-SESS-3 | Estado persiste após fechar e reabrir; lock bloqueia segundo processo |
| P10 | Como reutilizar página aberta? | E-SESS-2 | Segunda mensagem reusa a mesma aba sem relogin |
| P11 | Quanto cada estratégia consome? | E-BENCH-1 | RAM/CPU/tempo por estratégia, relatório JSON+CSV |
| P12 | Como diagnosticar mudanças de DOM? | E-DIAG-1 | Diff de candidatos entre execuções com `drift` reportado |

## 3. Ambientes

### 3.1 Ambiente de desenvolvimento/verificação remoto (este sandbox)

Auditado em 2026-10-24 pelo `doctor` (comando: `python -m browserapi_lab.cli doctor`):

| Item | Valor |
|------|-------|
| SO | Debian GNU/Linux 12 (bookworm), kernel 6.1.158 |
| Python | 3.11.2 |
| CPU | 2 vCPU (Intel Xeon 2.60 GHz) |
| RAM | 3,9 GB total |
| Disco | 20 GB livres |
| Playwright | 1.64.1 (instalado em venv) |
| Chromium/Chrome no sistema | **nenhum** |
| Cache de navegadores do Playwright | **vazio** |
| Rede | apenas PyPI, npm, github.com, codeload.github.com |

**Achado crítico (limitação do ambiente, não do projeto):** o sandbox não possui as bibliotecas de
runtime do Chromium (`libnss3`, `libnspr4`, `libatk-1.0`, `libatk-bridge-2.0`, `libatspi`,
`libcups`, `libdrm`, `libgbm`, `libxkbcommon`, `libXcomposite`, `libXdamage`, `libXrandr`,
`libXfixes`, `libpango`, `libcairo`, `libasound`, `libharfbuzz`, `libepoxy`) e não há acesso utilizável aos repositórios `apt`
nem acesso ao CDN do Playwright. Portanto:

* **nenhuma execução de navegador é possível dentro deste sandbox**;
* o núcleo de lógica (pontuação, decisão de término, extração, lock, relatório) é implementado em
  Python puro para ser testado aqui, sem navegador (ver ADR-002);
* a execução real de navegador acontece no **GitHub Actions** (`ubuntu-latest`), que possui
  bibliotecas e pode baixar o Chromium do Playwright — evidência real, com logs;
* a execução **headed** com login real (Marco 8) acontece no laptop do usuário.

### 3.2 Ambiente-alvo final (laptop do usuário)

Ubuntu/Debian, ~4 GB RAM, Python ≥ 3.11, navegador visível, login e seleção de modelo manuais.

## 4. Marcos

| Marco | Entrega | Status |
|-------|---------|--------|
| M0 | Auditoria, `docs/EXPERIMENT_PLAN.md`, `docs/DECISIONS.md`, esquema de resultados | em andamento |
| M1 | `fixtures/fake_chat.html` determinística | pendente |
| M2 | `browser.py` + `session.py`: perfil exclusivo, lock, fechamento limpo, persistência | pendente |
| M3 | `discovery.py` + `probes/chat_probe.js`: candidatos pontuados | pendente |
| M4 | `sender.py`: comparação de estratégias de envio | pendente |
| M5 | `observer.py`: MutationObserver + sinais de UI + híbrido | pendente |
| M6 | `extractor.py`: texto limpo e Markdown mínimo | pendente |
| M7 | `benchmark.py` + `report.py`: medições | pendente |
| M8 | Adaptadores assistidos de Gemini e LMArena (execução pelo usuário) | pendente |

Cada marco é fechado com: arquivos alterados, comandos executados, saída real dos testes,
limitações e próximo passo.

## 5. Matriz de experimentos

### E-DISC — Descoberta (M3)

* **E-DISC-1** DOM comum: ranking do composer da fixture.
* **E-DISC-2** Botão de envio: ranking e confirmação por envio real.
* **E-DISC-3** Open Shadow DOM: composer dentro de `attachShadow({mode:'open'})`.
* **E-DISC-4** Classificação de mensagens: contêiner de usuário vs assistente.
* **E-DISC-5** iframe same-origin.
* **E-DISC-6** Penalização: classes dinâmicas (`ng-tns-*`, hashes), `nth-child`, seletores ambíguos.

Métricas: posição do candidato correto, tempo (ms), nº de candidatos, seletor vencedor.

### E-SEND — Envio (M4)

Estratégias: `fill`, `keyboard_type`, `contenteditable_type`, `click_send`, `press_enter`,
`js_fallback` (último recurso).
Evidência obrigatória: nova mensagem do usuário aparece com o texto esperado.
Métricas: sucesso/falha, duração (ms), estratégia, erro.

### E-OBS — Streaming e término (M5)

Estratégias: `stability_only`, `ui_signals`, `hybrid`.
Cenários: streaming normal; **pausa artificial de 3 s no meio**; resposta vazia; timeout;
estabilidade sem botão Copy; Copy antes da estabilidade; erro de rate limit; login expirado.
Métricas: TTFT (ms), tempo até término (ms), overhead após última mutação (ms), falsos positivos
de término, acurácia contra o ground truth da fixture.

### E-EXT — Extração (M6)

Comparação `innerText` vs `textContent` normalizado vs serializador Markdown.
Cenários: parágrafos, títulos, listas, links, inline code, bloco de código com linguagem,
blockquote, tabela simples, elementos ocultos, botões de feedback.
Métricas: preservação de estrutura (asserções), tempo (ms), tamanho da saída, **DOM original
inalterado** (hash do HTML antes/depois).

### E-SESS — Sessão (M2/M8)

* **E-SESS-1** Perfil persiste após fechar e reabrir (IndexedDB/localStorage quando suportado).
* **E-SESS-2** Reúso da aba quente para a 2ª mensagem.
* **E-SESS-3** Lock: segundo processo com o mesmo `user_data_dir` é recusado com erro claro.

### E-BENCH — Consumo (M7)

Startup frio e quente; RSS do Python; RSS aproximado da árvore do navegador (soma de `/proc/*/status`
dos processos filhos); descoberta; preenchimento; envio; TTFT; overhead pós-mutação; extração.
Métricas: ms, KB, sucesso/falha. Repetição: 10 execuções para o teste de aprovação.

### E-DIAG — Deriva de DOM (M3/M8)

Compara o conjunto de candidatos de duas execuções e reporta `drift` (seletores que deixaram de
existir, novos candidatos, queda de pontuação do vencedor).

## 6. Formato dos resultados

Definido em [`docs/RESULTS_SCHEMA.md`](RESULTS_SCHEMA.md). Em resumo: um envelope JSON por
execução (`run_id`, `timestamp`, `env`, `experiment`, `strategy`, `target`, `metrics`, `events`,
`status`, `error`) e um CSV "longo" (uma linha por métrica) para análise.

## 7. Riscos e limitações conhecidas

1. **Sandbox sem navegador** — mitigado com CI + núcleo Python puro (ADR-002, ADR-007).
2. **Closed Shadow DOM** é inacessível por design do navegador; será registrado como limitação.
3. **Seletores de sites reais mudam** — nenhum seletor é contrato; há detecção de drift.
4. **4 GB de RAM** — concorrência 1, aba única, screenshots somente para diagnóstico.
5. **Login/CAPTCHA** nunca são automatizados; o usuário intervém (Marco 8).

## 8. Política de evidência

Nenhum resultado é considerado verdadeiro sem execução real. Todo relatório registra o comando
executado e a saída obtida. Testes que não puderam rodar são marcados como `SKIPPED` com o motivo —
nunca como sucesso.
