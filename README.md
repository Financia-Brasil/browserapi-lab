# browserapi-lab

Laboratório Linux leve para pesquisar, testar e medir automação, streaming e extração de respostas
em interfaces web de chats de IA **antes** da construção de uma API local compatível com OpenAI.

> **Este repositório não é o aplicativo final.** Não há FastAPI, `/v1/chat/completions`, SSE ou fila
> aqui — apenas componentes medidos que sustentarão o aplicativo futuro.

## Status

| Marco | Entrega | Status |
|-------|---------|--------|
| M0 | Auditoria, plano de experimentos, decisões, esquema de resultados | concluído |
| M1 | `fixtures/fake_chat.html` determinística | em desenvolvimento / validação |
| M2 | Navegador e sessão persistentes com perfil exclusivo e lock | em desenvolvimento / validação |
| M3 | Descoberta de elementos por pontuação | em desenvolvimento / validação |
| M4 | Estratégias de envio | em desenvolvimento / validação |
| M5 | Observação de streaming e detecção de término | em desenvolvimento / validação |
| M6 | Extração de texto limpo e Markdown | em desenvolvimento / validação |
| M7 | Benchmark de consumo | em desenvolvimento / validação |
| M8 | Adaptadores assistidos de Gemini e LMArena | em desenvolvimento / validação |

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

## Validação atual (2026-10-24)

O núcleo possui 130 testes executados localmente. As classes que exigem Chromium
são explicitamente ignoradas neste sandbox por falta de bibliotecas do navegador.
O GitHub Actions instala Chromium e executa a suíte completa. Consulte os resultados
mais recentes em `results/ci/browser-tests.log` e `results/ci/resumo.md`: um job verde
com testes ignorados **não** equivale à aprovação ponta a ponta.

O pipeline de integração cobre descoberta, envio com evidência, streaming, Markdown,
DOM intacto, dez repetições, pausa, input/contenteditable, Shadow DOM e iframe.
Benchmark completo (M7) e execuções assistidas de Gemini/LMArena (M8) ainda pendentes.
Não há validação de consumo no laptop de 4 GB.

### Resultado comprovado em Chromium

[Execução 40121924859](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40121924859):
**176 testes em 74,532 s — OK, um teste ignorado por condição de ambiente**.
As dez repetições do pipeline e a pausa longa passaram. Consulte
[`docs/VALIDATION_REPORT.md`](docs/VALIDATION_REPORT.md) para evidências, correções e
pendências. Isso valida a fixture local, não os sites reais nem o consumo no laptop.
