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
