# Revisão UX 0.5.1 — Ledger mantido, caminho inicial reduzido
Contrato: [perfil + chat + Conectar](UX_051_SPEC.md); fonte Inter 450, verde e tokens existentes, sem nova identidade decorativa.
Método: Chromium real em fixtures, 1440×1040 e 375×812; quatro PNGs inspecionados, não só revisão de código.
[Desktop](../../results/ci/ui-review-40435835598/ui-redesign/desktop.png): dois campos visíveis; nome/modo/ações manuais recolhidos em uma única seção.
[Mobile](../../results/ci/ui-review-40435835598/ui-redesign/mobile.png): sem overflow horizontal; CTA antes das opções após correção da primeira captura.
[Erro](../../results/ci/ui-review-40435835598/ui-redesign/error.png) e [chat salvo](../../results/ci/ui-review-40435835598/ui-redesign/saved-chat.png): recuperação preservada sem dominar a entrada.
[Checks](../../results/ci/ui-review-40435835598/ui-redesign/checks.json): foco por teclado, destinos de permissão restritos e ação nativa sem iniciar automação.
[Contrastes](../../results/ci/ui-review-40435835598/ui-redesign/contrasts.json): texto principal 13,99:1, secundário ≥5,31:1, CTA 6,38:1 e borda do campo 3,12:1.
[10 testes gráficos](../../results/ci/ui-review-40435835598/ui-review.log) aprovados em 31,548 s, incluindo dois campos e erro visível fora do log.
Testes de conexão: aba ausente é criada no contexto existente, aba encontrada não é recarregada, ambiguidade bloqueada e navegação recusada não gera retries.
Permissão inicial: tela nativa apenas após consentimento e somente para perfil inventariado; conta/modelo confirmados em etapa visível antes de ensinar ou enviar.
Sem evidência de uso no Chrome pessoal/conta real do usuário, Linux Lite real ou leitor de tela; permissão nativa não foi homologada neste sandbox.
captura 2026-10-27 02:02:07 UTC > última edição dos assets no runner 02:01:19 UTC ✓.
Publicada v0.5.1 após CI main 40436817318; atualização real 0.5→0.5.1 e 34 payloads do instalador verificados — [provas](../../results/ci/ux-051-updater/published.json).
