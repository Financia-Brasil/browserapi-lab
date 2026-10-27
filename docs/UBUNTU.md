# BrowserAPI no Ubuntu — sem terminal

Interface experimental para configuração e teste de chats. **Não é um serviço de produção homologado.** A partir de 0.4.0 existe API local opt-in experimental.

## Instalar e abrir

Você informou **Linux Lite 7.2**. Essa distribuição usa a base Ubuntu 24.04,
portanto é um alvo esperado para este pacote, mas não foi instalada uma sessão
Linux Lite completa para homologação. O teste automatizado usa Ubuntu 24.04.
Fonte da base: https://www.linuxliteos.com/forums/showthread.php?tid=9251


- Destinado inicialmente ao **Ubuntu 24.04 ou mais recente, com Python 3.11+**. Ubuntu 22.04 padrão não atende ao requisito; não atualize o Python do sistema para contornar isso.
- Baixe o arquivo **BrowserAPI-Ubuntu.deb** entregue junto com esta orientação.
- Abra o arquivo com o **instalador de pacotes** do Ubuntu e escolha **Instalar**. O Ubuntu pode pedir a senha de administrador na janela do próprio sistema. Nunca envie essa senha no chat.
- Procure **BrowserAPI** no menu de aplicativos e abra.
- Algumas instalações do Ubuntu não têm um programa gráfico que abra arquivos `.deb`. Nesse caso, informe sua versão do Ubuntu e o que aparece ao abrir o arquivo; não é necessário tentar comandos. A instalação gráfica varia entre versões e não foi homologada em um desktop Ubuntu do usuário.

O pacote não instala nada durante a montagem e não contém scripts de instalação privilegiados. O gerenciador de pacotes resolve as dependências declaradas e pede a autorização local necessária. O programa deve rodar como usuário normal, nunca como administrador.

## Atualizar uma instalação existente

Baixe o novo `.deb` e abra no instalador de pacotes, escolhendo atualizar/instalar.
Depois salve seus trabalhos e reinicie o computador, para encerrar a versão antiga
que pode continuar na memória mesmo depois de fechar a aba do painel. Abra
BrowserAPI novamente pelo menu. Não é necessário apagar seus perfis/configurações.

### Se o Google recusar o login

O Chrome controlado por automação pode ser recusado pelo Google, inclusive quando
é o Chrome oficial instalado. O usuário reportou essa recusa no uso real desta
versão inicial. Não peça repetidamente o login nem avance ao apontamento nesse
estado. A atualização identifica a mensagem conhecida (português/inglês na página
de contas Google) e interrompe o fluxo com explicação, mas **não libera o login**.
Não desative proteções da conta, não copie cookies e não compartilhe credenciais.
Não se garante uso do Gemini por este mecanismo.

### Se Enviar só aparecer depois de digitar

A verificação agora preenche o campo somente após autorização e, então, espera
até três segundos por um botão Enviar único, visível e habilitado. Só então tenta
clicar uma vez e exige evidência de uma nova mensagem sua. Se o botão continuar
indisponível/ambíguo, não clica nem reenvia; pode restar um rascunho. Confira a página
antes de autorizar qualquer outra tentativa. Essa correção cobre uma falha interna
reproduzida na fixture, não comprova que explica todo detalhe do site real reportado.

## Na janela do programa

1. Na primeira vez, clique em **Preparar BrowserAPI** e confirme o download. Isso cria um ambiente privado do usuário e baixa Playwright/Chromium. Requer internet e pelo menos 1,5 GB disponíveis. Não instala Chrome nem Edge.
2. Escolha o **navegador** e o **chat**. Dê um nome para salvar; use nomes diferentes para navegadores/chats diferentes.
3. Clique em **Abrir e configurar**. Na outra janela, faça login e escolha o modelo. No modo separado, seu perfil pessoal não é usado e é normal precisar entrar novamente. No modo Chrome já aberto, a conexão é autorizada e reutiliza a sessão existente.
4. Volte ao painel e clique em **Continuar**. Responda aos botões e, se solicitado, aponte os campos na janela do chat. Não é preciso escrever seletores ou código. Esc cancela o apontamento atual.
5. Autorize **uma mensagem de teste**, somente se estiver de acordo. O resultado aparece no painel, com uma orientação caso não funcione.

Depois, use **Testar agora** para uma nova verificação ou **Corrigir campos** se a interface mudar. Para escrever uma mensagem, selecione o chat salvo e use **Conversar**; haverá outra confirmação antes do envio. As respostas são texto na própria janela; não são interpretadas como HTML.

**Interromper operação** cancela a espera por confirmação, seleção e observação. Downloads são encerrados. Operações internas do navegador já iniciadas podem levar até o timeout para voltar. Interromper **não desfaz uma mensagem já enviada**. Não há reenvio automático.

## Se não funcionar

- **Chrome/Edge não abre:** confirme se esse produto está instalado. Ou prepare e escolha **Chromium do BrowserAPI**, salvando com outro nome.
- **Não encontra o campo ou a resposta:** clique em **Corrigir campos** e aponte os controles corretos na janela do chat.
- **Login, CAPTCHA ou limite do site:** resolva manualmente ou aguarde. Não há contorno automático.
- **Já existe um perfil aberto:** feche a outra execução do projeto que usa aquele chat.
- **O teste não confirma envio/resposta:** confira a conversa antes de autorizar outra tentativa, para não duplicar uma mensagem.
- **Download falhou:** verifique a conexão e o espaço disponível; use Preparar novamente. O painel não mostra exceções que possam conter dados privados.

## Privacidade e limites

O painel escuta somente em `127.0.0.1`, com chave aleatória por execução e proteção de origem. Não é acessível pela rede e é distinto da API textual experimental, que usa porta e chave próprias; veja [API local](LOCAL_API.md). A janela de controle abre no navegador padrão; o navegador selecionado no formulário é o que abre o chat automatizado.

Configurações, recibos e perfis exclusivos ficam em `~/.config/browserapi-lab/`. O ambiente de execução fica em `~/.local/share/browserapi-lab/` (ou em `$XDG_DATA_HOME/browserapi-lab/`). Esses diretórios podem conter sua sessão de login: não os compartilhe. O recibo não inclui mensagens, cookies ou credenciais. Mensagens/respostas exibidas no painel ficam temporariamente na memória até outra operação ou o processo encerrar.

Fechar a aba do painel não encerra o processo local: abrir BrowserAPI de novo no menu reabre o mesmo painel, sem duplicar o perfil. Sair da sessão Ubuntu encerra os processos. A remoção do pacote pelo gerenciador gráfico não apaga seus dados pessoais automaticamente.

O teste sintético não equivale a homologar Gemini/LMArena autenticados, todos os navegadores, todas as versões do Ubuntu ou comparar com uma API real. Sites externos podem mudar. Nenhuma instalação foi feita no computador do usuário nesta sessão.

## O que foi verificado nesta entrega

- Código validado: `7020ea3`; [Actions 40153757793](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40153757793), aprovado.
- Ubuntu 24.04 em CI: **244 testes, 127,108 s, sem falhas, 1 ignorado** (cenário de ausência de navegador, pois havia navegador instalado).
- Formulário real no painel, segundo Chromium visível sob Xvfb, autorização por botões, configuração e nova verificação com recibo de sucesso na fixture. Cancelamento antes da autorização, negativa, proteção contra HTML executável e orientação de reparo também exercitados.
- Instalador montado, extraído e importado fora do checkout; dependências resolvidas em **simulação**, sem instalar o pacote no sistema.
- Evidência sanitizada: `results/ci/40153757793/gui-flow.json`.
- Preparação com downloads na máquina do usuário, instalação gráfica via gerenciador do Linux Lite e sessão autenticada Gemini/LMArena **não foram executadas** aqui. Não se afirma homologação completa desse desktop.

As primeiras execuções encontraram uma falha no preparo da página sintética do teste: uma substituição de HTML também alterava a string interna do iframe. A fixture foi corrigida, sem relaxar a validação de URLs ou a exigência de autorização. A execução final acima passou.


## Correção após relato de uso real — versão 0.1.0+ubuntu2

O usuário reportou recusa do login Google no navegador controlado e falha de
reconhecimento de Enviar mesmo após apontamento. O bloqueio do Google continua
sem solução garantida: o programa apenas reconhece o aviso conhecido e impede
continuar a configuração nesse estado. Nenhum mecanismo de autenticação ou
proteção foi contornado.

Foi corrigido um defeito reproduzível: exigir Enviar visível antes de preencher.
Agora, após autorização, preenche e só ativa um botão único, visível e habilitado,
com espera limitada. Se falhar, não ativa nem reenvia e informa possível rascunho.
Isso não demonstra que essa era a única causa do erro no Gemini do usuário.

Validação: [Actions 40156336579](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40156336579),
**SUCCESS, 248 testes em 120,867 s, 1 ignorado**, código `9a59cf6`. Inclui botão
oculto/ausente até digitar, ambiguidade sem envio, rascunho preservado e recusa
Google em página sintética UTF-8 antes do apontamento. O código de execução do
instalador publicado é idêntico ao desse commit; mudanças seguintes só adicionam
documentação, evidências e teste de aviso em inglês (não incluído nessa bateria
completa). Montagem/extração do pacote e simulação de dependências aprovadas.
Não houve novo login autenticado no Google nem execução no computador do usuário.


## Versão 0.1.0+ubuntu3 — microfone/Enviar e Chrome já logado

### Apontar o estado correto do botão

Alguns chats exibem microfone enquanto o campo está vazio e Enviar quando há
texto. Ao usar **Corrigir campos**, o painel pode pedir autorização para escrever
um rascunho temporário **sem enviar**. Aceitando, aponte o botão no estado
**Enviar**. O rascunho do programa é removido apenas se continuar idêntico; se
você alterar o texto, sua edição é preservada. Um rascunho que já existia não é
substituído. Esc cancela o apontamento. Enter fica bloqueado durante a seleção.
O programa recusa controles explicitamente identificados como microfone/voz,
tanto no apontamento quanto antes do clique de envio. Isso não é reconhecimento
universal de qualquer ícone ou de toda mudança possível do site.

### Usar seu Chrome pessoal — referência do fluxo anterior (veja 0.5.1 ao final)

Esta opção atende ao pedido explícito do usuário de usar o perfil cotidiano,
sem copiar cookies e sem lançar outra instância sobre seu diretório de perfil.

1. Use Chrome **144 ou mais recente**, já aberto no perfil/conta desejados.
2. No Chrome, abra **chrome://inspect/#remote-debugging** e habilite a opção de
   depuração remota. Se a opção não existir, não tente flags/comandos para forçar.
3. Não precisa abrir o chat antes: o aplicativo abre quando necessário. Se já
   houver várias abas do mesmo chat, mantenha somente a que pretende usar.
4. No formulário BrowserAPI, escolha **Meu Chrome já aberto e logado**, deixe
   Google Chrome selecionado e salve com **outro nome**, por exemplo `gemini-logado`.
5. Leia o aviso de acesso e autorize a conexão no painel e no pedido do próprio
   Chrome. Só aceite se confiar no programa. A autorização de conexão é distinta
   da autorização para enviar uma mensagem.

**Acesso sensível:** a permissão CDP pode acessar todas as abas e contas desse
navegador, não apenas Gemini. O código do BrowserAPI opera apenas a aba do chat
selecionado; isso não é uma barreira de isolamento imposta pelo Chrome. Não
autorize uma conexão de programa desconhecido. Desative a depuração remota na
mesma tela quando não quiser mais permitir solicitações.

O programa conecta ao processo existente e desconecta sem fechar o Chrome, suas
abas ou sua sessão. Se houver mais de uma aba do chat, ele pede para deixar
somente uma em vez de escolher arbitrariamente. Não lê/exporta cookies. A
conexão usa somente o endpoint local publicado pelo próprio Chrome do usuário.
Algumas versões/instalações não disponibilizam esse endpoint; nesse caso falha
com orientação, sem tentar outras portas nem contornar a permissão.

Referência oficial do fluxo de consentimento do Chrome 144+: https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session
O projeto usa Playwright diretamente para CDP; não instala MCP/Node nem extensões.
A conexão nativa com permissão no Chrome pessoal e o login real no Google ainda
precisam de validação nesse desktop. Testar CDP em navegador controlado não prova
que o login funcionará nem que toda versão do Chrome disponibiliza esse modo.


### Evidência da versão ubuntu3

[Actions 40157983637](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40157983637), código `8b11752`: **SUCCESS, 257 testes em 124,149 s, 1 ignorado**.

Exercitados com navegador real e fixture: controle que muda de microfone para
Enviar, recusa de clique em microfone, apontamento real que rejeita voz, rascunho
temporário (consentido/negado/cancelado), preservação de rascunho anterior e de
edições, conexão CDP a um processo já aberto, reconexão sem recarregar a página,
não fechamento do processo/abas e recusa de múltiplas abas do mesmo chat.
O navegador CDP desse teste é um Chromium temporário controlado, não um perfil
pessoal real. O diálogo nativo de permissão do Chrome pessoal, disponibilização
do endpoint em cada versão e a sessão Google do usuário **não foram homologados**.
Também passaram testes de autorização negada antes de conectar, validação de
endpoint local/UID/symlink e montagem/extração do `.deb` com simulação de
dependências Ubuntu 24.04. O pacote publicado contém o mesmo código de execução
do commit validado; mudanças posteriores desta publicação são documentação e
artefato de instalação.


## Versão 0.1.0+ubuntu4 — ensino explícito de voz e Enviar

Este fluxo substitui o rascunho automático da GUI descrito na versão ubuntu3.

### No chat que já está salvo

1. Se quer seu Chrome pessoal, deixe o chat aberto na conta/modelo desejados e
   clique em **Usar Chrome já aberto** no cartão desse chat. Confirme a mudança.
   Mudar o formulário de um chat novo não alterava chats antigos; esse botão
   agora muda explicitamente o modo salvo. Ele apenas salva o modo e não abre
   navegador. A próxima conexão ainda requer permissão no painel e no Chrome.
2. Com o campo vazio e o microfone visível, clique em **Selecionar botão de voz**.
   Confirme a aba/conta e selecione o controle de voz. O clique é interceptado;
   não solicita gravação. Não apague um rascunho importante sem salvá-lo antes.
3. Clique em **Digitar e selecionar Enviar / Enter**. Quando solicitado, digite
   algo no chat **sem enviar**, volte ao painel e clique em **Já digitei ·
   Selecionar Enviar**. Então clique no botão Enviar/Enter que apareceu. Esse
   clique apenas ensina o controle. Não pressione a tecla Enter para enviar.
4. O rascunho que você digitou fica preservado. Apague-o manualmente antes de
   autorizar um teste. O apontamento não comprova funcionamento e não envia
   mensagem de teste automaticamente.

Durante o ensino manual, os controles de botão e a tecla Enter são bloqueados
na página para evitar envio no fluxo suportado; a proteção de clique passa ao
seletor sem remover o bloqueio antes de instalar o seletor. Esc/interrupção
limpam os observadores sem apagar o texto da pessoa. Páginas com eventos
incomuns, frames ou Shadow DOM continuam fora da garantia universal do wizard.

O estado de voz selecionado é guardado como seletor mais uma impressão digital
dos atributos/ícone, sem salvar texto do chat. **Não ignoramos permanentemente o
mesmo elemento físico:** se ele mudar de microfone para Enviar, o novo estado
pode ser usado. Um controle que continuar com o estado de voz registrado é
recusado antes de clicar, mesmo sem um rótulo reconhecido automaticamente.

### Não abrir outro perfil quando a conexão não encontra sua aba

No modo **Chrome já aberto**, BrowserAPI agora exige exatamente uma aba já
aberta da origem do chat. Se não a enxergar, para com explicação: o código não
cria uma aba nova, não lança outro Chrome e não volta ao modo separado. Com
duas abas desse chat, também para sem escolher uma arbitrariamente. O cartão
mostra **Chrome já aberto (configurado)**, não afirma falsamente que está
conectado só porque esse modo foi salvo.

Isso elimina um caminho de criação de aba nova e a confusão entre o formulário
e o chat salvo. **Não identifica automaticamente a conta sincronizada nem
comprova qual contexto/perfil o Chrome real do usuário está expondo por CDP.**
Confira a aba e a conta antes de prosseguir. Não copiamos cookies nem acessamos
perfis por diretório. Se o Chrome expuser outro contexto, não se promete que o
programa conseguirá entrar no perfil desejado.


### Validação da versão ubuntu4

Código `670bd10`, [Actions 40205878425](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40205878425): **SUCCESS, 262 testes em 117,706 s, 1 ignorado**.
Navegador real com fixture: seleção de voz, digitação humana simulada, bloqueio
de clique/Enter durante o ensino, seleção posterior de Enviar sem envio,
preservação do rascunho e envio autorizado posterior. Estado de voz sem rótulo
reconhecido é bloqueado; cancelamento limpa a proteção sem apagar o texto.
Também foram exercitados os botões reais do painel, troca consentida do modo
de chat salvo sem abrir navegador, recusa de aba inexistente sem criar outra e
reuso de aba já aberta sem recarregá-la/fechar o processo CDP.
O teste CDP usa um Chromium temporário, não o Chrome sincronizado do usuário.
O relato de visitante não foi reproduzido no computador real; não se afirma
identificação/correção universal de perfil pessoal, login Google ou contexto
que cada versão do Chrome expõe. O `.deb` passou montagem/extração e simulação
de dependências. Nesta publicação o código do pacote é o mesmo que passou a
CI; as mudanças posteriores são documentação e instalador gerado.


## Versão 0.1.0+ubuntu5 — pergunta de voz integrada e diagnóstico do painel

Na GUI, **Abrir e configurar** e **Corrigir campos** agora sempre passam pelo
assistente manual, sem pular a etapa por hipóteses de seletores ou pela opção
antiga de não revisar. Depois da seleção opcional do campo de texto:

1. Pergunta: **Com o campo de mensagem vazio, este chat tem um botão de entrada
   de texto por voz (microfone)?**
2. Se **Sim**, pede para selecionar esse controle. Se **Não**, remove um estado
   de voz anteriormente salvo, sem pedir apontamento de microfone.
3. Pede para você digitar algo sem enviar; depois de **Já digitei · Selecionar
   Enviar**, pede o clique no botão Enviar/Enter que apareceu. Essa etapa não é
   mais uma pergunta opcional que possa deixar o seletor antigo sem revisão.
4. O texto digitado é preservado. Apague seu rascunho antes de autorizar o teste;
   não há envio automático pelo ensino. Seletores de mensagens continuam com
   perguntas próprias, e o envio de teste continua exigindo consentimento.

Os botões individuais para voz e Enviar continuam disponíveis, mas não são
necessários para que a pergunta apareça no assistente completo.

### Erros de console reportados

- O padrão HTML do nome escapou o hífen para funcionar com a validação moderna
  de expressões regulares do Chrome. Não é preciso mudar nomes válidos.
- `/favicon.ico` agora responde sem exigir token de gerenciamento, mantendo
  validação do Host e sem expor dados. Não relaxamos a autorização das APIs.
- Erros `400` esperados passam a explicar nome já existente, chat não encontrado,
  operação em andamento ou ação não reconhecida. Exceções brutas do SO/navegador
  continuam omitidas para não revelar dados privados. Solicitações realmente
  inválidas continuam podendo retornar `400`; não se afirma que todo `400`
  anterior tinha a mesma causa.
- O cabeçalho/status mostram a versão da interface e a do servidor local. Se
  estiverem diferentes, os controles de operação ficam desabilitados e há
  orientação para reiniciar/abrir pelo menu. Fechar apenas a aba não encerra
  o processo antigo. Não basta instalar por cima e continuar na aba anterior.

A mensagem de recibo trazida pelo usuário lembra versões anteriores, mas não
foi possível determinar a versão efetivamente em execução naquele computador.
O novo diagnóstico torna essa informação visível, sem pedir terminal. Nenhuma
autorização/login Google ou identidade de perfil foi inferida por esse relato.


### Evidência ubuntu5

[Actions 40207783784](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40207783784), código `0f2de45`: **SUCCESS, 267 testes em 138,647 s, 1 ignorado**.

O teste de GUI da configuração percorreu presença de voz **Sim**, seleção do
microfone, digitação simulada pela pessoa e seleção de Enviar antes da
autorização de uma mensagem. O teste de **Corrigir campos** percorreu presença
**Não**, remoção de estado de voz antigo, digitação e seleção de Enviar, sem
enviar mensagem. São janelas/navegadores reais com fixture local e interações
sintéticas; não uma sessão autenticada do Gemini.

Passaram também validação HTML de nomes válidos/inválidos no Chromium moderno,
console sem erro de regex/favicons na carga válida, resposta pública vazia do
favicon com proteção de Host, mensagens controladas dos 400, bloqueio de ações
quando o runtime é antigo e pacote montado/extraído com simulação de dependências.

A primeira execução, [40207331990](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/40207331990), passou pelos novos testes de GUI,
mas falhou em timeout de um teste legado de CLI. A causa desse timeout não foi
identificada. Não se aumentou o prazo de produção/teste nem se inseriu reenvio;
acrescentaram-se verificações do cenário curto da fixture CLI e a bateria
completa foi executada novamente, com o resultado aprovado acima. Isso não
prova ausência universal de instabilidade.

O instalador publicado contém o mesmo código de execução validado. As alterações
seguintes são documentação e o `.deb` gerado. A escolha do perfil pessoal e o
Google real permanecem fora desta homologação.


## 0.2.0+ubuntu1 — dashboard e medição por etapa

Esta atualização preserva o fluxo integrado de voz/digitação/Enviar da ubuntu5.
Acrescenta **Dashboard de execução** na mesma janela: contadores da janela de
100 operações, média/P95, tokens não disponíveis, fontes observadas e a seção
**Análise de gargalos e histórico** com tempos e até 30 barras. O chat de teste
continua em **Meus chats → Conversar**, com autorização antes do envio.

As métricas ficam somente na memória e somem quando o programa é encerrado.
“Online (observado)” não é monitoramento contínuo: após 5 minutos a observação
fica antiga. Não se enviam mensagens para manter esse rótulo. Erros anteriores
à obtenção de um recibo são **erros de operação**, não latência zero. Verificações
sintéticas também contam como requisições com resultado; não existe API de LLM
pública nesta versão. [Definições e próximos marcos](NEXT_ARCHITECTURE.md).

**Atualização sem terminal:**
1. Baixe o instalador mais recente em
   <https://github.com/Financia-Brasil/browserapi-lab/releases/latest/download/BrowserAPI-Ubuntu.deb>
   (a pasta `downloads/` do código é histórica; não use os arquivos dela).
2. Abra o arquivo pelo gerenciador de arquivos e escolha instalar/atualizar.
3. Salve seu trabalho e reinicie o computador pelo menu gráfico. Apenas fechar
   a aba não encerra o programa antigo; ainda não há atualização a quente.
4. Abra **BrowserAPI** pelo menu de aplicativos. Confira que **Interface** e
   **programa em execução** mostram a mesma versão (rodapé do painel).
5. Abra **Análise de gargalos e histórico**. Use seu chat salvo e **Testar agora**
   ou **Conversar** quando desejar autorizar uma mensagem; o resultado alimenta
   o painel. Não é necessário recriar perfil nem fazer login só para medir.

Chrome pessoal continua experimental; esta atualização não descobre todos os
perfis instalados nem comprova a conta escolhida. Não há bloqueio de imagens,
CSS ou scripts, headless novo, Fetch/XHR, RAG, atualizador ou failover neste marco.
O relato anterior de Gemini em **9838 ms** foi do usuário, em perfil separado:
não é teste de Chrome sincronizado feito pelo assistente nem benchmark comparativo.


## 0.3.0 — uma instalação inicial, próximas atualizações automáticas

Use o `.deb` 0.3.0 publicado em `downloads/BrowserAPI-Ubuntu.deb`. Instale pelo
gerenciador gráfico e encerre a versão anterior/reinicie uma vez, pois ela não
tinha supervisor de atualização. Abra BrowserAPI pelo menu e confira **Painel
0.3.0 · programa 0.3.0**. A opção **Atualização automática** deve estar marcada.

Depois disso, versões estáveis compatíveis do repositório oficial são buscadas,
verificadas e aplicadas automaticamente com o programa livre. A aba reconecta;
não é preciso novo `.deb` ou reiniciar o computador para atualizações ABI 1.
Não fecha o Chrome pessoal nem repete mensagens. Pode desmarcar a opção no painel.

O estado do download/aplicação/falha aparece na seção de atualização. Sem internet,
o programa atual continua funcionando. Trocas de dependências do sistema ou do
supervisor ainda requerem instalador, não autorização silenciosa de administrador.
Código futuro é confiado ao editor GitHub indicado na GUI; SHA256 verifica
integridade, não é assinatura independente. [Detalhes e limites](UPDATES.md).


## Versão recomendada atual: 0.3.1

Use `downloads/BrowserAPI-Ubuntu.deb` 0.3.1 ou a release estável no GitHub.
Instale graficamente e encerre o programa antigo/reinicie uma vez se vier de
0.2.x ou anterior. Ao abrir pelo menu, confira **Painel 0.3.1 · programa 0.3.1**
e **Atualização automática** marcada. Esta versão também preserva o runtime
privado preparado durante a primeira sessão, inclusive após autoatualizar de
0.3.0. Atualizações de código ABI 1 seguintes não requerem reinstalação manual.


## Novidades 0.4.0: perfis, API e contexto

No modo **Meu Chrome já aberto e logado**, use **Listar perfis** e selecione a
instalação/diretório pretendidos. Os nomes vêm de metadados locais; não comprovam
conta Google, sincronização ou qual contexto o Chrome disponibiliza por CDP. Abra
o perfil desejado ou use Conectar para o fluxo guiado descrito no final desta página. Não copiamos credenciais,
não fechamos outras abas e não lançamos outro processo sobre seu perfil pessoal.
Chrome Beta/Unstable são selecionáveis; Chromium/Edge aparecem apenas no inventário.

A seção **API local para agentes** fica desligada inicialmente. Só autorize chats
que passaram pelo teste. A chave autoriza envios sem novas perguntas a cada chamada.
O [guia da API](LOCAL_API.md) explica os campos aceitos, fallback conservador e
limites: sem tools, sem contador de tokens, SSE bufferizado e sem contexto nativo
de 1M. A aba do site permanece compartilhada entre chamadas.

**Guardar histórico RAG** é uma escolha separada, desligada por padrão: salva
texto NÃO criptografado localmente, com limite de 8 milhões de caracteres, não
tokens. IDs separam recuperação local, não conversas remotas. É possível apagar
o histórico ou revogar a chave pelo painel, sem usar terminal. Otimizações
headless/bloqueio de recursos só se aplicam a perfil dedicado e são experimentais.

## Interface 0.5.1: perfil e chat, depois Conectar

1. Em **Conexões**, escolha seu perfil e o chat. Clique em **Conectar**.
2. Autorize o acesso ao Chrome. Se faltar a permissão inicial, o aplicativo abre
   a tela do Chrome no perfil escolhido: habilite Depuração remota e continue.
3. O aplicativo reaproveita uma aba do chat ou abre uma nesse Chrome. Não exige
   que você abra o chat antes, nem recarrega uma conversa já encontrada.
4. Confira sua conta e o modelo. O assistente mantém o ensino manual de voz/Enviar
   e pede autorização separada antes de enviar o teste.

**Opções e ajuda** reúne nome da conexão, perfil separado e ações manuais de
recuperação. Logs ficam recolhidos. Não há flags a digitar ou credenciais a copiar.
Se houver várias abas do mesmo chat, o aplicativo pede que você escolha qual
manter; não escolhe uma conta/conversa arbitrária nem fecha suas abas.
O nome do perfil não comprova a conta disponibilizada pelo Chrome; confira o avatar.
Chrome 144+ continua necessário para o consentimento nativo. Seu desktop/conta real
não foi homologado neste ambiente; os testes usam fixtures e processos descartáveis.

## 0.6 — escolher pela imagem, sem adivinhar seletores

Em **Corrigir campos**, confirme o controle que quer ensinar. O chat vem para a
frente com áreas numeradas em azul. Clique na área: a prévia fica verde; somente
**Usar esta área** salva a seleção. Não é mais preciso entender “seletor genérico”.
Para mensagens, use **Camada maior/menor**, **Voltar** ou **Escolher outra** até a
prévia cobrir o texto certo. **Mover painel** libera uma área encoberta; **Esc**
ou **Cancelar** saem sem salvar aquele apontamento. A prévia não envia mensagens.

O assistente não preenche todos os campos: busca, login e título também podem
parecer campos de texto. A descoberta visual não altera rascunhos. O ensino de
Enviar continua com sua digitação manual e autorização separada para o teste.
Seleção por posição é avisada: pode precisar de ajuste após novas mensagens.
Frames e componentes com DOM isolado ainda não têm este mapeamento gráfico.

Para remover um cadastro, abra **Ajustar ou excluir → Excluir conexão** e confirme.
Isso remove somente a conexão e seu recibo no BrowserAPI; não apaga conta,
conversas, perfil do Chrome ou histórico RAG da API. Desative a API e termine
qualquer tarefa antes de excluir. O diretório **Default/Profile N** aparece antes
do nome do perfil para diferenciá-los; isso não comprova qual conta foi conectada.

## 0.6.1 — o perfil escolhido é o perfil usado

1. Em **Conectar um chat**, escolha o perfil e o chat e clique em **Conectar**. A pasta (`Default` ou `Profile N`) aparece
   primeiro na lista; ela não diz qual conta está dentro.
2. Quando o Chrome pedir a permissão de depuração, clique em **Permitir**.
3. O BrowserAPI pede ao Chrome uma aba de verificação **no perfil escolhido**, confere a pasta e abre o chat nesse
   mesmo perfil. Se aparecer “Perfil confirmado pelo Chrome: Profile N”, a pasta bateu. A conta do site (avatar,
   modelo) continua sendo conferência sua.

Se algo parar, **nada foi escrito ou enviado**:

- **“O Chrome concedeu outro perfil, não o escolhido”** — abra esse perfil pelo avatar do Chrome e conecte de novo.
  Se continuar, esta versão do Chrome não deixa usar esse perfil por este modo. Não copie perfis para contornar.
- **“Página diferente da configurada”** — mostra o endereço esperado e o aberto. A Arena agora é `arena.ai`; ao
  conectar um chat antigo (`lmarena.ai`) o programa pergunta se pode migrar e mantém os campos já apontados.
- **“Mais de uma aba do chat neste perfil”** — deixe só uma aba do chat naquele perfil.

Não homologado no seu Chrome nem no Linux Lite. Detalhes e fontes: `docs/PROFILE_BINDING_061.md` e
`pesquisa/2026-10-27-perfis-cdp-e-origem.md`.
