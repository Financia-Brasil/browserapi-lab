# 0.6.1 — o perfil escolhido é o perfil usado

## O que causava “os 2 perfis levam para um só”
Três peças, cada uma conferida na fonte (ver `pesquisa/2026-10-27-perfis-cdp-e-origem.md`):

1. O Playwright 1.64.1 coloca abas de **todos** os perfis do Chrome no mesmo contexto. Confirmado em Chrome real:
   1 contexto do Playwright para 2 perfis.
2. A criação de aba por CDP (`Target.createTarget`) abre no perfil usado por último, não no escolhido.
3. O código procurava “uma aba da mesma origem” sem saber de qual perfil ela era; o serviço de API local
   ainda fazia isso por conta própria.

Renomear ou reordenar a lista de perfis não muda nada disso.

## Como funciona agora
1. Conecta ao Chrome com a sua permissão (nada é aberto antes dela).
2. Pede ao **próprio Chrome** uma aba no perfil escolhido (`--profile-directory`, sem `user_data_dir`, sem flags
   de depuração, sem copiar perfil). A aba é uma página local `http://127.0.0.1:<porta>/browserapi-proof-<código>`,
   servida só em loopback e só durante a prova. **Tem de ser http(s):** o Chrome aceita o pedido com código 0 e
   descarta `chrome://` (e `about:blank#x`), sem avisar.
3. Reencontra só essa aba pelo código, navega por CDP até `chrome://version`, lê o *Profile Path* e compara a pasta
   inteira. Guarda o `browserContextId` real da aba, só na memória.
4. A aba de prova **vira a aba do chat** (navega para o chat). Fechá-la antes derrubava a única janela do perfil.
   Se o perfil já tem uma aba do chat com a mesma identidade, ela é usada e a aba de prova é fechada.
5. Qualquer divergência ou falta de prova **para antes de abrir ou escrever no chat**. Aba nova em outro perfil
   nunca é usada nem repetida.

O painel mostra “Perfil confirmado pelo Chrome: Profile N”. Isso é a **pasta**; a conta do site (avatar, e-mail,
modelo) continua sendo conferida por você. Caminhos e contas não entram no recibo.

## Permissão do Chrome
O Chrome não deixa programas abrirem `chrome://inspect`. O botão **Permissão do Chrome** abre a janela do perfil, e o
texto manda **digitar** `chrome://inspect/#remote-debugging` na barra de endereço e ativar a Depuração remota.

## Arena
O endereço oficial é `arena.ai`. Conexões antigas em `lmarena.ai` pedem confirmação para migrar e preservam
os campos já apontados. Nenhum outro domínio, subdomínio, HTTP ou porta ganha confiança automática.
O recibo diz em que etapa parou e se algo foi enviado; “0 ms” de um pré-voo não é mais apresentado como
tempo de resposta do modelo.

## Evidência e limites
- `scripts/native_open_probe.py` roda o **fluxo real do produto**, com dois perfis, contra o Google Chrome instalado
  (workflow `probe-perfis`, cerca de 1,5 min). Resultado em `results/ci/probe-*/`.
- Não homologado no seu Chrome pessoal nem no Linux Lite. O experimento usa um Chrome descartável com porta de
  depuração; o diálogo de aprovação do Chrome 144+ não pode ser aceito na CI.
- Se esta versão do Chrome não expuser a aba de prova, o modo para com mensagem clara. Não há login alternativo,
  cópia de perfil nem Guest como contorno.
- O código do Chromium lido é o da linha principal; o Chrome estável instalado pode divergir.
