# UI/UX 0.5 — especificação e limites

**Ledger**: Inter + JetBrains Mono apenas para código/dados; regular 450,
títulos 650, corpo moderado de 13/20 para 15/21 px para legibilidade no desktop
Linux. Borda 1px, foco 2px, controles com raio 6px, painéis sem sombras repetidas.
Ritmo predominante 8/16/24/32/40/48/64. Fundo #f6f8f7, branco #fff,
tinta #1b3029, secundário #596b63 e ação #146c50. Fontes OFL servidas localmente,
sem CDN ou novas dependências. Não adotar Terracota (editorial, não operacional)
nem Ácido-Noir (contraste teatral desnecessário nesta tarefa frequente).

## Intake assumido
Ação primária: **Conectar → perfil existente**. Público: usuário Linux Lite,
sem terminal. Objeções: abrir um visitante em vez da conta, permissões confusas,
e sobrecarga de controles. Provas: testes sintéticos HTTP/Chromium e screenshots;
nenhuma conta real ou diálogo nativo de Chrome pessoal foi homologado aqui.

## Referências documentais consultadas ao vivo em 2026-10-26
- https://github.com/primer/css — hierarquia de aplicação, estados e bordas discretas.
- https://github.com/shadcn-ui/ui — componentes como ações independentes/componíveis.
- https://github.com/microsoft/vscode-docs/blob/main/docs/configure/profiles.md —
  ações de perfil concentradas, separando abrir/gerenciar de configurar o conteúdo.
São referências documentais ao vivo, não comparações visuais pixel a pixel.

## Assinatura e guardas
Trilho real “Navegador → Chat → Agentes” e perfil/permissão junto da ação principal.
Riscos Ledger: densidade excessiva e todas as cartas com mesma sombra. Guardas:
quatro áreas separadas, opções avançadas recolhidas e zero sombras decorativas.
Não inventar contadores, status online ou ganhos de desempenho.

## Fluxo corrigido
Antes: selecionar um perfil apenas gravava uma indicação; nenhum botão o abria.
Agora: “Abrir este perfil” usa o comando normal da instalação do Chrome com
`--profile-directory`, encaminhado pelo ProcessSingleton nativo, sem
`--user-data-dir`, flags CDP ou Playwright. Não clona/importa cookies nem fecha abas.
“Configurar permissão” pede ao mesmo perfil para abrir a tela nativa de consentimento.
O pedido ao SO não é prova de janela aberta ou conta correta. O usuário confere o
avatar, ativa a permissão no Chrome 144+ e aceita a conexão. Falta de endpoint ainda
é um erro explícito, não um pretexto para abrir um perfil vazio.

## Barra de evidência
Antes de capturas reais, aparência e responsividade = **SEM-EVIDÊNCIA**.
Testes novos devem salvar desktop 1440px e mobile 375px, foco, ausência de overflow,
navegação, pedido nativo mockado (sem acessar perfil pessoal) e data de captura.
Uma correção visual será aplicada e recapturada depois da primeira inspeção.
