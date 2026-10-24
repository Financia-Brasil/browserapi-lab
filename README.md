# browserapi-lab

Laboratório Linux leve para pesquisar, testar e medir automação, streaming e extração de respostas
em interfaces web de chats de IA **antes** da construção de uma API local compatível com OpenAI.

> **Este repositório não é o aplicativo final.** Não há FastAPI, `/v1/chat/completions`, SSE ou fila
> aqui — apenas componentes medidos que sustentarão o aplicativo futuro.

## Status

| Marco | Entrega | Status |
|-------|---------|--------|
| M0 | Auditoria, plano de experimentos, decisões, esquema de resultados | concluído |
| M1 | `fixtures/fake_chat.html` determinística | pendente |
| M2 | Navegador e sessão persistentes com perfil exclusivo e lock | pendente |
| M3 | Descoberta de elementos por pontuação | pendente |
| M4 | Estratégias de envio | pendente |
| M5 | Observação de streaming e detecção de término | pendente |
| M6 | Extração de texto limpo e Markdown | pendente |
| M7 | Benchmark de consumo | pendente |
| M8 | Adaptadores assistidos de Gemini e LMArena | pendente |

## Dependências

Apenas `playwright` (ADR-008). Todo o resto é biblioteca padrão do Python 3.11+.
Testes usam `unittest` — sem pytest, sem Docker, sem banco, sem Selenium, sem Node.

## Instalação

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium      # baixa o Chromium gerenciado
# em Debian/Ubuntu, se faltarem bibliotecas do sistema:
sudo python3 -m playwright install-deps chromium
```

## Uso (Marco 0)

```bash
python -m browserapi_lab.cli doctor                       # audita o ambiente
python -m browserapi_lab.cli doctor --json results/doctor.json
python -m unittest discover -s tests                      # testes do núcleo
```

O `doctor` **não instala nada** e nunca executa `sudo`: ele apenas diagnostica e sugere comandos.

## Documentação

* [`docs/EXPERIMENT_PLAN.md`](docs/EXPERIMENT_PLAN.md) — perguntas, matriz de experimentos e critérios.
* [`docs/DECISIONS.md`](docs/DECISIONS.md) — ADRs (decisões técnicas) e quando reabri-las.
* [`docs/RESULTS_SCHEMA.md`](docs/RESULTS_SCHEMA.md) — formato JSON/CSV dos resultados.

## Onde cada parte roda

| Parte | Onde roda | Por quê |
|-------|-----------|---------|
| Núcleo Python (pontuação, decisão, extração, lock, relatório) | qualquer lugar, inclusive sem navegador | ADR-002 |
| Integração real com Chromium | GitHub Actions (`ubuntu-latest`) | ambiente com bibliotecas e download do navegador |
| Testes headed com login real | laptop do usuário | exige login manual e seleção de modelo |

## Limitações declaradas

1. Closed Shadow DOM é inacessível por design do navegador.
2. Seletores de sites reais mudam; nenhum seletor é tratado como contrato (há detecção de drift).
3. O ambiente de desenvolvimento remoto usado neste repositório não possui bibliotecas de runtime
   do Chromium nem `apt`; o navegador roda apenas no CI e no laptop.
4. Nada de cookies, tokens ou conteúdo de mensagens é gravado (ADR-009).

## Escopo futuro (fora daqui)

Interface de configuração, adaptadores por chat, navegador/página quente, fila com concorrência 1,
`/v1/models`, `/v1/chat/completions`, SSE e erros no formato OpenAI.
