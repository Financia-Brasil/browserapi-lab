**SPEC — Ledger**: Inter 450 + JetBrains Mono nos dados; base 15/21px, espaços 8pt, tinta/verde, bordas sem sombras; não Terracota editorial nem Ácido-Noir teatral ([receita](UI_050_SPEC.md)).
Referências documentais ao vivo: Primer, shadcn e [VS Code Profiles](https://github.com/microsoft/vscode-docs/blob/main/docs/configure/profiles.md); sem comparação pixel a pixel das referências.
1. Foco **Conectar → perfil existente**: inspeção Chromium, coluna esquerda/CTA — [desktop](../../results/ci/ui-review-40432431701/ui-redesign/desktop.png).
2. Ritmo: regex de padding/margin/gap + inspeção; offsets da sidebar não são espaçadores — [auditoria](../../results/ci/ui-050-audit/code.json).
3. Contraste: luminância sRGB; texto 13,99/5,66/5,31:1, CTA 6,38:1, campos 3,12:1 — [pares](../../results/ci/ui-review-40432431701/ui-redesign/contrasts.json).
4. Foco: Tab/Shift+Tab reais e computedStyle solid, ring CSS 2px — [checks](../../results/ci/ui-review-40432431701/ui-redesign/checks.json).
5. Estados: vazio, conexão salva e recusa nativa não mascarada — [vazio](../../results/ci/ui-review-40432431701/ui-redesign/desktop.png), [salvo](../../results/ci/ui-review-40432431701/ui-redesign/saved-chat.png), [erro](../../results/ci/ui-review-40432431701/ui-redesign/error.png).
6. Responsivo: capturas 1440 e 375px; scrollWidth ≤ innerWidth — [mobile](../../results/ci/ui-review-40432431701/ui-redesign/mobile.png) e checks.
7. Ledger visível: hierarquia operacional, verde contido, sem sombras repetidas; glifo quebrado removido — desktop/mobile acima; não uma alegação de gosto universal.
8. Fontes: duas famílias locais OFL, sem CDN, mono apenas nos campos de dados/log — [auditoria](../../results/ci/ui-050-audit/code.json), [licenças](../TYPOGRAPHY_LICENSE.md).
9. Motion: somente cor/borda 140ms, sem movimento de layout; reduced-motion respeitado — auditoria + CSS; nenhum efeito de entrada bloqueia tarefas.
10. Microcopy auditada: pedido ao SO ≠ conexão; endpoint ≠ conta verificada; sem tokens/online inventados. Ciclos: glifo/ordem → contraste → tokens → recaptura; 10 testes gráficos aprovados em [log](../../results/ci/ui-review-40432431701/ui-review.log).
Anti-autopilot: receita relida e referência VS Code reaberta; ADOTA ações de perfil agrupadas (coluna esquerda); REJEITA copiar perfil/modal (sessão pessoal não deve ser clonada). Não verificados: Chrome pessoal/conta real, diálogo nativo, leitor de tela e todas as alturas de laptop; a tela estreita requer rolagem vertical.
captura 01:27 UTC > última edição 01:26 UTC ✓ (mtime dos assets no runner, registrado em checks.json).
