# BrowserAPI no Ubuntu — sem terminal

Interface experimental para configuração e teste de chats. **Não é um serviço de API pronto.**

## Instalar e abrir

- Destinado inicialmente ao **Ubuntu 24.04 ou mais recente, com Python 3.11+**. Ubuntu 22.04 padrão não atende ao requisito; não atualize o Python do sistema para contornar isso.
- Baixe o arquivo **BrowserAPI-Ubuntu.deb** entregue junto com esta orientação.
- Abra o arquivo com o **instalador de pacotes** do Ubuntu e escolha **Instalar**. O Ubuntu pode pedir a senha de administrador na janela do próprio sistema. Nunca envie essa senha no chat.
- Procure **BrowserAPI** no menu de aplicativos e abra.
- Algumas instalações do Ubuntu não têm um programa gráfico que abra arquivos `.deb`. Nesse caso, informe sua versão do Ubuntu e o que aparece ao abrir o arquivo; não é necessário tentar comandos. A instalação gráfica varia entre versões e não foi homologada em um desktop Ubuntu do usuário.

O pacote não instala nada durante a montagem e não contém scripts de instalação privilegiados. O gerenciador de pacotes resolve as dependências declaradas e pede a autorização local necessária. O programa deve rodar como usuário normal, nunca como administrador.

## Na janela do programa

1. Na primeira vez, clique em **Preparar BrowserAPI** e confirme o download. Isso cria um ambiente privado do usuário e baixa Playwright/Chromium. Requer internet e pelo menos 1,5 GB disponíveis. Não instala Chrome nem Edge.
2. Escolha o **navegador** e o **chat**. Dê um nome para salvar; use nomes diferentes para navegadores/chats diferentes.
3. Clique em **Abrir e configurar**. Na outra janela, faça login e escolha o modelo. Seu perfil pessoal não é usado; é normal precisar entrar novamente.
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

O painel escuta somente em `127.0.0.1`, com chave aleatória por execução e proteção de origem. Não é acessível pela rede e não oferece API OpenAI. A janela de controle abre no navegador padrão; o navegador selecionado no formulário é o que abre o chat automatizado.

Configurações, recibos e perfis exclusivos ficam em `~/.config/browserapi-lab/`. O ambiente de execução fica em `~/.local/share/browserapi-lab/` (ou em `$XDG_DATA_HOME/browserapi-lab/`). Esses diretórios podem conter sua sessão de login: não os compartilhe. O recibo não inclui mensagens, cookies ou credenciais. Mensagens/respostas exibidas no painel ficam temporariamente na memória até outra operação ou o processo encerrar.

Fechar a aba do painel não encerra o processo local: abrir BrowserAPI de novo no menu reabre o mesmo painel, sem duplicar o perfil. Sair da sessão Ubuntu encerra os processos. A remoção do pacote pelo gerenciador gráfico não apaga seus dados pessoais automaticamente.

O teste sintético não equivale a homologar Gemini/LMArena autenticados, todos os navegadores, todas as versões do Ubuntu ou comparar com uma API real. Sites externos podem mudar. Nenhuma instalação foi feita no computador do usuário nesta sessão.
