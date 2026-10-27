# Revisão 0.6 — assistente visual, Ledger mantido
Receita: painel branco/verde, texto 15px, botões 44px, 8/16px de espaço, números além de cor; [contrato](UX_060_SPEC.md).
Referências documentais revisitadas: [Primer](https://github.com/primer/css), [Radix](https://github.com/radix-ui/primitives), [shadcn](https://github.com/shadcn-ui/ui); sem alegar comparação visual das bibliotecas.
[Desktop do picker](../../results/ci/ui-review-40509596029/ui-redesign/picker-desktop.png) e [375px](../../results/ci/ui-review-40509596029/ui-redesign/picker-mobile.png) inspecionados em Chromium, fixture sem conta privada.
Correção real após primeira captura: esconder camadas/desfazer inaplicáveis e retirar números do centro dos controles; recaptura final acima.
Mapa azul → clique → prévia verde → confirmação; nenhum preenchimento para descobrir controles e nenhum envio no apontamento.
Textos: camada maior/menor, Voltar e escolher outra; seleção antes rejeitada como genérica agora pode ser conferida, com aviso quando depender da posição.
[Contraste sRGB](../../results/ci/visual-060-updater/picker-contrast.json): texto 13,99:1, CTA 6,38:1, contorno azul 5,17:1 e borda de botão 3,12:1.
[12 testes gráficos](../../results/ci/ui-review-40509596029/ui-review.log), 32,047s: prévia/confirmar/reset sem escrita ou envio, exclusão cancelada/confirmada e largura sem overflow na fixture.
[Chat salvo](../../results/ci/ui-review-40509596029/ui-redesign/saved-chat.png): Ajustar ou excluir; diretório do perfil antes do nome, sem afirmar que a identidade da conta foi corrigida.
Exclusão autenticada apenas de cadastro/recibo, bloqueada durante operação/API; histórico RAG e conversas não são apagados.
Limites: LMArena real/conta pessoal não homologados; frames e shadow DOM isolados não têm mapa gráfico; seletores por posição continuam frágeis.
capturas na execução 40509596029: checks 2026-10-27 13:10:59 UTC > mtime de assets (incluindo picker.js) 13:10:15 UTC ✓.
Publicação v0.6.0 aprovada em main 40511019910; 34 payloads do instalador e atualização 0.5.1→0.6.0 conferidos — [prova](../../results/ci/visual-060-updater/published.json).
