# Pré-registro congelado — 2026-10-28

Escrito **antes** do loop de coleta (o loop só atualiza a coluna de resultado).

**Pergunta original → operacional.** "A API não funciona, o mapeamento confunde
as mensagens, a janela não abre, a atualização não aplica" →
*qual arquitetura de captura, confirmação e interface o BrowserAPI deve adotar
para funcionar em chats arbitrários (Gemini, Arena/LMArena) usando **apenas
Playwright + biblioteca padrão**, sem seletor por site, sem falso "envio não
confirmado" e sem UI que quebre a página?*

| # | Hipótese (afirmativa, testável) | O que a mata | Fonte-alvo | Kent prévia |
|---|---|---|---|---|
| H1 | Dá para separar "minha mensagem" de "resposta" só por **estrutura** (ordem no DOM + alinhamento horizontal + proximidade do editor), sem marcador de papel, com ≥95% de acerto em ≥3 UIs diferentes | achado de chat onde a heurística estrutural erra de forma sistemática (ex.: resposta alinhada à direita) | MDN/Chromium + repos open-source de automação de chat | provável 75±12% |
| H2 | Nonce único no corpo da mensagem (`request_id`) presente no DOM é confirmação de envio com falso-positivo ≈0 e falso-negativo ≈0 | provedor que sanitiza/renderiza o texto sem o nonce de forma comum | docs de sanitização/markdown dos provedores | quase-certo 93±6% |
| H3 | Fim de streaming é melhor detectado por "botão parar ausente" + estabilidade de texto do que por tempo fixo | ausência de botão parar em todos os alvos | DOM real Gemini/Arena | provável 75±12% |
| H4 | UI injetada com Shadow DOM + `position:fixed` + tamanho fixo elimina interceptação de clique e barra de rolagem, sem quebrar CSP da página | CSP `style-src` sem `unsafe-inline` bloqueando estilo inline também dentro de shadow root | MDN/CSP + testes reais | 50±10% |
| H5 | `ResizeObserver`/`MutationObserver` é mais robusto e barato que polling de 350 ms para acompanhar layout/conteúdo | observers não dispararem em conteúdo virtualizado/iframe fechado | MDN | provável 75±12% |
| H6 | Persistir telemetria local (agregada, sem texto) sobrevive a atualização do app sem risco de vazar prompt/resposta | qualquer caminho em que o arquivo persistido contenha texto de mensagem | código atual + revisão de campos | quase-certo 93±6% |

**Fermi prévio (ordem de grandeza esperada, antes de abrir fonte).**
Automação de chat por seletor fixo quebra a cada ~2–8 semanas (sites redesenham);
automação por estrutura + nonce deve cair para ~1 quebra a cada 6 meses.
Ordem esperada de falsos negativos de confirmação por texto: 1 em 20 envios com
seletor de papel; com nonce: <1 em 1 000.

**Baseline da classe.** Ferramentas de automação de chat publicadas (extensões,
bots de navegador) mantêm lista manual de seletores por site e quebram quando o
site muda; a taxa típica de manutenção é o custo dominante do produto.
