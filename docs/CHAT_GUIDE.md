# Escolher navegador, escolher chat e corrigir problemas

## O que mudou

O laboratório agora tem um assistente de configuração e um fluxo assistido de
mensagens reais. Os conectores Gemini/LMArena são **hipóteses iniciais**: só o
comando `check` com uma resposta válida pode comprovar funcionamento naquela
configuração e naquela execução. Não são conectores homologados em sites reais
pelo CI.

Não é necessário escrever CSS, colar JavaScript no console ou identificar o modelo.
O modelo é sempre selecionado manualmente no próprio chat.

## Configuração inicial

Depois da instalação descrita no README:

```bash
browserapi-lab configure meu-gemini
```

O assistente pede:

1. Navegador: `chrome`, `msedge`, `chromium` ou `custom`.
2. Chat: `gemini`, `lmarena` ou `custom` com URL HTTPS própria.
3. Login e seleção do modelo, feitos por você no navegador visível.
4. Confirmação das hipóteses de campos, com opção de apontar os campos na página.
5. Autorização para **uma** mensagem sintética de teste.

`custom` como navegador exige caminho absoluto para um binário compatível com
Chromium. Firefox/Safari não são anunciados como suportados. `chromium` usa o
navegador gerenciado pelo Playwright; `chrome`/`msedge` usam o produto instalado.

**Não abre sua sessão pessoal já existente.** Usa perfil exclusivo do projeto,
para preservar suas senhas, histórico e preferências pessoais. O login nesse
perfil separado precisa ser feito uma primeira vez. Nunca exportar ou copiar
cookies do perfil pessoal.

Para cadastrar outro chat, use outro nome. As configurações e os perfis ficam
separados por nome. Para trocar de produto de navegador, prefira outro nome de
configuração e refaça o login no perfil separado.

## Verificar e consultar o resultado

```bash
browserapi-lab check meu-gemini
browserapi-lab status meu-gemini
browserapi-lab chats
```

`check` abre o chat, aguarda você confirmar login/modelo e pede autorização para
uma única mensagem. Sem `s`/`sim`, nada é enviado. Esse teste pode consumir cota
ou créditos do site. `status` e `chats` não enviam mensagens nem abrem navegador.

O recibo informa:

- Resultado e ação sugerida em português.
- Data e navegador/versão observados.
- Compatibilidade **naquela execução**, não disponibilidade futura.
- TTFT observado no DOM, tempo total e overhead de captura. Esses tempos começam
  após a autorização; não incluem login, escolha de modelo nem abertura do navegador.
- Orçamento de captura de 900 ms e resultado separado de desempenho.
- Equivalência a API: `not_measured`, até haver comparação real autorizada.

**Compatível** exige nova mensagem do usuário e nova resposta do assistente que
atenda um desafio JSON com identificador aleatório daquela tentativa. Um JSON
antigo, um eco do prompt ou mais de uma saída válida não são aceitos como sucesso.
O modelo pode não obedecer ao JSON: isso não prova que o site seja incompatível.

Se alterar a configuração, o recibo anterior é invalidado. Se o site mudar sem
alterar o arquivo, o recibo continua sendo apenas histórico: repita `check`.

## Enviar uma mensagem normal

```bash
browserapi-lab ask meu-gemini
```

Digite a mensagem no terminal. O navegador abre, você escolhe/confirma o modelo e
autoriza o envio uma vez. A resposta é exibida no terminal. Conteúdo da pergunta
ou da resposta não é gravado no recibo. Se redirecionar stdout para um arquivo,
esse arquivo poderá conter sua resposta: cuide dele como dado privado.

Cada invocação abre/fecha o navegador, reutilizando o perfil em disco. **Não é um
serviço de agentes com navegador permanentemente quente ou uma API 24/7.** O
benchmark de aba quente mede outro cenário, sem esse custo de abrir/fechar.

No painel gráfico (0.7.0), a mesma mensagem aparece no cartão **Conversa** com
**Copiar última resposta** e **Limpar painel**. Esse texto vive só na memória do
processo: não é gravado, não entra em recibo/telemetria e não é histórico do site.
Limpar o painel não apaga a conversa no provedor. Ver
[UX_070_SPEC.md](design/UX_070_SPEC.md).

## Corrigir uma configuração

```bash
browserapi-lab repair meu-gemini
```

Abra uma conversa que tenha uma mensagem sua e uma resposta visíveis. O mapeamento
é **passo a passo**, e cada pergunta diz qual elemento clicar:

| Passo | Campo | O que clicar |
|---|---|---|
| 1 | Campo de digitação | a caixa de texto de baixo, vazia (não a conversa) |
| 2 | Microfone (opcional) | o ícone de microfone, se existir; responda **Não** se não houver |
| 3 | Botão Enviar | digite algo **sem enviar** e clique na seta/Enviar |
| 4 | A sua pergunta | o balão com o texto que você mandou (não o campo de digitar) |
| 5 | A resposta do chat | o balão da resposta do modelo |

O painel mostra **Passo N de M** e o título do passo. Antes de confirmar, a faixa
mostra **“Vai capturar: …”** com o texto real da área escolhida — é assim que se vê
que o balão inteiro entrou, e não um pedaço. Para mensagens o programa sobe sozinho
ao balão completo (o Gemini, por exemplo, divide a resposta em vários `<span>`).

- `Esc` ou **Pular este campo** pula **só** aquele passo; o mapeamento continua.
- **Cancelar mapeamento** encerra tudo.
- No fim, cada campo pode ser **refeito** sem recomeçar do zero.

**Camadas.** Um balão tem várias camadas dentro (parágrafo, texto, moldura). O
painel mostra em que camada você está e quais textos vão ser capturados, em lista
numerada. **Camada maior** sobe para o balão inteiro; **Camada menor** desce para
o pedaço. Camada interna não conta duas vezes: uma resposta nunca vira duas.

**Três mensagens, conferidas.** Antes de concluir, o programa lê as mensagens já
enviadas e exige pelo menos **três perguntas suas com as três respostas** na tela.
Ele mostra o texto de cada par, na ordem, e recusa quando:

| Problema | Mensagem |
|---|---|
| menos de três de um lado | “encontrei N pergunta(s)…; o mínimo é 3” |
| números diferentes | “N pergunta(s) contra M resposta(s)” |
| duas do mesmo papel seguidas | “mensagens fora de ordem” |
| resposta inclui a pergunta | “aponte a camada menor (só o balão da resposta)” |
| texto repetido | “mensagens com o mesmo texto contadas duas vezes” |

Se não conferir, você pode refazer os dois balões na hora. Continuar sem conferir
é possível, mas o aviso é explícito: o teste pode responder “envio não confirmado”.

Não exige código. Cliques de seleção são interceptados; o teste automatizado
verifica que apontar Enviar com rascunho preenchido não envia a mensagem na fixture.

Após reparar, você decide se autoriza outro teste. Não existe reenvio automático
quando não sabemos se o primeiro envio foi aceito. Confira a conversa antes de
autorizar nova tentativa.

### Diagnósticos típicos

| Resultado | O que fazer |
|---|---|
| Campo/botão não encontrado ou ambíguo | Usar `repair` e apontar o controle correto |
| Rascunho presente | Enviar ou remover manualmente; o programa não o sobrescreve |
| Envio não confirmado | Conferir a conversa: se a sua mensagem apareceu, o envio funcionou. Não reenviar às cegas. Persistindo, reparar o balão da pergunta já enviada |
| Resposta fora do formato | Verificar seleção de saída e se o modelo obedeceu ao pedido |
| Múltiplas saídas válidas | Apontar somente o contêiner de cada resposta do assistente |
| Login expirado | Fazer login e escolher o modelo manualmente |
| CAPTCHA | Resolver manualmente; não contornar a proteção |
| Rate limit | Respeitar o prazo e os limites do site |
| Timeout | Verificar rede, página/modelo e configuração de saída; não significa necessariamente que não houve resposta |
| Perfil em uso | Fechar a outra execução que usa esse chat |

## Onde os dados ficam

Padrão: `~/.config/browserapi-lab/`. Configurações e recibos usam arquivos com
permissão 0600. Perfis ficam no subdiretório `profiles/`. São dados locais privados,
não devem ser versionados ou enviados como artefatos.

Diretório alternativo:

```bash
browserapi-lab --config-dir ~/.config/meus-chats configure meu-chat
```

Não coloque esse diretório dentro de uma pasta pública ou monitorada pelo Git.
Nunca compartilhe arquivos de perfil ou estado de autenticação. Relatórios de
compatibilidade não contêm cookies, prompt, resposta, URL privada ou seletores.

## Limites que exigem mais desenvolvimento/testes

- O fluxo configurável usa seletores CSS no documento principal. Iframes e Shadow
  DOM no novo assistente podem exigir adaptação, mesmo que o laboratório tenha
  testes específicos dessas estruturas.
- Páginas que reutilizam o mesmo nó de saída, em vez de adicionar um novo turno,
  precisam de adaptação. O sistema prefere falhar a aceitar uma resposta antiga.
- Um site pode impedir automação; nesse caso não há garantia de reparo por apontamento.
- Desempenho de API, autenticação real e operação contínua exigem evidência própria.
- As rotas/seletores conhecidos de Gemini/LMArena podem mudar e não são contratos.
