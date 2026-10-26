# Consolidação e validação — 2026-10-24

## Veredito

**Aprovado para uso como laboratório local/CI com fixture sintética.**
**Não aprovado como serviço para agentes 24/7 ou integração pronta com Gemini/LMArena.**
Não há garantia de ausência de defeitos; os limites comprovados estão descritos abaixo.

Código testado: `1d4bb718fdf2aafca1bcab874dadfb0912ae59bd`.

[Execução final 40135895580](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40135895580)
— ambos os jobs aprovados; integração em 6 min 8 s.

## Testes executados de verdade

Comando no runner: `python -m unittest discover -s tests -v`.

```text
Ran 208 tests in 81.019s

OK (skipped=1)
```

O único teste ignorado verifica a situação de **navegador ausente**, não aplicável
a esse runner. Nenhuma classe de integração foi ignorada. O job exige navegador
real e falha se ele estiver indisponível.

Log integral: `results/ci/40135895580/browser-tests.log`.

### Instalação e usabilidade operacional

O CI executou `pip install .`, mudou para `/tmp` e invocou o console script
instalado, sem depender do diretório do repositório:

```text
browserapi-lab --help
browserapi-lab verify --iterations 10 --results <destino>/chromium
browserapi-lab verify --iterations 3 --channel chrome --results <destino>/chrome
xvfb-run -a browserapi-lab verify --headed --iterations 1 --results <destino>/headed
```

Os três comandos `verify` retornaram código zero. Assets JS/HTML são incluídos
no pacote. Help, argumentos inválidos e códigos de falha também têm testes.
Isso comprova a usabilidade operacional da CLI, **não uma avaliação humana de UX**.

## Fluxo ponta a ponta

Descoberta → preenchimento → envio com mensagem nova como evidência → observação
por MutationObserver → decisão híbrida → extração de Markdown → comparação do DOM
original → JSON/CSV e resumo de desempenho.

| Execução do verificador instalado | Experimentos | Falhas | Mensagens sequenciais sem navegar |
|---|---:|---:|---:|
| Chromium headless | 43 | 0 | 20 |
| Chrome do sistema headless | 36 | 0 | 20 |
| Chromium headed em Xvfb | 34 | 0 | 20 |
| **Total** | **113** | **0** | **60** |

Experimentos negativos passam somente se o comportamento de bloqueio/timeout for
o esperado. Uma resposta vazia que produz timeout não é uma resposta válida para
um agente; é uma verificação bem-sucedida da lógica de falha.

### Cobertura importante

- Dez fluxos consecutivos na suíte e no baseline Chromium do verificador.
- Pausa artificial de três segundos sem término prematuro.
- textarea, input, contenteditable, open Shadow DOM e iframe same-origin.
- Fill, teclado, Enter em input e fallback JS em testes reais.
- Stop, Copy antecipado e estabilidade sem Copy.
- Resposta vazia e recuperação na mesma página após timeout.
- Erro, login expirado e rate limit simulados; opções da UI não causam falso bloqueio.
- JSON com identificação de tentativa, saída antiga, eco do usuário excluído do
  conjunto candidato e duas saídas válidas tratadas como ambiguidade. Essa parte é
  teste de componente em DOM controlado, não adaptação de formato em sites reais.
- HTML com código, listas, link, tabela, ocultos e feedback; DOM intacto.
- localStorage e IndexedDB persistem após fechar/reabrir; exportação sanitizada.
- Lock entre processos, limpeza quando driver falha e bloqueio de reenvio ambíguo.
- Conversa com 150 controles antigos e histórico com mais de 7000 nós.
- Relatórios rejeitam path traversal, métricas não finitas e iteração inválida.

## Velocidade medida

Runner: Linux, 4 vCPU, aproximadamente 15,6 GiB RAM, Python 3.11.17,
Playwright 1.64.1. Chromium 156.0.8078.4; Chrome 155.0.8059.39.
A fixture usa streaming artificial com `delay=1`; o navegador impõe seu próprio
agendamento de timers. Estes números **não são latência de modelos reais**.

| Métrica | Chromium headless (n=10 baseline) | Chrome headless (n=3 baseline) |
|---|---:|---:|
| Fluxo total, mediana | 2056 ms | 2101 ms |
| Fluxo total, P95 | 2175 ms | 2446 ms |
| Último conteúdo → conclusão da verificação, P95 | 338 ms | 331 ms |
| Startup de perfil novo | 432 ms | 1282 ms |
| Reinício do perfil | 446 ms | 645 ms |

P95 é nearest-rank. Amostra Chrome é pequena e exploratória; não demonstra
superioridade estatística de um canal. O orçamento automatizado é P95 < 2500 ms
**após a última mutação**, não para o fluxo total.

**Advertência headed:** o único baseline de janela virtual levou **8771 ms**,
com aproximadamente **6655 ms na ativação do clique inicial**. Os cenários
subsequentes seguiram funcionando, mas não há base para prometer primeiro envio
rápido em ambiente gráfico. O tempo pós-mutação desse baseline foi 241 ms. A
latência inicial headed merece investigação adicional no laptop real; não foi
ocultada nem "corrigida" com cliques forçados.

### Recursos

RSS aproximado da árvore do navegador + driver, somado por processo (memória
compartilhada pode ser contada mais de uma vez):

| Canal | Antes das 20 mensagens | Depois |
|---|---:|---:|
| Chromium headless | 832516 KB | 884992 KB |
| Chrome headless | 1434076 KB | 1463012 KB |
| Chromium headed | 1487936 KB | 1509804 KB |

Essas amostras não são pico nem comprovam ausência de vazamentos. O histórico do
DOM cresce deliberadamente. CPU registrada nos envelopes é somente do Python,
não da árvore do navegador. Não há homologação de consumo no laptop de 4 GB.

## Defeitos encontrados e corrigidos nesta consolidação

1. Assets fora do pacote impediam uso instalado: agora JS/HTML viajam no pacote.
2. CLI só tinha diagnóstico: `verify` executa fluxo, cenários e métricas.
3. Falta de confirmação podia provocar reenvio: ativação ambígua não é repetida.
4. Falha ao encerrar driver podia deixar lock preso: limpeza usa `finally` aninhado.
5. Reinstalar observador em aba quente acumulava MutationObservers: o anterior é desligado.
6. Conversas longas esgotavam candidatos antes de alcançar Send: varredura limitada
   prioriza os nós recentes; regressão também cobre histórico acima do teto de nós.
7. Diagnóstico de mensagem divergente podia incluir texto privado: conteúdo foi removido.
8. Relatórios aceitavam métricas inválidas e identificador com path traversal: agora rejeitam.

A rodada `40135546456` ficou **vermelha** ao detectar a falha na 20ª mensagem.
Sua evidência está preservada; a aprovação final só veio após corrigir e repetir.

## Pendências que bloqueiam uma entrega de produção para agentes

- Gemini e LMArena reais não foram executados: rede/autenticação e participação
  manual do usuário são necessárias. Não automatizar CAPTCHA ou escolha de modelo.
- Não existe API OpenAI-compatible, fila de agentes, SSE nem serviço supervisionado;
  essa parte foi explicitamente excluída do briefing inicial.
- Endurance de horas/dias, quedas de rede, expiração real de login e deriva real de
  DOM não foram homologados. Vinte mensagens por canal não equivalem a 24/7.
- Acessibilidade humana, laptop de 4 GB e latência inicial headed precisam de teste.
- Seletores e sinais não são universais. Closed Shadow DOM, iframes cross-origin,
  layout/CSS externo e respostas fora do contrato têm limitações.
- Polling como baseline completo e CPU do navegador ainda não estão medidos.

Nenhum login real, limite ou autenticação foi contornado. Nenhum conteúdo privado
foi usado nesses experimentos. A aprovação é estritamente a do laboratório descrito.

## Onde estão as evidências

`results/ci/40135895580/benchmark/{chromium,chrome,headed}/` contém:

- `summary.json`;
- envelopes JSON de cada experimento;
- CSV longo e largo;
- logs das invocações instaladas, no diretório pai.

Resultados mais antigos diretamente em `results/ci/` são históricos, não o estado final.
