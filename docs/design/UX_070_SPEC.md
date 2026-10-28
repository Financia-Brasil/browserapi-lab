# 0.7 — a resposta aparece na conversa do painel

## Por que

Até a 0.6.1, quem usava **Conversar** recebia a resposta dentro de
“Ver detalhes da operação”, um `pre` recolhido com o log técnico. O texto existia,
mas parecia diagnóstico e não conversa: não dava para reler, copiar nem comparar
pergunta e resposta com calma. Nada disso mudava a conversa do site; faltava
exibição no programa.

## O que muda para quem usa

Na tela **Conexões**, abaixo de **Meus chats**, aparece o cartão **Conversa**:

- cada envio feito por **Conversar** vira um turno “Você enviou” e cada resposta
  validada vira “Resposta capturada da página”, com data/hora e o tempo da troca;
- **Copiar última resposta** copia o texto completo da última resposta;
- **Limpar painel** apaga apenas a exibição local, com confirmação explícita de
  que a conversa do site **não** é apagada;
- o cartão troca de conteúdo ao selecionar outra conexão.

O texto vem da página, não de uma API: continua valendo que a resposta é capturada
por DOM, que o modelo é escolhido manualmente e que o site mantém o contexto das
mensagens anteriores.

## Contratos técnicos

| Peça | Regra |
|---|---|
| `transcript.Transcript` | memória do processo, uma fila por conexão, sem arquivo, sem recibo, sem telemetria |
| `GET /api/conversation?name=` | exige token, Host/Origin locais, `Cache-Control: no-store`; 400 sem nome inválido/ausente, 404 para conexão não salva |
| `POST /api/conversation/clear` | exige token e ociosidade; remove só o texto dessa conexão |
| `/api/state` | informa apenas `turns`, `revision`, `characters`, `dropped`; o texto nunca trafega no estado |
| `check(record=...)` | chamado **somente** após mensagem enviada com resposta nova validada (`status == success` e texto não vazio); verificação sem mensagem da pessoa nunca entra |
| Exclusão de conexão | apaga também o texto exibido daquele cadastro |
| Recibo/telemetria/relatório | continuam sem pergunta e sem resposta |

Uma falha ao exibir não altera o resultado do envio: o recibo continua sendo o do
teste e a mensagem avisa que o painel não conseguiu mostrar o texto. Nada é
reenviado.

## Orçamento e descarte

- 40 mensagens (20 turnos) e 120 mil caracteres por conexão.
- O descarte remove **pares** pergunta/resposta, para não deixar metade de um turno.
- O turno mais novo nunca é descartado; se um texto passar de 40 mil caracteres,
  ele é cortado com aviso visível — não em silêncio.
- O total em memória depende do número de conexões salvas. Reiniciar o programa
  ou aplicar uma atualização apaga a conversa do painel.

## Segurança e privacidade

- Renderização só por `textContent`: HTML vindo da página não é interpretado,
  não executa script e não insere imagem/iframe.
- O texto não vai para recibo, telemetria, `/api/state`, log de operação nem
  arquivo de configuração.
- Não é histórico do site, não é o RAG da API local e não é serviço multiusuário.
- Limpar ou reiniciar **não** apaga a conversa no provedor.

## Aceite

- [x] turno só aparece depois de resposta validada; recusa, timeout, ambiguidade
      e resposta antiga não entram;
- [x] verificação automática (`check`) não entra na conversa;
- [x] texto entra como texto, inclusive etiquetas HTML da página;
- [x] endpoints exigem autenticação local e respeitam operação em andamento;
- [x] `/api/state` não carrega o texto;
- [x] excluir conexão apaga o texto daquela conexão;
- [x] orçamento, descarte em pares e corte com aviso testados sem navegador;
- [x] troca de conexão, copiar e limpar verificados no DOM emulado;
- [ ] captura em Chromium real da jornada nova (workflow de navegador);
- [ ] uso assistido em Gemini/Arena reais.

## Limites desta etapa

- Não há streaming ao vivo na conversa: o turno aparece quando a resposta termina
  e é validada, porque é isso que o observador confirma.
- Chamadas feitas pela **API local** e por agentes não entram nesta conversa; elas
  têm registro próprio de idempotência e histórico opt-in.
- A conversa não é salva em disco; um reinício ou atualização do programa a apaga.
- Seletores continuam hipóteses: se o campo ou a resposta não forem reconhecidos,
  vale o fluxo de reparo já existente.
- Sites autenticados e o Chrome pessoal continuam **não homologados** por este marco.
