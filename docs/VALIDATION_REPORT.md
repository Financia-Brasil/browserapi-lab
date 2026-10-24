# Relatório de validação — 2026-10-24

## Evidência real

Execução GitHub Actions: https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40121924859

Commit testado: `bc34f3c` (ver metadados em `results/ci/40121924859/resumo.md`).
Comando: `python -m unittest discover -s tests -v`.
Saída real, obtida do runner:

```
Ran 176 tests in 74.532s

OK (skipped=1)
```

Log integral: `results/ci/40121924859/browser-tests.log`.
Ambiente: `results/ci/40121924859/doctor-browser.json`.
O único teste ignorado verifica comportamento **sem navegador**, condição que não
se aplica ao runner com Chromium instalado. Nenhuma classe de integração foi ignorada.

## Fluxo ponta a ponta comprovado na fixture

- Descoberta e ranking do composer e botão de envio.
- Preenchimento e clique com evidência de nova mensagem do usuário.
- MutationObserver, sinais de UI e decisão híbrida.
- Dez execuções consecutivas bem-sucedidas.
- Pausa artificial de três segundos sem término prematuro.
- textarea, input, contenteditable, open Shadow DOM e iframe same-origin.
- Extração com títulos, listas, código com linguagem, link e tabela.
- Impressão digital do DOM idêntica antes/depois da extração.
- Persistência de localStorage após reinício e recusa de segundo processo no perfil.

## Correções descobertas durante testes reais

1. Sessão deixada aberta pelo teste de persistência bloqueava as classes seguintes.
2. Falhas de inicialização eram indevidamente tratadas como testes ignorados.
3. Streaming por insertAdjacentHTML em fragmentos não preservava a estrutura HTML.
4. Texto de opções do painel era confundido com mensagem real de rate limit.
5. Logs eram ignorados pelo Git e resultados simultâneos causavam conflito de publicação.
6. Pipeline de shell precisava de `pipefail` explícito para não mascarar falhas de unittest.

As execuções com falha também estão preservadas em `results/ci/40121661386/`.
Os logs antigos diretamente em `results/ci/` são históricos, **não** a validação mais recente.

## Validação local adicional

Após adicionar quatro testes puros de evidência de envio:

```
/home/user/.venv/bin/python -m unittest discover -s tests
Ran 134 tests in 6.368s
OK (skipped=10)
```

Dez entradas ignoradas correspondem a gates/classes de navegador indisponível no
sandbox; não são evidência de aprovação dessas integrações localmente.

## Pendências — não afirmar aprovação final

- M4: matriz comparativa completa de todas as estratégias de teclado/Enter/JS.
- M5: comparação medida MutationObserver vs polling e cenários adicionais integrados
  de timeout/resposta vazia/bloqueios (há testes puros e fixture, mas não toda a matriz).
- M7: benchmark frio/quente, CPU e consumo comparativo dos canais Chromium/Chrome.
- M8: Gemini e LMArena reais, em navegador visível, login e seleção manual de modelo,
  uma mensagem somente após confirmação do usuário.
- Validar consumo no laptop de 4 GB: o runner de CI tem aproximadamente 16 GB;
  resultados nele não demonstram adequação ao laptop.
- O doctor não distingue sandbox remoto genérico de Linux local sem marcadores Codespaces.
- Empacotamento/distribuição instalada ainda precisa de teste; execução validada é a
  partir do checkout do repositório.

Nenhuma API OpenAI-compatible foi criada. Nenhum login, CAPTCHA ou limite foi contornado.
