# browserapi-lab

Laboratório Python/Linux para validar automação de chats por navegador real.
**Não é ainda uma API para agentes nem um serviço 24/7.** O aplicativo final
OpenAI-compatible continua fora do escopo desta etapa.

## Janela para Ubuntu (experimental)

Agora há um painel local com botões de configurar, autorizar, testar e corrigir,
e montagem de instalador `.deb` com entrada no menu. A versão ubuntu4 inclui
**Selecionar botão de voz**, **Digitar e selecionar Enviar / Enter** e mudança
explícita de sessão em chats já salvos. A ubuntu5 integra a pergunta de voz
no assistente completo e mostra as versões da interface e do programa. Veja o [guia sem terminal](docs/UBUNTU.md).
Alvo inicial: Ubuntu 24.04+ com Python 3.11+. A instalação gráfica no desktop do
usuário e os sites autenticados ainda não estão homologados; isso não é uma API pronta.


## Novo: escolher e verificar um chat

As [seis metas de produto](docs/PRODUCT_GOALS.md) agora orientam o desenvolvimento.
O assistente permite selecionar navegador e chat, fazer login/escolher modelo
manualmente, testar uma mensagem autorizada e reparar campos por apontamento:

```bash
browserapi-lab configure meu-gemini
browserapi-lab check meu-gemini
browserapi-lab status meu-gemini
browserapi-lab repair meu-gemini
browserapi-lab ask meu-gemini
```

Leia o [guia de configuração e reparo](docs/CHAT_GUIDE.md) e o
[estado de validação das metas](docs/PRODUCT_VALIDATION.md). Compatibilidade só é
confirmada para a execução testada; Gemini/LMArena continuam aguardando homologação
assistida real. Seletores conhecidos são hipóteses, não garantia. Não há promessa
medida de equivalência a API ou funcionamento contínuo.

## O que já é executável

Um comando abre um Chromium real, serve uma fixture HTTP local, descobre os
controles, envia com confirmação, observa streaming, extrai Markdown e gera
JSON/CSV com métricas. Não abre sites externos, não faz login e não usa seu perfil
pessoal. Usa uma instância de navegador e uma aba quente, com concorrência 1.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
python -m playwright install chromium
# Somente se faltarem bibliotecas no Debian/Ubuntu; requer autorização administrativa:
python -m playwright install-deps chromium

browserapi-lab doctor
browserapi-lab verify --iterations 10
```

Para usar o Google Chrome instalado ou uma janela visível:

```bash
browserapi-lab verify --channel chrome --iterations 10 --results results/chrome
browserapi-lab verify --headed --results results/headed
```

`--headed` requer sessão gráfica. No CI é testado com display virtual (Xvfb);
isso não equivale a uma avaliação humana de usabilidade no laptop.
Também funciona a partir do checkout: `python -m browserapi_lab.cli verify`.

## Como interpretar o resultado

O comando `verify` imprime um resumo JSON e retorna:

| Código | Significado |
|---|---|
| `0` | Todos os cenários e o orçamento de latência passaram |
| `1` | Falhou algum cenário ou orçamento de latência |
| `2` | Argumentos inválidos, ambiente/navegador indisponível ou falha de inicialização |
| `130` | Interrompido pelo usuário |

Resultados em `results/verify/`:

- `summary.json`: ambiente, falhas, P50/P95, startup/reinício e RSS aproximado.
- `json/`: métricas por execução, sem conteúdo privado.
- `csv/metrics.csv` e `csv/runs.csv`: dados para análise.

**Uma resposta vazia que termina por timeout é um cenário negativo esperado**;
se o comportamento observado for o esperado, o experimento passa. Isso não
transforma timeout em uma resposta válida para um agente.

### Cenários do verificador

- Dez fluxos completos por padrão (configurável de 1 a 1000).
- Pausa de três segundos, Copy prematuro, ausência de Copy, campo input e contenteditable.
- Open Shadow DOM e iframe same-origin.
- Resposta vazia, erro, login expirado e rate limit simulados.
- Comparação `hybrid`, `stability_only` e `ui_signals` na resposta normal.
- Vinte mensagens adicionais na mesma aba/conversa, sem navegar entre mensagens.
- Reinício do perfil e verificação de reúso da aba.
- Preservação de estrutura Markdown e DOM intacto.

O orçamento conservador é **P95 < 2500 ms do último conteúdo até a conclusão da
verificação** na fixture. O tempo total inclui o streaming artificial: não é a
latência de Gemini/LMArena, nem um SLA de produção.

## Desenvolvimento e testes

```bash
python -m unittest discover -s tests -v
```

Sem Chromium, as classes de integração são ignoradas com motivo explícito. No job
de navegador do GitHub Actions, o navegador é obrigatório: indisponibilidade gera
falha. O CI executa testes reais e testa o pacote instalado fora do checkout,
Chromium, Chrome do sistema e Chromium headed com Xvfb. Os logs e benchmarks
sanitizados ficam em `results/ci/<run_id>/`.

## Segurança e confiabilidade

- Por padrão usa perfil separado com lock cooperativo. A opção experimental de conectar ao Chrome pessoal já aberto exige consentimento explícito; não inicia outro processo no perfil nem copia cookies. Veja [o guia e os riscos de acesso](docs/UBUNTU.md).
- Não repete automaticamente um envio cuja aceitação seja ambígua.
- Campo esvaziado é evidência adicional, não prova isolada de envio.
- Contrato JSON opt-in rejeita saídas antigas e sinaliza múltiplas saídas válidas.
  A validação estrutural é um componente experimental; ainda não é adaptador de site.
- CAPTCHA, login e seleção de modelo são manuais. Não há descoberta automática de modelos.
- Não registra mensagens privadas, cookies ou tokens nos relatórios.
- O estado bruto exportado de sessão é sensível: deve ficar somente em `profiles/`,
  nunca ser anexado a relatórios ou versionado.

## Limites da entrega

**Pronto para uso como laboratório de validação local e CI. Não homologado para
agentes 24/7 ou automação genérica de sites reais.** Ainda é necessário:

1. Executar Gemini e LMArena com autenticação e autorização assistidas.
2. Medir compatibilidade e consumo no laptop de aproximadamente 4 GB.
3. Executar endurance prolongado (horas/dias), com recuperação de rede e sessão.
4. Validar adaptadores contra mudanças reais de DOM; seletores não são contratos.
5. Closed Shadow DOM, iframes cross-origin e CSS externo ocultando conteúdo têm
   limitações: a fixture não demonstra cobertura universal.

Não há FastAPI, SSE, fila, `/v1/models` ou `/v1/chat/completions` neste laboratório.

## Documentação

- [Relatório de validação](docs/VALIDATION_REPORT.md)
- [Plano de experimentos](docs/EXPERIMENT_PLAN.md)
- [Decisões técnicas](docs/DECISIONS.md)
- [Esquema dos resultados](docs/RESULTS_SCHEMA.md)
