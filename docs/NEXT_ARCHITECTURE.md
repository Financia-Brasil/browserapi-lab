# Próxima arquitetura: navegador autorizado como backend local

Decisão de 2026-10-25. O usuário delegou a escolha do primeiro marco. Começamos
por **medir antes de otimizar**, não pela API final. Este documento é um plano de
engenharia e critérios de aceite, não uma afirmação de funcionalidades prontas.

## Estado e sequência

| Marco | Escopo | Estado |
|---|---|---|
| M1 | Tempos por etapa e dashboard privado, limitado | Implementado em 0.2.0+ubuntu1; evidência de testes em PRODUCT_VALIDATION.md |
| M2 | Descoberta/seleção segura de sessões e abas existentes | Planejado; conexão Chrome existente atual continua experimental |
| M3 | Otimização medida: sessão aquecida, headless e recursos | Planejado; nenhum bloqueio ou replay de rede ligado |
| M4 | Atualização automática de código ABI 1 | Implementada em 0.3.0; regras independentes permanecem planejadas; [contrato](UPDATES.md) |
| M5 | API local compatível com subconjunto OpenAI e roteamento seguro | Planejado; não há endpoint de LLM neste marco |
| M6 | Histórico pesquisável, RAG e orçamento de contexto | Planejado; não há contexto de 1M tokens implementado |

A ordem pode mudar após os dados do M1. Cada marco exige testes e aprovação de
escopo antes do próximo. Os módulos futuros não estão sendo entregues como
subsistemas parcialmente ativos ou opções escondidas.

## M1 — o que se mede agora

- `browser_start_ms`: entrada na sessão Playwright, inclusive conexão/consentimento
  nativo quando houver. Não é só o custo de criar um processo.
- `page_open_ms`: abrir uma página ou localizar a aba existente.
- `preflight_ms`, `send_pipeline_ms`, `response_wait_ms`, `parse_ms`: fases
  sequenciais da troca autorizada. Espera inclui estabilização do DOM, não é
  medida isolada de inferência do modelo.
- `fill_ms`/`send_ms`: subtempos do pipeline, não somar novamente.
- `total_ms`: troca de mensagem, incluindo pré-voo; exclui abertura, perguntas
  humanas anteriores, encerramento da sessão e limpeza final do observador.
- `ttft_dom_ms`: primeiro conteúdo observado no DOM, **não primeiro token real**.
  `capture_overhead_ms` é tempo desde a última mutação, não CPU de captura.
- `operation_wall_ms`: tarefa do painel inteira, incluindo abertura, perguntas e
  encerramento. `manual_wait_ms` mede somente espera por respostas no painel;
  consentimento nativo/login dentro do navegador não pode ser subtraído por isso.

Tempos de falha são registrados até a fase alcançada; fases não executadas ficam
ausentes. Exceções anteriores a um recibo contam como erros de operação, não
como sucesso nem requisição concluída com latência zero. Interromper não desfaz
um envio. Nenhum temporizador produz reenvio.

Média e P95 (nearest rank) usam somente resultados com `total_ms` numérico.
Sucesso/falha e taxa usam recibos conhecidos, exceto `not_authorized`. Incluem
verificações sintéticas e mensagens do painel, não chamadas a uma API pública.
Os denominadores são mostrados. Contadores cobrem **as últimas 100 operações do
processo**, não vida útil; gráfico exibe até 30 amostras. Reiniciar zera tudo.

O estado de cada fonte é a última observação na janela, não heartbeat. Após
cinco minutos ela é antiga. Configurar/mudar sessão sem novo resultado invalida
um Online anterior. Não se envia mensagem para monitorar disponibilidade. O
contador de tokens é `null`/“Não disponível”: não se infere consumo de caracteres,
TTFT ou tamanho da resposta. Não se mede CPU/RAM/tráfego neste marco.

Privacidade: lista branca de nome local validado, operação, status, tempos e data;
sem prompt, resposta, URL, seletor, conteúdo de exceção, cookies ou credenciais
no histórico. Só memória do processo, sem arquivo de telemetria/serviço externo.
Os recibos existentes continuam guardando metadados e tempos, não conteúdo. O
chat de teste já existente no painel permanece integrado ao mesmo fluxo e
consentimento. O painel não cria segundo browser para coletar essas métricas.

## M2 — perfis e sessões sem destruir o navegador pessoal

Inventário somente de metadados de instalações e diretórios de perfil permitidos
pelo mesmo usuário. Mostrar navegador, diretório/perfil, nome e estado observado;
não ler bancos Cookies/Login Data, copiar credenciais ou exportar sessões.
Selecionar metadados não implica estar conectado à conta correta.

Separar explicitamente:

1. Perfil dedicado, sob lock cooperativo do aplicativo.
2. Chrome pessoal em execução, conexão suportada e consentida pelo Chrome.

Nunca iniciar dois processos sobre o mesmo user-data-dir, desbloquear arquivos do
Chrome ou cair silenciosamente em Guest/perfil novo. Se não houver endpoint
suportado/aba única correspondente, parar e explicar. Selecionar perfil no disco
não garante que esse perfil seja isolável pelo endpoint CDP; isso precisa ser
validado por versão, instalação e sistema. Se houver múltiplas contas/abas,
solicitar seleção explícita, não inferir por e-mail ou copiar cookies.

Aceite: matrizes de Chrome suportado/sem endpoint, perfis múltiplos, ocupado,
permissão negada, aba ausente/ambígua, consentimento revogado e desconexão que
não fecha abas pessoais. Validação real no Linux Lite permanece necessária.
As referências oficiais já usadas para a conexão experimental estão no guia
Ubuntu; a restrição antiga de porta no perfil padrão não deve ser confundida
com o fluxo nativo de consentimento Chrome 144+.

## M3 — desempenho com comparação controlada

Estabelecer baseline frio/quente por site, versão e modo, incluindo taxa de
sucesso, latência de fases, CPU/RAM e bytes (estes três ainda sem implementação).
Reusar sessão/aba aquecida com um proprietário Playwright e concorrência 1.
Login e seleção de modelo continuam manuais; headless só será opt-in após login,
quando compatível. Não aplicar headless ao Chrome pessoal já aberto.

Experimentos independentes: imagens, fontes, mídia e depois CSS/scripts por
origem/recurso mapeado. Não bloquear genericamente CSS: visibilidade, geometria,
controles e sinais de término podem mudar. Não bloquear scripts sem provar que
não participam de autenticação, envio, stream ou composição. Cada variante tem
controle equivalente, amostras repetidas, falhas explícitas e rollback por site;
não prometer ganho percentual sem medição. Preservar seletor semântico e prova de
nova mensagem do usuário, detecção de bloqueios e extração rica.

Fetch/XHR pode ser **investigado**, não está ativado. Exige avaliar suporte,
permissões e termos do provedor, acoplamento a tokens/CSRF/protocolo efêmero,
cancelamento e confirmação do envio. Não replay de endpoints privados para
contornar CAPTCHA, autenticação, limite ou restrições. Se não houver mecanismo
permitido e estável, manter UI ou integração oficial autorizada.

Aceite: zero envio duplicado, mesma correção de resultados, perfis intactos,
nenhum aumento oculto de incompatibilidade; relatório comparativo antes de ligar
qualquer otimização por padrão. Uma única execução de Gemini em 9838 ms relatada
pelo usuário não é baseline estatístico nem garantia de performance futura.

## M4 — distribuição e atualização sem misturar versões

**Atualização 0.3.0:** parte de código/GUI implementada conforme [UPDATES.md](UPDATES.md).
O texto abaixo registra o desenho original e metas adicionais, não substitui o
contrato ABI 1. Assinatura independente e regras quentes não foram entregues.

Proposta: testes em PR/branch; em main aprovado, workflow determina incremento
SemVer a partir de sinal explícito/convenção validada, cria tag e release com
artefatos, changelog e checksums. Commit de documentação não deve publicar patch
vazio; impedir tags duplicadas e publicação antes dos checks obrigatórios.
`0.2.0+ubuntu1` é a identificação atual; versão Debian e SemVer precisam de
mapeamento e testes próprios de ordenação (metadados + não ordenam SemVer).

GUI futura consulta manifesto com intervalo/backoff, mostra versão, origem,
notas e oferece download autorizado. HTTPS e hash detectam corrupção; hash no
mesmo canal **não** substitui autenticação de release. Definir cadeia de confiança
assinada/gerenciador de pacotes e distribuição da chave antes de autoexecutar
código baixado. Não implementar criptografia caseira nem elevar privilégios
silenciosamente. Neste marco não há checagem/download automático.

Separar dois tipos de atualização:
- **Regras como dados**: esquema/versão, validação, escopo por origem, sem JS/Python
  arbitrário. Download temporário, validação, ativação atômica só entre tarefas,
  snapshot imutável por requisição, histórico e rollback da geração anterior.
- **Código**: não `importlib.reload` em worker ativo. Propor supervisor + worker
  versionado, drenar fila, negociar protocolo, reciclar worker quando ocioso e
  fazer rollback. Investigar posse da sessão aquecida e conexão existente antes
  de prometer atualização sem desconexão. Servidor/UI podem permanecer abertos,
  mas nunca trocar código no meio de um envio nem fechar Chrome pessoal.

Aceite: pacote/regra inválido, rede cortada, versão velha, concorrência com envio,
rollback e incompatibilidade de protocolo. Até lá, atualização gráfica atual
continua exigindo encerrar o runtime antigo/reiniciar, com diagnóstico de versões.

## M5 — serviço local e fallback não duplicante

Evolução proposta: GUI → serviço local autenticado → fila serial/roteador →
adaptadores por site → uma sessão/aba aquecida. Introduzir contratos internos de
requisição, resultado, tentativa e capacidade antes de expor endpoints. Somente
após aprovação do laboratório: `/v1/models`, `/v1/chat/completions`, erros e SSE
em subconjunto explicitamente documentado. Sem alegar paridade para tools,
imagens, logprobs, IDs de modelos reais ou usage não fornecido.

API só loopback por padrão, autenticação local, limites de corpo/fila/origem e
consentimento explícito para política de automação. Modelo da UI é manual;
alias configurado não comprova versão de modelo remoto. Não exportar endpoint
público/LAN por padrão. Testes de contrato com cliente compatível, streaming,
backpressure, cancelamento e desligamento são gates, não funcionalidades atuais.

Fallback exige estados de envio separados:
- **não enviado**: pode tentar outra fonte permitida, com orçamento de tentativas;
- **rejeitado explicitamente**: aplicar cooldown/backoff e política de permissão;
- **aceito/confirmado**: esperar ou devolver erro com identificação da tentativa;
- **ambíguo**: nunca repetir automaticamente. Timeout ou compositor vazio sozinhos
  não provam que o provedor não recebeu a mensagem.

429 só é classificado quando há sinal confiável, não adivinhado de todo erro.
Respeitar Retry-After quando disponível legitimamente, limites e consentimentos.
Fallback não deve servir para burlar quotas. Não misturar respostas de fontes
após começar um stream. Expor fonte/tentativa efetiva; reenvio ou custo potencial
adicional exigem política explícita. Circuit breaker não envia mensagens de
sondagem pagas. Acesso à fonte seguinte não ganha login automático.

Aceite: falha antes/depois do clique, confirmação atrasada, timeout ambíguo,
429, revogação de consentimento e cancelamento. Invariantes: no máximo um envio
potencialmente aceito sem decisão explícita; concorrência global 1; nenhuma
resposta antiga atribuída à tentativa nova. Atualmente **não há fallback**.

## M6 — orçamento de contexto, não um falso modelo de 1M tokens

Meta: pesquisar histórico equivalente a ~1M tokens armazenados localmente,
selecionando uma janela pequena para o contexto real do modelo. Isso não amplia
a janela nativa e pode perder detalhes. Entrada >30k exige política por fonte;
32 mil **caracteres** aceitos pelo formulário atual não são 32 mil tokens.

Pipeline proposto: validar/preservar mensagem atual → separar instruções de
conteúdo recuperado → medir com tokenizer conhecido quando disponível → janela
recente + resumos por tópico + recuperação de trechos relevantes → reservar
saída/margem → verificar orçamento antes do envio. Se tokenização/capacidade
forem desconhecidas, reportar estimativa e limites conservadores, não contagem
exata nem aceitação garantida. Não truncar silenciosamente instruções essenciais.
Se ainda não couber, retornar erro/orientação ou pedir resumo autorizado.

Começar avaliando recuperação lexical local e armazenamento leve stdlib; só
adotar embeddings/vetor/DB adicional após medir necessidade, RAM e dependências.
Resumos têm proveniência/versão e links para trechos originais; resumo não é fonte
infalível. Conteúdo recuperado é dado não confiável, não instrução de sistema.
Gerar resumos por modelo é uma nova chamada real: orçamento e autorização prévios,
não mensagens ocultas no navegador. Avaliar recall, fidelidade por tópico,
continuidade, latência e resistência a prompt injection em históricos sintéticos.

Persistir conversas é uma mudança de privacidade, não extensão da telemetria.
Exige opt-in, separação por usuário/conversa, retenção/apagar/exportar, permissões
de arquivo e estratégia de proteção em repouso. Não guardar histórico privado no
Git/relatórios nem enviá-lo a serviço de embedding sem consentimento. Testar
isolamento e deleção. Só então medir corpus de 1M, sem pôr esse corpus no repo.

## Gates globais

Playwright + stdlib/unittest continuam sendo a base desta entrega. Sem banco,
Docker, Node, Selenium, FastAPI, novo serviço ou coleta remota neste marco.
Manter uma operação e navegador por vez, autorização e modelo manuais, sem
CAPTCHA/auth/Cloudflare bypass. Testes sintéticos de Actions não autenticam
Gemini/LMArena nem comprovam Chrome pessoal ou hardware de 4 GB. Cada promoção
precisa de evidência reproduzível, limitações e pacote correspondente ao código.
