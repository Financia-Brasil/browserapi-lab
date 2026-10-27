# Dossiê: perfis CDP e falha antes do envio
**Data:** 2026-10-27 · **Rotas planejadas:** web em paralelo, documentação/código primário via GitHub, testes locais/Actions.
**Pergunta original → operacional:** “melhorar tudo; dois perfis vão para um e teste falha” → decidir como vincular o Chrome realmente conectado ao perfil selecionado e tratar redirecionamentos sem enviar para outra conta/site.

## 1. Hipóteses pré-registradas
Escritas após leitura dos anexos e código local, antes da coleta web; só atualizar Resultado.
| # | Hipótese afirmativa | O que a mata | Fonte-alvo | Kent prévia | Resultado |
|---|---|---|---|---|---|
| H1 | O endpoint por instalação não seleciona o diretório do perfil no CDP; as duas opções podem conectar ao mesmo contexto | Evidência primária de seleção de Profile N pelo endpoint/BrowserContext usado | Chrome DevTools MCP/Chromium + browser.py | quase-certo 93±6%, código já lido | pendente |
| H2 | O guard de origem impede o envio depois de um redirecionamento do domínio do chat | Origem configurada e efetiva iguais no caso; teste reproduz sem guard de origem | origem de Arena e preflight/config locais | provável 75±12% | pendente |
| H3 | O “0 ms” prova que houve uma tentativa de envio rápida | preflight retornar antes de send_message e nenhum envio em teste | chat.exchange + teste de regressão | provavelmente-não 30% | pendente |
| H4 | Remover o guard de origem resolve o problema com segurança | Um destino alheio/login passa a receber um envio em teste | teste de guard com site não relacionado | provavelmente-não 30% | pendente |

Sub-perguntas: (1) escopo do endpoint/perfil; (2) identidade verificável da conexão; (3) redirecionamento Arena; (4) etapa exata e recibo; (5) recuperação simples sem trocar conta ou reenviar.
Fermi pré-fonte: perfis listados (2) × instalações selecionadas (1) × endpoints por instalação (1) = 2 escolhas para 1 endpoint (ordem 10^0); não esperar 2 identidades só pelo inventário. Latência do pré-voo local: comparação de 2 URLs + consultas DOM (0 chamadas de envio) → milissegundos, arredondamento a 0 possível. Não é medição de modelo.
Baseline de referência: usuário relata falha apesar de testes sintéticos; estes não estimam taxa de sucesso pessoal. Não existe amostra de contas reais para projetar homologação.

## 2. Coleta/fichas
Pendente.
## 3. ACH
Pendente.
## 4. Premortem e linchpin
Pendente.
## 5. Resumo executivo
Pendente.
## 6. Surpresa e implicação
Pendente.
## 7. Comparativo
Pendente.
## 8. Lacunas
Não há DOM, URL efetiva, versão do Chrome nem perfil real do usuário neste ambiente. Não registrar conteúdo privado para pesquisar.
## 9. Fontes
Pendente.

### Rodada 1 — fichas registradas na leitura (acesso 2026-10-27)
- **F1 · fato primário · ChromeDevTools/advanced-usage · revisão 2026-09-15, snapshot ca6f83498014e74243117a2aa3830cf71091d64d** · https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/ca6f83498014e74243117a2aa3830cf71091d64d/docs/advanced-usage.md · “If the user has multiple active profiles, the MCP server will connect to the default profile (as determined by Chrome).” Discrimina H1 vs hipótese implícita de que selecionar inventário seleciona CDP. Documenta MCP, não prova toda implementação Playwright.
- **F2 · fato primário de limitação declarada · issue #694, aberta 2025-12-19; comentário mantenedor 2026-10-14** · https://github.com/ChromeDevTools/chrome-devtools-mcp/issues/694 · “there's no way to control which profile will be automated by the MCP server.” A solução --profile-directory ainda está em avaliação. Mesmo projeto de F1: não contar como confirmação independente.
- **F3 · fato primário · Arena Team, publicado/atualizado 2026-01-28** · https://arena.ai/blog/lmarena-is-now-arena · “That evolution is why we are now Arena. Now available at: arena.ai.” O snippet de busca marcava agosto, mas a página primária marca janeiro: usar data da página. Discrimina H2 de defeito de seletor; não prova a URL efetiva do usuário.
- **F4 · fato local · revisão-base dfbf8d0, acesso 2026-10-27** · browserapi_lab/config.py, browserapi_lab/chat.py · “'lmarena': 'https://lmarena.ai/'” e “if origin(page.url) != origin(config.url): return 'wrong_origin'”. O texto exato relatado pelo usuário é REMEDIES['wrong_origin']; não é um erro genérico de apontamento.

### Rodada 2 — busca refinada: contraprova e identidade nativa
- **F5 · alegação independente, não homologada · govarthenan/chrome-profiles, publicado 2026-10-22** · https://github.com/govarthenan/chrome-profiles/tree/4f4cd3b9bc658f4a4587244ed620593cfc2fc622 · “A reliable way to find the new tab: compare the page list before and after open.” Propõe abrir --profile-directory no Chrome existente. CONTRADIÇÃO com F1: README promete dirigir outros perfis, mas o script só abre janelas e não prova que o transporte os expõe. Não adotar promessa; aproveitar apenas abertura nativa + exigir prova do perfil. Não instalar Node nem copiar credenciais.
- **F6 · fato primário · Chromium docs/user_data_dir.md, data de publicação não indicada, acesso 2026-10-27** · https://github.com/chromium/chromium/blob/main/docs/user_data_dir.md · “Look for the Profile Path field. This gives the path to the profile directory.” Identidade do diretório pode vir do próprio navegador, não do inventário/email. Não prova identidade da conta do site.
- **Falha de rota declarada:** chrome/browser/resources/version/version.html retornou 404 no mirror Chromium; não usar esse caminho como evidência do seletor DOM. Próximo passo: localizar fonte real via árvore GitHub.
- Refinamento efetivo: rodada 1 encontrou limitação de seleção; rodada 2 buscou alternativa que contradiz a documentação e prova nativa para arbitrar em execução. A promessa comunitária não prevalece sobre a verificação local.
- **F7 · código primário Chromium, data de publicação não obtida, acesso 2026-10-27 via gh API** · https://github.com/chromium/chromium/blob/main/components/webui/version/resources/about_version.html · `<td class="version" id="profile_path">$i18n{profile_path}</td>`; https://github.com/chromium/chromium/blob/main/components/webui/version/resources/about_version.ts · `getRequiredElement('profile_path').textContent = profilePath;` O preenchimento é assíncrono: esperar campo não vazio. Fonte localizada por árvore GitHub após duas rotas 404 e busca vazia; não inferir seletor da documentação descritiva.
