# browserapi-lab

Laboratório Python/Linux para validar automação de chats por navegador real.
**Não é um serviço homologado 24/7.** A versão 0.4.0 acrescenta uma API local
experimental e opt-in, com subconjunto textual de Chat Completions, não paridade
completa OpenAI. Veja [contrato, ativação e limites](docs/LOCAL_API.md).

## Janela para Ubuntu (experimental)

Agora há um painel local com botões de configurar, autorizar, testar e corrigir,
e montagem de instalador `.deb` com entrada no menu. A versão ubuntu4 inclui
**Selecionar botão de voz**, **Digitar e selecionar Enviar / Enter** e mudança
explícita de sessão em chats já salvos. A ubuntu5 integra a pergunta de voz
no assistente completo e mostra as versões da interface e do programa. A versão
**0.3.1** entregou dashboard e atualização automática com rollback. O código
**0.4.0** acrescenta inventário de perfis, API local, recuperação de contexto e
histórico opcional, preservando o atualizador. O instalador estável só muda após
os testes e a publicação automática da release. Veja o [guia sem terminal](docs/UBUNTU.md).
Alvo inicial: Ubuntu 24.04+ com Python 3.11+. A instalação gráfica no desktop do
usuário e os sites autenticados ainda não estão homologados; não é uma API de produção.


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

## Dashboard e próxima arquitetura

A versão **0.2.0+ubuntu1** acrescenta dashboard local: sucesso/falha, latência
média/P95, fontes pelo último estado observado, fases da execução e até 30 barras
de histórico. Janela de 100 operações em memória, sem conteúdo de mensagens.
Tokens são **Não disponível**, não uma estimativa apresentada como consumo real.
Configurar, testar e conversar continuam exigindo consentimento; nenhuma
mensagem é enviada para monitoramento. Não foram ligados headless, bloqueio de
recursos, replay Fetch/XHR, atualizador ou failover automático.

O [plano da próxima arquitetura](docs/NEXT_ARCHITECTURE.md) descreve sessões,
otimização, releases, API local, fallback seguro e RAG/histórico pesquisável.
Histórico de 1M tokens **não** é contexto nativo de 1M tokens do modelo.
[Instalação gráfica e limites](docs/UBUNTU.md).

## Documentação

- [Relatório de validação](docs/VALIDATION_REPORT.md)
- [Plano de experimentos](docs/EXPERIMENT_PLAN.md)
- [Decisões técnicas](docs/DECISIONS.md)
- [Esquema dos resultados](docs/RESULTS_SCHEMA.md)


## Atualização automática (0.3.0)

O instalador atual inclui supervisor e atualizador: consulta releases estáveis
do repositório, verifica integridade/compatibilidade e aplica código automaticamente
quando não houver tarefa ativa. Mantém a aba, troca o processo com segurança e
restaura a versão anterior se a nova falhar ao iniciar. Não há reenvio de mensagens.
Ativação padrão visível e revogável na GUI; sem root. É necessária uma instalação
inicial porque as versões antigas não tinham esse mecanismo. Não é preciso
reinstalar cada próxima versão ABI 1. Veja [confiança, publicação e limites](docs/UPDATES.md).

O workflow de publicação para main depende dos testes; patch automático, minor/
major por incremento da base. Alterações nesta branch só afetam main depois de
integradas. Inventário de perfis, API, RAG e roteamento não são implementados por
este atualizador e continuam no plano, sem falsa alegação de entrega completa.

## Redesenho 0.5

Conexões primeiro, com abertura nativa de perfil Chrome já existente e permissão
separada; API, atividade e manutenção em áreas próprias. Fontes locais, teclado,
contraste e capturas desktop/375px: [revisão com evidências](docs/design/UI_050_REVIEW.md).
Abertura normal de perfil não implica conta verificada nem autorização CDP.

## Assistente gráfico 0.6.0

**Corrigir campos → área azul → prévia verde → Usar esta área.**
O assistente enumera candidatos visíveis sem escrever em todos os campos. Para
textos, permite ajustar camadas e voltar antes de confirmar. Ações inaplicáveis
ficam ocultas. Esc cancela; Mover painel libera regiões encobertas.

**Meus chats → Ajustar ou excluir → Excluir conexão** remove apenas o cadastro
local e recibo, com confirmação. Não apaga conversas, Chrome ou histórico RAG.

[Instalador 0.6.0](https://github.com/Financia-Brasil/browserapi-lab/releases/download/v0.6.0/BrowserAPI-Ubuntu.deb) · [Capturas e limites](docs/design/UX_060_REVIEW.md).
Atualização da versão pública 0.5.1 para 0.6.0 testada. LMArena real/conta pessoal
ainda não homologados; frames isolados não têm este mapa gráfico.
