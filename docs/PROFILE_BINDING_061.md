# 0.6.1 — limites e correções de conexão

O inventário de diretórios não é uma lista de contextos CDP. Chrome 144+ pode
conceder somente o perfil padrão, mesmo com outros perfis abertos. Não afirmar
que duas opções do inventário selecionam duas contas.

Antes de tocar no chat, o runtime abre sua própria aba interna chrome://version,
espera o Profile Path e compara o diretório inteiro com instalação/perfil
escolhidos. Fecha apenas essa aba de prova. Falha ou divergência interrompe a
conexão, sem preencher/enviar nem encerrar o Chrome. Caminhos, contas e cookies
não entram no recibo. Isso verifica o diretório, não o login da conta no site:
a confirmação manual de conta/modelo continua obrigatória.

**Limitação importante:** isto impede conectar silenciosamente ao perfil errado;
não faz o Chrome oferecer perfis que o transporte nativo não expõe. Não é
homologação de múltiplos perfis pessoais ou de Linux Lite. A documentação e o
contraponto comunitário estão em `pesquisa/2026-10-27-perfis-cdp-e-origem.md`.
Não propor cópia de credenciais, Guest, flags no perfil padrão ou outro login.

Arena agora abre em arena.ai. Conexões antigas lmarena.ai podem confirmar a
migração ao endereço mostrado, preservando os seletores. Outros domínios,
subdomínios, HTTP ou portas não ganham confiança automaticamente. Recusar não
altera o arquivo. A alteração de domínio não é prova de conta.

Recibos distinguem navegação/pré-voo/envio/espera/leitura. Quando não houve envio,
o painel informa isso e não apresenta 0 ms como tempo de resposta do modelo.
Diagnósticos mostram só origens, não caminhos, queries ou conteúdo da conversa.
Updater, apontamento gráfico, exclusão local e consentimento de um envio mantidos.
