# API local experimental — 0.12.0

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

## `curl` recusou a conexão (erro 7)

`curl: (7) Failed to connect to 127.0.0.1 port 8765` significa que **nada está
escutando**. Não é token errado. As causas, em ordem:

1. **A janela do aplicativo foi fechada.** A API é uma thread do programa
   instalado, não um serviço do sistema: fechou a janela, a porta fecha.
2. **A API não foi autorizada.** Clique em **Autorizar e iniciar API** e confira a
   mensagem do cartão. Se o cartão disser “abra o aplicativo instalado”, você está
   rodando pelo código-fonte — a API só existe no pacote instalado.
3. **A porta 8765 estava ocupada.** Agora isso é informado (“já está em uso por
   outro programa”) em vez de um erro genérico.
4. **Algum chat autorizado não tem teste válido.** Cada chat precisa de recibo
   `compatible_in_this_run` da execução atual.

O botão **Testar conexão** faz exatamente o caminho de um agente (loopback +
chave) e mostra o resultado, sem abrir navegador e sem enviar mensagem.

O teste com `curl` precisa de caminho e chave — a raiz `/` responde 404 de
propósito, e sem `Authorization` a resposta é 401:

```bash
curl -i http://127.0.0.1:8765/v1/models -H "Authorization: Bearer SUA_CHAVE"
```

## Contrato para integradores

- `GET /v1/models`: aliases locais aprovados e `auto`. O alias não comprova o modelo
  remoto: a escolha continua sendo feita na interface do provedor.
- `GET /v1`: índice das rotas (exige a chave). A raiz `/` responde 404 explicando
  qual rota usar — não é “API fora do ar”.

### Rotas

| Rota | Dialeto | Para quê |
|---|---|---|
| `POST /v1/messages` | Anthropic Messages | **Claude Code** e SDKs Anthropic |
| `POST /v1/messages/count_tokens` | Anthropic | contagem de contexto (devolve 0 + explicação) |
| `POST /v1/chat/completions` | OpenAI Chat Completions | SDKs OpenAI e a maioria dos clientes |
| `POST /v1/responses` | OpenAI Responses | CLIs que usam a API nova da OpenAI |
| `POST /v1/completions` | OpenAI legado | clientes antigos, só texto |
| `GET /v1/models` | OpenAI | lista os aliases autorizados |
| `POST /v1/embeddings`, áudio, imagens | — | **501**: a API local só faz conversa em texto |

Autenticação: `Authorization: Bearer <chave>` **ou** `x-api-key: <chave>` (o que o
SDK Anthropic manda). `anthropic-version` e `anthropic-beta` são aceitos e
ignorados. Corpo `gzip` é aceito. Sem CORS para sites externos.

### Usar com o Claude Code

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:8765"   # base SEM /v1
export ANTHROPIC_AUTH_TOKEN="<chave do painel>"
export ANTHROPIC_MODEL="meu-gemini"                  # alias do painel
claude
```

O SDK chama `/v1/messages` sozinho. O painel mostra essas três linhas com botão
**Copiar variáveis** (a chave fica na variável de ambiente, não no texto copiado).

### Parâmetros: aceitos e ignorados, nunca fingidos

O chat do navegador não tem `temperature`, `max_tokens`, `seed`, `top_p`… Aceitar e
**dizer que ignorou** é o que permite uma CLI funcionar; recusar quebrava a chamada
com *“Parâmetro não suportado”*. Cada resposta traz `browserapi.ignored` com a lista
e o cabeçalho `X-BrowserAPI-Ignored`. Campo desconhecido de verdade continua sendo
erro 400, com o nome do campo.

- `messages`/`system`: 1–2000 itens; `content` pode ser texto ou lista de blocos.
  Blocos `tool_use` e `tool_result` viram texto no histórico, para o modelo não
  perder o fio; imagens/áudio/PDF são **omitidos** com marcação.
- `tools`: **emuladas por protocolo de texto** (ver abaixo). `browserapi.tools`
  diz `emulated`.
- `usage`: **zeros** e `usage.browserapi.note` explicando que o site não informa
  tokens. Nenhuma contagem é inventada; `browserapi.context` traz caracteres.
- Streaming (`stream: true`): SSE com a **sequência de eventos** do dialeto
  (`message_start` … `message_stop` no Anthropic; `chat.completion.chunk` +
  `[DONE]` no OpenAI). O texto chega de uma vez, porque a página entrega a resposta
  inteira — é *bufferizado*, não token a token.

### Ferramentas (tools): emuladas, com limites claros

Sem função nativa, o programa instrui o modelo a responder
`{"tool_calls":[{"name":"…","arguments":{…}}]}` e interpreta o que ele escreveu
(`browserapi_lab/tool_calls.py`). Regras:

1. o nome precisa estar na lista enviada pelo cliente — nome desconhecido **não**
   vira chamada;
2. os argumentos precisam ser objeto JSON (string com JSON é aceita);
3. se o modelo responder texto comum, o cliente recebe texto comum e decide.

Consequências honestas: a qualidade depende de o modelo seguir o protocolo; o
`stop_reason` é `tool_use`/`tool_calls` **porque o formato foi reconhecido**, não
porque houve chamada nativa. O agente executa a ferramenta — o programa nunca
executa comando nenhum.

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
