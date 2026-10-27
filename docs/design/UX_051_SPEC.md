# 0.5.1 — menos preparação, mais conexão

Estilo mantido: Ledger (Inter 450, verde contido, superfícies planas, escala 8pt).
Não é uma nova identidade visual. É uma revisão do caminho inicial e de recuperação.

## Contrato de experiência
- Entrada: perfil + chat + Conectar. Nome automático; modo separado e ações manuais dentro de uma única divulgação progressiva, Opções e ajuda.
- Sem aviso técnico permanente quando o inventário está saudável. Falhas permanecem visíveis e acionáveis.
- A permissão é pedida na hora de conectar. Se faltar a configuração inicial, abrir a tela nativa do Chrome no perfil explicitamente escolhido e pedir uma única ação.
- Não exigir chat previamente aberto. Reaproveitar a aba sem reload; se não existir, abrir uma aba nesse contexto CDP já autorizado.
- Não criar perfil vazio, copiar sessão ou navegar abas não relacionadas. Ambiguidade continua bloqueada; não escolher uma conversa silenciosamente.
- Antes de ensinar controles ou enviar: confirmação visível da conta/modelo. Nome do perfil e endpoint não comprovam identidade da conta.
- Preservar ensino manual de digitação/voz/Enviar e consentimento separado de envio; preservar atualizador.

## Critérios de aceite
Testes sem navegador para abertura ausente, recusa de navegação sem retry, ambiguidade e permissão inicial após consentimento.
Teste Chromium descartável para criação de uma aba, reuso sem reload e preservação do processo/abas não relacionadas.
Interface real: exatamente dois campos visíveis inicialmente; opções recolhidas; foco por teclado, captura 1440px e 375px sem overflow.
Aparência só aprovada após inspecionar capturas posteriores às mudanças. Chrome pessoal/conta real e Linux Lite do usuário não são homologáveis neste sandbox.
