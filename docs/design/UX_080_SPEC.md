# 0.8 — correções do uso real + Atividade em gráficos

Relato do usuário que originou este marco (resumo fiel):

1. “Funcionou tudo menos o sistema identificar a confirmação” — apareceu
   **Envio sem confirmação**, com 6619 ms, perfil `Default` confirmado.
2. “Não dá pra excluir os modelos configurados.”
3. No mapeamento aparece “Apontar mensagem do usuário?” sem dizer **qual**
   elemento clicar, e sem instrução de enviar algo antes.
4. Quer a aba **Atividade** com gráficos de erros, consumo/contabilidade de
   tokens “e muito mais”, sem os blocos de texto.
5. Quer **menos texto e mais configuração útil** (ex.: cartões de Configurações).

## 1. Envio sem confirmação (o problema mais grave)

**Causa provável, com base no código e no relato.** A confirmação exigia que o
último balão do usuário tivesse **texto idêntico** ao que foi preenchido, dentro de
5 segundos. Chats reais normalizam o texto renderizado (espaços, `NBSP`, caracteres
invisíveis) e podem demorar para pintar o balão. O prompt de verificação tem
quebras de linha e aspas — justamente onde a normalização acontece. Quando a
comparação falhava, o programa dizia “envio sem confirmação” mesmo com a mensagem
na tela. **Não é possível afirmar que foi só isso no seu computador**; o teste
iça uma página que reproduz o cenário.

**O que mudou**

| Antes | Agora |
|---|---|
| texto idêntico, byte a byte | comparação com `NFKC` + remoção de invisíveis + espaços colapsados |
| só contagem de nós | aceita lista virtualizada que reutiliza o mesmo nó (texto mudou) |
| 5 s para aparecer | até 9 s (limitado por `timeout_ms` da conexão) |
| nada sobre o campo | mensagem nova **e** campo esvaziado também confirmam (site consumiu o rascunho) |
| — | recibo mostra a evidência em `diagnostics.send_evidence` |

**O que continua bloqueado, de propósito:** texto divergente com o campo ainda
preenchido continua sendo ambiguidade, e campo esvaziado sozinho **não** confirma
envio. Nenhum caso dispara reenvio automático. A mensagem do erro agora é: “Enviamos,
mas o site não confirmou a mensagem — olhe a conversa; se a sua mensagem apareceu,
o envio funcionou”.

Contraprova testada: reescrever o balão para outro texto **e** manter rascunho no
campo resulta em `send_state = unknown`, nunca sucesso.

## 2. Excluir conexões

- **Excluir** virou botão visível na linha de ações de cada chat (antes só existia
  dentro de “Ajustar ou excluir”), com estilo de ação destrutiva.
- A confirmação cita o nome: `Excluir a conexão "meu-chat"? … Seu Chrome, sua conta
  e suas conversas no site não são apagados.`
- Continua exigindo autenticação local, aplicação ociosa e API desativada; apaga
  cadastro, recibo e a conversa exibida daquele chat — nada do navegador.

## 3. Apontamento sem ambiguidade

Perguntas reescritas e ajuda ao lado da pergunta:

| Elemento | Pergunta |
|---|---|
| campo de digitar | “Apontar o campo onde você digita a mensagem (a caixa de texto vazia)?” |
| balão da pessoa | “Apontar **A SUA PERGUNTA JÁ ENVIADA**: o balão com o texto que você mandou (não o campo de digitar)?” |
| resposta | “Apontar **A RESPOSTA DO CHAT**: o balão da resposta que o modelo deu?” |
| Enviar | “Apontar o botão enviar (Enviar / seta), depois de digitar sem enviar?” |

Antes das perguntas sobre a conversa, o programa instrui: *envie você mesmo uma
pergunta no chat, espere a resposta e volte; o campo onde se digita não é a
pergunta já enviada.*

## 4. Atividade

A aba virou um painel de gráficos em SVG gerado no próprio painel (sem biblioteca
externa, sem `innerHTML`):

1. **Resultados por tipo** — rosca com sucesso, sem autorização, envio não
   confirmado, login, limite, verificação, erros, com legenda textual.
2. **Duração por operação** — barras das últimas 14 operações.
3. **Consumo medido** — caracteres enviados e recebidos por operação.
4. **Etapas do último resultado** — navegador, aba, pré-voo, envio, espera, leitura.
5. **Sucesso acumulado** — linha da taxa ao longo das operações.
6. **Estado por chat** — última observação, sem virar heartbeat.

Cada gráfico tem `aria-label` com os valores e legenda/números embaixo; tabelas e
parágrafos de “análise de gargalos” saíram da vista principal (ficaram recolhidos).

**Sobre tokens:** o site não informa `usage`. O painel mede **caracteres** de
verdade e mostra “≈ N tokens por estimativa grosseira (4 caracteres/token), não é o
número do provedor”. O cartão diz **Não medido**. Nada de custo, quota ou consumo
inventado. A medição é do par pergunta+resposta: um valor implausível descarta o
par inteiro em vez de virar estatística.

## 5. Menos texto

- **Configurações**: componentes, atualização e versão em três cartões curtos; o
  texto longo virou um “O que este programa não faz” recolhido.
- **Sua próxima ação**: uma linha de ajuda contextual por pergunta; o aviso genérico
  saiu. “Detalhes da operação” continua recolhido.

## Aceite

- [x] confirmação tolera normalização do site e reuso de nó; contraprova mantida;
- [x] exclusão visível, autenticada, com nome na confirmação;
- [x] perguntas de apontamento dizem qual elemento e o que fazer antes;
- [x] aba Atividade com seis gráficos, legenda textual e `aria-label`;
- [x] consumo em caracteres + estimativa declarada; tokens seguem `Não medido`;
- [x] configurações e próxima ação com menos texto;
- [x] HTML do painel validado por parser (id sem aspa não passa mais);
- [ ] uso assistido em Gemini/Arena reais — depende da sua conta e permissão.

## Limites

- A causa exata do seu “sem confirmação” não pode ser provada daqui: os testes
  reproduzem normalização e atraso de renderização, não a sua conta.
- Confirmação por “campo esvaziado + balão novo” é mais permissiva que texto exato;
  o efeito é deixar de chamar de falha um envio visível, nunca duplicar envio.
- Gráficos usam apenas a janela de 100 operações deste processo; reiniciar zera.
- Estimativa de tokens é grosseira e não substitui `usage` do provedor.
- Sites autenticados e Chrome pessoal continuam **não homologados**.
