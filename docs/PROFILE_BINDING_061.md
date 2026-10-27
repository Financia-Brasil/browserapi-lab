# 0.6.1 — o perfil escolhido é o perfil usado

## O que causava “os 2 perfis levam para um só”
Três peças, cada uma conferida na fonte (ver `pesquisa/2026-10-27-perfis-cdp-e-origem.md`):

1. O Playwright 1.64.1 coloca abas de **todos** os perfis do Chrome no mesmo contexto.
2. A criação de aba por CDP (`Target.createTarget`) abre no perfil usado por último, não no escolhido.
3. O código procurava “uma aba da mesma origem” sem saber de qual perfil ela era; o serviço de API local
   ainda fazia isso por conta própria.

Renomear ou reordenar a lista de perfis não muda nada disso.

## Como funciona agora
1. Conecta ao Chrome com a sua permissão (nada é aberto antes dela).
2. Pede ao **próprio Chrome** uma aba interna `chrome://version` com código único no perfil escolhido
   (`--profile-directory`, sem `user_data_dir`, sem flags de depuração, sem copiar perfil).
3. Reencontra só essa aba, lê o *Profile Path* mostrado pelo Chrome e compara a pasta inteira.
   Guarda o `browserContextId` real da aba, só na memória. Fecha apenas a aba de prova.
4. O chat é aberto **pelo Chrome nativo no mesmo perfil**. Abas existentes só são reaproveitadas se tiverem o
   mesmo `browserContextId`. Aba nova em outro perfil nunca é usada nem repetida.
5. Qualquer divergência ou falta de prova **para antes de abrir ou escrever no chat**.

O painel mostra “Perfil confirmado pelo Chrome: Profile N”. Isso é a **pasta**; a conta do site (avatar, e-mail,
modelo) continua sendo conferida por você. Caminhos e contas não entram no recibo.

## Arena
O endereço oficial é `arena.ai`. Conexões antigas em `lmarena.ai` pedem confirmação para migrar e preservam
os campos já apontados. Nenhum outro domínio, subdomínio, HTTP ou porta ganha confiança automática.
O recibo diz em que etapa parou e se algo foi enviado; “0 ms” de um pré-voo não é mais apresentado como
tempo de resposta do modelo.

## Limites
- Não homologado no seu Chrome pessoal nem no Linux Lite: os testes usam Chromium descartável.
- Se esta versão do Chrome não expuser a aba de prova, o modo para com mensagem clara. Não há login alternativo,
  cópia de perfil nem Guest como contorno.
- O código do Chromium lido é o da linha principal; o Chrome estável instalado pode divergir.
