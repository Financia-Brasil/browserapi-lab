# API local experimental — 0.4.0

Esta é uma interface textual **parcialmente compatível** com Chat Completions,
não uma substituição transparente da API OpenAI. Reutiliza a automação validada
pelo laboratório. Sites autenticados, Chrome pessoal e funcionamento 24/7 ainda
não estão homologados. Não contorna login, CAPTCHA, limites ou assinaturas.

## Ativar sem terminal

1. Abra BrowserAPI pelo menu. Configure o chat, entre na conta e escolha o modelo
   manualmente. Conclua o teste autorizado; um chat sem recibo válido não entra na API.
2. No cartão **API local para agentes**, selecione os chats autorizados. Leia o
   aviso: ativar permite envios por agentes com a chave, sem perguntar Sim em cada chamada.
3. Para Chrome pessoal, autorize explicitamente o acesso amplo CDP. Não marque
   headless ou bloqueio de recursos nesse modo. Mantenha exatamente uma aba do chat.
4. Clique **Autorizar e iniciar API**. No cliente de agentes, use a Base URL exibida
   (`http://127.0.0.1:8765/v1`), a chave mostrada no painel e o nome do chat como modelo.
   Esses endereços são do computador que executa o aplicativo, não de um servidor remoto.
5. **Desativar API** impede novas chamadas; não desfaz uma mensagem já aceita.
   **Revogar chave e registro de idempotência** exige ociosidade e desliga a API.

A política e a chave persistem no diretório privado do aplicativo. A API pode
voltar habilitada após reiniciar se os recibos e a configuração continuarem
válidos. A chave autoriza todos os chats/IDs locais: **não é isolamento multiusuário**.
Não compartilhe a chave, não exponha a porta à rede. Não há CORS para sites externos.

## Contrato para integradores

- `GET /v1/models`: aliases locais aprovados e `auto`. O alias não comprova o modelo
  remoto: a escolha continua sendo feita na interface do provedor.
- `POST /v1/chat/completions`: somente `model`, `messages`, `stream`, `documents`
  e `conversation_id`. Autenticação `Authorization: Bearer …` e JSON obrigatório.
- `messages`: 1–2000 itens `{role, content}` textuais. Papéis aceitos: system,
  developer, user, assistant; o último deve ser user não vazio. São serializados
  em texto no chat: **não há hierarquia nativa de papéis nem garantia contra prompt injection**.
- `documents`: extensão opcional, até 100 textos. `conversation_id`: extensão de
  1–64 letras ASCII, números, `_` ou `-`, obrigatória se a retenção estiver habilitada.
- Tools, imagens, Responses API, temperature, max_tokens, stop, response_format e
  demais opções não são implementados e são rejeitados. Clientes que as enviam
  automaticamente precisam permitir desativá-las.
- Resposta JSON Chat Completions com `usage: null`, sem estimar tokens/custo.
  `browserapi.context` informa redução/recuperação; `browserapi.attempts` informa
  fonte, estado de envio e reutilização. SSE (`stream:true`) é **bufferizado**:
  entrega a resposta completa ao terminar, não tokens ao vivo.
- Até 16 MB por corpo HTTP, resposta até 1 milhão de caracteres, orçamento de
  saída do planejador de 24 mil caracteres (não tokens). Entrada combinada do
  planejador até 16 milhões de caracteres. Um worker, uma aba quente, sem fila
  paralela de mensagens. Clientes concorrentes podem receber 409/429.

Exemplo de corpo (a chave é configurada separadamente no cliente):

```json
{"model":"meu-chat","messages":[{"role":"user","content":"Explique este documento"}],"documents":["Texto do documento…"],"stream":false}
```

## Contexto grande e histórico: limites explícitos

**Recuperar trechos locais** habilita busca lexical por blocos, janela recente,
proveniência e um pequeno mapa extrativo de tópicos. Excertos não são uma síntese
semântica verificada. O planejador mantém integralmente system/developer e o pedido
atual; se não couberem, recusa antes de enviar. Documentos e mensagens antigos podem
ser omitidos. Isso permite consultar um acervo maior, **não enviar 1M tokens ao modelo**.
Não há tokenizer do provedor nem garantia de preservar todas as relações do original.

Por padrão, não há histórico de conteúdo em disco. Marcar **Guardar histórico RAG**
exige recuperação habilitada e autoriza explicitamente armazenamento **em texto
NÃO criptografado**, em arquivo JSON privado, sem banco de dados ou dependência adicional.
Guarda apenas o último pedido do usuário, a resposta bem-sucedida e os documentos
fornecidos; não guarda mensagens system/developer como registros de histórico.
Textos podem conter dados sensíveis: permissões 0600 não substituem criptografia de disco.

O limite global é **8 milhões de caracteres/10 mil registros**, com descarte dos
mais antigos. A busca percorre os registros ainda retidos do ID; as últimas quatro
mensagens podem compor a janela recente. O teste automatizado consulta um acervo
sintético persistido de mais de **6 milhões de caracteres**, sem chamar isso de
milhão de tokens. Não é um arquivo completo e ilimitado.

IDs separam somente a recuperação local. **O chat do provedor permanece compartilhado
entre chamadas**, inclusive IDs distintos; não há isolamento/reset automático da
conversa remota. Não use com usuários ou dados que exijam separação de contexto.
`history_saved:false` indica falha de gravação sem repetir o envio já concluído.

**Apagar histórico local** exige ociosidade, desliga a API, limpa as respostas em
memória, remove o arquivo de registros. Não apaga a conversa do provedor,
backups, cópias externas nem garante apagamento forense do armazenamento físico.

## Retries e fallback sem duplicar mensagens

Envie um `Idempotency-Key` estável para cada pedido lógico. Até 16 respostas ficam
em memória; um registro persistente de até 128 hashes/digests impede reenvio após
reinício, mas não recupera a resposta perdida: pode retornar 409. Sem chave explícita,
o corpo é deduplicado por 60 s após término seguro; resultados incertos continuam
bloqueados enquanto o registro for retido. Não é uma garantia infinita de exactly-once.
Não troque de chave automaticamente depois de timeout/409: confira a página.

`auto` usa a ordem autorizada e, com fallback explícito, só passa para **outra origem**
se não começou a editar/enviar. Uma falha de inicialização permite tentar outra fonte;
edição, timeout ou aceitação ambígua impedem fallback. Não troca contas da mesma
origem para contornar quotas. Depois de perder a resposta não há reenvio silencioso.

## Desempenho e privacidade

A aba é mantida quente, inclusive quando o site muda a URL da conversa. Headless
é opt-in somente em perfil dedicado já preparado. O bloqueio experimental remove
imagens/mídia/fontes, preservando CSS/scripts/Fetch/XHR; pode quebrar sites e desabilita
cache via interceptação Playwright. Não há alegação de aceleração universal.
**Replay direto de Fetch/XHR não foi implementado**: falta prova segura de protocolo,
autorização e ausência de duplicação.

Tempos reais de inicialização/abertura e etapas do envio entram na telemetria por
fonte. Os testes de fixture não equivalem a benchmark de conta real ou laptop de 4 GB.
O dashboard não inventa tokens, custos ou equivalência à API oficial. Chaves e conteúdo
não entram nos logs de acesso; apenas hashes limitados ficam no registro de replay.
O Chrome pessoal nunca recebe essas otimizações nem é iniciado em duplicidade.

As atualizações automáticas do canal estável permanecem ativas, com espera por tarefas
HTTP e rollback de inicialização. Detalhes e limites: [guia Ubuntu](UBUNTU.md).


### Medição sintética registrada (2026-10-26)

CI [40350990553](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40350990553),
[amostras completas](../results/ci/40350990553/resource-modes.json): Chromium em
runner de CI, três chamadas por modo (uma fria, duas quentes). Tempos abaixo são
da chamada completa, incluindo a resposta sintética, **não só captura/startup**.

| Modo | Chamada fria | Mediana das duas quentes |
|---|---:|---:|
| Visível | 2929 ms | 1989 ms |
| Headless | 2579 ms | 2014 ms |
| Headless + filtro | 2624 ms | 2025 ms |

Nesta amostra pequena não houve ganho de latência quente com headless/filtro.
Por isso não ativamos otimizações automaticamente. Não é comparação estatística,
medição de conta real nem prova de economia de RAM/CPU. O teste também verificou
reúso e confirmação de envio nos três modos.
