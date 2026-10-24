# Esquema de Resultados — browserapi-lab

Todo experimento grava **um envelope JSON por execução** e **linhas CSV** derivadas dele.
Objetivos: (1) permitir comparação entre estratégias; (2) ser legível por pandas/planilha;
(3) nunca conter dados privados (ADR-009).

Versão atual do esquema: `1.0`.

## 1. Envelope JSON (`results/json/<run_id>.json`)

```json
{
  "schema_version": "1.0",
  "run_id": "20261024T120000Z-3f9c1a",
  "timestamp_utc": "2026-10-24T12:00:00Z",
  "milestone": "M5",
  "experiment": "E-OBS-3",
  "target": "fixture",
  "target_url": "file:///home/user/browserapi-lab/fixtures/fake_chat.html",
  "strategy": "hybrid",
  "iteration": 1,
  "status": "success",
  "error": null,
  "env": {
    "python": "3.11.2",
    "platform": "Linux-6.1.158-x86_64-with-glibc2.36",
    "cpu_count": 2,
    "ram_total_kb": 4033852,
    "playwright": "1.64.1",
    "browser_channel": "chromium",
    "browser_version": "141.0.7390.54",
    "headed": false,
    "ci": true
  },
  "metrics": {
    "discovery_ms": 41.2,
    "fill_ms": 12.5,
    "send_ms": 8.1,
    "ttft_ms": 310.0,
    "stream_ms": 2410.5,
    "settle_overhead_ms": 220.0,
    "extract_ms": 6.3,
    "total_ms": 2800.0,
    "python_rss_kb": 62400,
    "browser_rss_kb": 210300,
    "mutation_count": 412,
    "success": true
  },
  "events": [
    {"t_ms": 0.0,   "type": "send",        "detail": "strategy=fill"},
    {"t_ms": 310.0, "type": "first_token", "detail": "mutation=17"},
    {"t_ms": 2710.0,"type": "last_mutation"},
    {"t_ms": 2720.0,"type": "ui_signal",   "detail": "aria_busy=false"},
    {"t_ms": 2930.0,"type": "done",        "detail": "reason=stable+ui"}
  ],
  "artifacts": {
    "screenshot": null,
    "trace": null,
    "candidates": "results/json/20261024T120000Z-3f9c1a.candidates.json"
  }
}
```

### Campos obrigatórios

| Campo | Tipo | Observações |
|-------|------|-------------|
| `schema_version` | string | `"1.0"` |
| `run_id` | string | `UTC compacto + 6 hex` |
| `timestamp_utc` | string | ISO 8601 com `Z` |
| `milestone` | string | `M0`..`M8` |
| `experiment` | string | `E-DISC-1`, `E-SEND-2`, ... |
| `target` | string | `fixture` \| `gemini` \| `lmarena` \| `unit` |
| `strategy` | string | nome da estratégia, ou `"none"` |
| `iteration` | int | 1..N para execuções repetidas |
| `status` | string | `success` \| `failure` \| `timeout` \| `skipped` |
| `error` | string? | mensagem curta, sem dados sensíveis |
| `env` | object | ver §1.1 |
| `metrics` | object | números; ver §2 |
| `events` | array | linha do tempo, ver §3 |

### 1.1 `env`

`python`, `platform`, `cpu_count`, `ram_total_kb`, `playwright`, `browser_channel`,
`browser_version`, `headed`, `ci`. Em execuções sem navegador: `browser_version = null` e
`browser_channel = "none"`.

## 2. Métricas padronizadas (chaves de `metrics`)

| Chave | Unidade | Descrição |
|-------|---------|-----------|
| `discovery_ms` | ms | coleta + pontuação de candidatos |
| `fill_ms` | ms | preenchimento do composer |
| `send_ms` | ms | clique/Enter até aceitação |
| `ttft_ms` | ms | envio → primeira mutação da resposta |
| `stream_ms` | ms | primeira → última mutação |
| `settle_overhead_ms` | ms | última mutação → decisão de término |
| `extract_ms` | ms | serialização da resposta |
| `total_ms` | ms | início → fim |
| `python_rss_kb` | KB | RSS do processo Python (`/proc/self/status`) |
| `browser_rss_kb` | KB | soma do RSS da árvore de processos do navegador |
| `mutation_count` | int | mutações observadas na resposta |
| `candidate_count` | int | candidatos avaliados |
| `success` | bool | evidência observável obtida |

Métricas específicas por experimento podem ser acrescentadas; todas as chaves ausentes viram
célula vazia no CSV (nunca `null` solto).

## 3. Eventos (`events`)

Cada evento: `{"t_ms": float, "type": string, "detail": string?}`.
Tipos usados: `open_page`, `discover`, `fill`, `send`, `first_token`, `mutation`, `last_mutation`,
`ui_signal`, `pause_start`, `pause_end`, `done`, `timeout`, `error`, `login_required`,
`captcha_detected`, `rate_limited`.

## 4. CSV

### 4.1 `results/csv/metrics.csv` (formato longo)

```csv
run_id,timestamp_utc,milestone,experiment,target,strategy,iteration,status,metric,value,unit
20261024T120000Z-3f9c1a,2026-10-24T12:00:00Z,M5,E-OBS-3,fixture,hybrid,1,success,ttft_ms,310.0,ms
20261024T120000Z-3f9c1a,2026-10-24T12:00:00Z,M5,E-OBS-3,fixture,hybrid,1,success,stream_ms,2410.5,ms
```

Uma linha por métrica — permite pivotar sem retrabalho.

### 4.2 `results/csv/runs.csv` (formato largo, uma linha por execução)

Colunas fixas: `run_id,timestamp_utc,milestone,experiment,target,strategy,iteration,status,error,
total_ms,ttft_ms,stream_ms,settle_overhead_ms,discovery_ms,fill_ms,send_ms,extract_ms,
python_rss_kb,browser_rss_kb,mutation_count,candidate_count,success`.

## 5. Candidatos de descoberta (`results/json/<run_id>.candidates.json`)

```json
{
  "schema_version": "1.0",
  "run_id": "20261024T120000Z-3f9c1a",
  "target": "fixture",
  "role": "composer",
  "candidates": [
    {
      "rank": 1,
      "selector": "textarea#composer",
      "score": 87.5,
      "signals": {"tag": "textarea", "role": "textbox", "placeholder": true, "visible": true},
      "penalties": {"dynamic_class": 0.0, "path_length": 1.5, "ambiguity": 0.0},
      "inside": "document",
      "occurrences": 1
    }
  ]
}
```

`inside` ∈ `document` \| `open_shadow` \| `iframe` \| `closed_shadow`.

## 6. Regras de higiene

* Nunca gravar cookies, tokens, senhas, `authorization` ou conteúdo de mensagens de sites reais.
* Em alvos reais, mensagens são registradas como `{"chars": N, "sha256_12": "..."}`.
* `results/` fica no `.gitignore`, exceto `results/samples/**` (exemplos sintéticos).
