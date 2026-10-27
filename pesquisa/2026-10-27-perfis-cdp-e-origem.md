# Dossiê: perfis CDP e falha antes do envio
**Data:** 2026-10-27 · **Rotas usadas:** busca web paralela (3 consultas por ciclo: MCP/perfis, rebrand da Arena, CDP/perfil), leitura primária via GitHub (Chromium, Playwright, Chrome DevTools MCP), troca de rota quando a busca falhou (ver Desvios), testes locais e GitHub Actions.
**Pergunta original → operacional:** “melhorar tudo; dois perfis vão para um e teste falha” → decidir como vincular o Chrome realmente conectado ao perfil selecionado e tratar redirecionamentos sem enviar para outra conta/site.

## 1. Hipóteses pré-registradas
Escritas após leitura dos anexos e código local, antes da coleta web; só atualizar Resultado.
| # | Hipótese afirmativa | O que a mata | Fonte-alvo | Kent prévia | Resultado |
|---|---|---|---|---|---|
| H1 | O endpoint por instalação não seleciona o diretório do perfil no CDP; as duas opções podem conectar ao mesmo contexto | Evidência primária de seleção de Profile N pelo endpoint/BrowserContext usado | Chrome DevTools MCP/Chromium + browser.py | quase-certo 93±6%, código já lido | confirmada, com refinamento — F1/F2/F10/F13: o endpoint não escolhe perfil; o “padrão” é o último usado e o Playwright junta os perfis. Causa no computador do usuário não observada |
| H2 | O guard de origem impede o envio depois de um redirecionamento do domínio do chat | Origem configurada e efetiva iguais no caso; teste reproduz sem guard de origem | origem de Arena e preflight/config locais | provável 75±12% | mecanismo reproduzido — F3/F4/F8; compatível com o texto recebido, mas não é a única causa possível (ver H5). URL efetiva do usuário não observada |
| H3 | O “0 ms” prova que houve uma tentativa de envio rápida | preflight retornar antes de send_message e nenhum envio em teste | chat.exchange + teste de regressão | provavelmente-não 30% | morta — F8: sender não chamado; nenhuma espera de resposta |
| H4 | Remover o guard de origem resolve o problema com segurança | Um destino alheio/login passa a receber um envio em teste | teste de guard com site não relacionado | provavelmente-não 30% | morta — F9: guard removido permitiu envio na origem errada (fixture) |
| H5 *(adicionada depois do início do loop; ver Desvios)* | Mesmo com o perfil certo aberto, o uso de abas ignorava o perfil: Playwright agrupa abas de todos os perfis, criar aba por CDP usa o perfil usado por último e o código casava “mesma origem” entre perfis | Fonte primária mostra que as abas de perfis diferentes ficam em contextos separados no Playwright e que createTarget respeita o perfil pedido | Playwright (tag fixada) + Chromium + código local | provável 75±12% (no momento em que foi adicionada) | confirmada — F10/F12/F13/F15 e, em Chrome real, F19 (1 contexto do Playwright para 2 perfis); correção validada em Chrome 155: F19 |
| H6 *(adicionada depois do início do loop; ver Desvios)* | Pedir ao Chrome nativo, pela linha de comando, a abertura de uma página `chrome://` (aba de prova e permissão) funciona no Chrome atual | O Chrome aceita o pedido (código 0) mas não abre a página em experimento com Chrome real | Chromium (url_util.cc) + experimento com o Google Chrome instalado na CI | provável 75±12% (no momento em que foi adicionada) | morta — F17/F18: aceito com código 0 e descartado, em Chrome 155 e 156 |

Sub-perguntas: (1) escopo do endpoint/perfil; (2) identidade verificável da conexão; (3) redirecionamento Arena; (4) etapa exata e recibo; (5) recuperação simples sem trocar conta ou reenviar.
Fermi pré-fonte: perfis listados (2) × instalações selecionadas (1) × endpoints por instalação (1) = 2 escolhas para 1 endpoint (ordem 10^0); não esperar 2 identidades só pelo inventário. Latência do pré-voo local: comparação de 2 URLs + consultas DOM (0 chamadas de envio) → milissegundos, arredondamento a 0 possível. Não é medição de modelo.
Baseline de referência: usuário relata falha apesar de testes sintéticos; estes não estimam taxa de sucesso pessoal. Não existe amostra de contas reais para projetar homologação.

**Desvios do plano declarados:**
- H5 foi adicionada depois de ler F10 e F12, e H6 depois de a primeira tentativa de desenho (que dependia dela) falhar no Chrome real. Nenhuma existia no pré-registro; ambas têm a confiança prévia do momento. H1–H4 não foram reescritas; só a coluna de resultado.
- Erro meu no meio do loop: `verify_profile` passou a devolver `None` depois de uma edição de mensagem. O teste de integração em Chromium real pegou (“O perfil desta conexão não foi verificado”), os testes unitários não, porque nunca conferiam o retorno. Corrigido, com teste de mutação (sem o `return`, o teste falha).
- `gh search code` não existe nesta versão do CLI; `version.html` no caminho que a documentação sugeria retornou 404; a busca `site:` no repositório do MCP voltou vazia. Rotas trocadas para a API de busca de código do GitHub e para a árvore de diretórios do repositório, que localizaram os arquivos F7/F10–F14.
- A matriz abaixo trata H1–H5 como **não exclusivas** (cobrem eixos diferentes). Ela audita inconsistências; não calcula a probabilidade posterior de uma causa única.

## 2. Coleta/fichas
Datas de acesso: 2026-10-27, salvo indicação. “Revisão” é a data do último commit que tocou o arquivo (API do GitHub). Código lido da linha principal do Chromium não é, necessariamente, o do Chrome estável instalado; por isso as fichas F17, F19 e F20 vêm de execuções em **Google Chrome real**.

### Sub-pergunta 1 — o que o endpoint consentido realmente seleciona?
- **F1 · fato primário · Chrome DevTools MCP, docs/advanced-usage.md · revisão 2026-09-15 (ca6f834980)** · https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/ca6f83498014e74243117a2aa3830cf71091d64d/docs/advanced-usage.md · “If the user has multiple active profiles, the MCP server will connect to the default profile (as determined by Chrome).” *Discrimina H1 vs “escolher na lista seleciona o perfil”.* Documenta o MCP, não o Playwright.
- **F2 · fato primário · issue #694 do MCP · aberta 2025-12-19, comentário de mantenedor 2026-10-14** · https://github.com/ChromeDevTools/chrome-devtools-mcp/issues/694 · “there's no way to control which profile will be automated by the MCP server.” Mesmo projeto de F1: **não** conta como confirmação independente.
- **F10 · código primário · Chromium, chrome_devtools_manager_delegate.cc e devtools_browser_context_manager.cc · revisão 2026-10-23 (ee558d4082)** · https://github.com/chromium/chromium/blob/main/chrome/browser/devtools/chrome_devtools_manager_delegate.cc · em `CreateNewTarget`: “Profile* profile = ProfileManager::GetLastUsedProfile();”. *Discrimina H1/H5:* criar aba por CDP cai no perfil usado por último, não no escolhido.
- **F11 · código primário · remote_debugging_server.cc · revisão 2026-10-05 (9bb1a1e18b)** · “return local_state->GetBoolean(prefs::kDevToolsRemoteDebuggingEnabled);” [inferência: é o “Local State” da pasta de dados, logo a ativação é da instalação, não de cada perfil].
- **F12 · código primário · target_handler.cc · revisão 2026-10-21 (dabb873bb1)** · “target_info->SetBrowserContextId(host->GetBrowserContext()->UniqueId());”. Cada aba carrega a identidade real do seu perfil.
- **F13 · código primário · Playwright, crBrowser.ts na tag v1.64.1 (a fixada em requirements.txt) · revisão 2026-10-03 (626808d289), tag 2026-10-13 (cfe490d941)** · https://github.com/microsoft/playwright/blob/v1.64.1/packages/playwright-core/src/server/chromium/crBrowser.ts · “// TODO: auto attach only to pages from our contexts.” seguido de “context = this._defaultContext as CRBrowserContext;”. *Discrimina H5.*
- **F14 · código primário · devtools_http_handler.cc · revisão 2026-10-21 (dabb873bb1)** · “// If we require user approval, we do not require guid.”; no mesmo modo, os caminhos `/json` respondem 404. Nada nessa camada filtra por perfil.

### Sub-pergunta 2 — como provar o perfil recebido, sem ler cookies ou contas?
- **F6 · fato primário · Chromium, docs/user_data_dir.md · revisão 2025-09-12 (1f2119bcde)** · “Look for the `Profile Path` field. This gives the path to the profile directory.” Identifica a **pasta**, não a conta do site.
- **F7 · código primário · about_version.ts (revisão 2026-06-29, c077c11d20) e about_version.html (2026-08-11, 80664deb97)** · `getRequiredElement('profile_path').textContent = profilePath;`. O valor chega de forma assíncrona.
- **F5 · alegação comunitária, não homologada · govarthenan/chrome-profiles · publicada 2026-10-22** · “A reliable way to find the new tab: compare the page list before and after `open`.” **Contradiz F1** sem provar visibilidade por CDP. Aproveitado: abertura nativa; descartado: a promessa.

### Sub-pergunta 3 — o redirecionamento da Arena explica o texto recebido?
- **F3 · fato primário · Arena Team · publicado 2026-01-28** · https://arena.ai/blog/lmarena-is-now-arena · “That evolution is why we are now Arena. Now available at: arena.ai.”
- **F4 · fato local · revisão-base dfbf8d0** · “'lmarena': 'https://lmarena.ai/'” e “if origin(page.url) != origin(config.url): return 'wrong_origin'”. O texto que o usuário colou é exatamente `REMEDIES['wrong_origin']`: **não** é erro de apontamento de campo. *Discrimina H2 vs defeito de seletor.*

### Sub-pergunta 4 — que etapa falhou e por que “0 ms”?
- **F8 · fato local testado · commit 6de2131** · “sender.assert_not_called()”; “self.assertNotIn('response_wait_ms', result.timings)”. Origem configurada diferente da aberta → nenhuma chamada ao envio. *Mata H3:* o “0 ms” era a etapa de pré-voo rotulada como “inclui espera da resposta”.

### Sub-pergunta 5 — abrir o chat no perfil certo, sem trocar de conta nem reenviar
- **F9 · contraprova em Chromium na Actions 40515014165** · “test_removing_origin_guard_allows_send_to_wrong_destination_counterexample … ok”. Com o guard desligado **na fixture**, houve envio à origem errada. *Mata H4.*
- **F15 · fato local com teste de mutação** · browserapi_lab/llm_api.py (antes) escolhia “aba da mesma origem” em **qualquer** perfil. O teste `test_personal_chrome_never_matches_same_origin_tab_from_another_profile` **falhou** com o arquivo antigo (o prompt iria à aba “another-account”) e passa com a correção. Prova de lógica em fixture; não prova que ocorreu com o usuário.
- **F17 · experimento em Google Chrome real · Actions probe-perfis 40524842847 (Chrome 155.0.8059.39) e 40525730006 (Chrome 156.0.8078.47), 2026-10-27** · results/ci/probe-40525730006/native-open-probe.json · stdout do segundo processo: “Opening in existing browser session.” (código 0, 0,07 a 0,14 s). Página aberta de fato: `{'about_blank_with_fragment': False, 'chrome_version': False, 'chrome_inspect': False, 'http_loopback': True}`. *Mata H6:* o Chrome **aceita e descarta** `chrome://`, sem erro.
- **F18 · código primário · Chromium, chrome/browser/ui/startup/url_util.cc · revisão 2026-09-17 (bd587d54a3)** · https://github.com/chromium/chromium/blob/main/chrome/browser/ui/startup/url_util.cc · “return url.SchemeIsHTTPOrHTTPS() || url.spec() == url::kAboutBlankURL;” e “In Headless mode, allow any URL pattern that matches chrome:// scheme if the user explicitly allowed it.” Explica F17: só http(s) e exatamente `about:blank` entram por linha de comando.
- **F19 · fluxo REAL do produto em Chrome real, dois perfis · Actions probe-perfis 40526453697, 2026-10-27 ~14:59Z, Chrome 155.0.8059.39 sob xvfb** · results/ci/probe-40526453697/native-open-probe.json · `checks`: tags = pastas ✓, identidades distintas (`6BBA9E32` × `90D5077B`) ✓, reabertura isolada `{'Profile 1': 'Profile 1', 'Default': 'Default'}` com a **mesma origem** nas duas abas ✓, perfil inexistente rejeitado ✓; `playwright_contexts = 1` para 2 perfis. Cada sessão ≈ 1,0–1,2 s. *Confirma H5 e F13 em Chrome real.* Escopo: Chrome descartável em pasta temporária e sem aprovação por diálogo, não o Chrome pessoal.
- **F20 · falha antes da correção · Chrome 156.0.8078.47, probe-perfis 40525730006** · o `Default` passou; no `Profile 1` a prova **passou** (o Chrome respeitou `--profile-directory`, o Profile Path conferiu e o CDP viu a aba), mas abrir o chat falhou (“não abriu o chat no perfil escolhido a tempo”). [Especulação — teste segue: fechar a aba de prova fechava a única janela do perfil antes do pedido do chat.] Correção: a aba de prova vira a aba do chat. **Reteste em Chrome 156: PASS em 3 de 3** (matriz amostras 1 e 4 e VM da bateria) — ver F16. A causa (fechar a única janela do perfil) segue como explicação mais provável, não demonstrada isoladamente.
- **F16 · bateria completa e segunda amostra do experimento, commit final** · Commit final `6a25f44`, Actions `lab` 40529619157 (2026-10-27, concluída com sucesso): **370 testes em Chromium real sob xvfb, 206,084 s, OK (1 ignorado)**; revisão visual 14 testes, 33,548 s, OK; núcleo local 267 testes OK (17 de navegador ignorados por não haver navegador local). O experimento na VM da bateria: PASS em Google Chrome 156.0.8078.47 (identidades `8486D967` × `65A46B2E`). **Matriz de 4 VMs** (probe-perfis 40527555235, commit `4644b64`): PASS em 4 de 4, Chrome 156.0.8078.47 (amostras 1 e 4) e 155.0.8059.39 (amostras 2 e 3). Depois da matriz o único arquivo de produto alterado foi uma linha de texto em `chat.py`. Atualização automática 0.6.0 → 0.6.1 com supervisor e dois processos reais: PASS (`results/ci/profile-binding-061-updater/result.json`, runtime `37cd5863…e3b3`).

## 3. ACH — cada evidência contra todas as hipóteses
⊕ compatível/favorável · ⊖ inconsistente · 0 não decide.

| Evidência | H1 endpoint não escolhe perfil | H2 guard barra após mudança de origem | H3 “0 ms” = envio rápido | H4 retirar guard é seguro | H5 uso de abas ignorava o perfil | H6 pedido nativo de chrome:// funciona |
|---|---|---|---|---|---|---|
| F1/F2 padrão decidido pelo Chrome | ⊕ | 0 | 0 | 0 | 0 (é o MCP) | 0 |
| F3/F4 domínio novo + guard exato | 0 | ⊕ | ⊖ (neste mecanismo) | 0 | 0 | 0 |
| F5 promessa comunitária | tensão sem prova | 0 | 0 | 0 | 0 | 0 |
| F6/F7 Profile Path nativo | via de prova | 0 | 0 | 0 | via de prova | 0 |
| F8 sem chamada de envio | 0 | ⊕ | **⊖ decisiva** | 0 | 0 | 0 |
| F9 contraprova do guard | 0 | ⊕ | 0 | **⊖ decisiva** | 0 | 0 |
| F10 createTarget = último usado | ⊕ (refina) | 0 | 0 | 0 | ⊕ | 0 |
| F12 identidade por aba | meio de arbitragem | 0 | 0 | 0 | ⊕ | 0 |
| F13 Playwright agrupa perfis | ⊕ | 0 | 0 | 0 | **⊕⊕** | 0 |
| F15 teste de mutação | 0 | 0 | 0 | 0 | ⊕ | 0 |
| F17 Chrome real descarta chrome:// | 0 | 0 | 0 | 0 | 0 | **⊖ decisiva** |
| F18 só http(s) e about:blank | 0 | 0 | 0 | 0 | 0 | **⊖** |
| F19 Chrome real, 2 perfis, 1 contexto | ⊕ | 0 | 0 | 0 | **⊕⊕ decisiva** | 0 |

**Eliminadas:** H3 (F8), H4 (F9), H6 (F17/F18). **Sobrevivem e se somam:** H1, H2, H5. H6 era a base de duas funções do produto (a aba de prova e o botão “Permissão do Chrome”); sua morte mudou o desenho.

## 4. Premortem e linchpin
**Cenário (2027-10-27): a correção fracassou.** Causas plausíveis: a política de URLs de lançamento do Chrome mudou de novo (hoje só http(s) e `about:blank`); o Chrome do usuário não é o binário `google-chrome` (Flatpak/Snap); a aprovação por diálogo expõe só o perfil padrão; uma prova de pasta foi vendida como prova de conta.

| Linchpin (premissa que sustenta tudo) | Indicador de reversão | Verificação datável |
|---|---|---|
| O Chrome aceita http(s) em pedidos de linha de comando e `--profile-directory` escolhe o perfil | experimento `probe-perfis` deixa de dar PASS; mensagem “O Chrome não abriu a verificação do perfil escolhido” em uso real | a cada execução do probe (≈1,5 min por commit que toque o fluxo) e a cada Chrome estável; próxima conferência até 2026-11-27 |
| `chrome://version` abre por navegação CDP (não por linha de comando) | prova falha com “ler identificação do perfil” | idem |
| O que vale para o Chrome descartável vale para o modo de aprovação | primeira conexão real do usuário falha ou só enxerga o perfil padrão | **não verificado**: o diálogo de aprovação não pode ser aceito pela CI; depende do relato do usuário |
| Pasta correta ≠ conta correta | usuário vê avatar/modelo errado no site | a conferência manual continua obrigatória; o recibo diz “pasta” |

## 5. Resumo executivo (Kent: prévia → final)
- **[fato, F10+F13+F15+F19] “2 perfis → 1” vinha do desenho, não do rótulo.** Playwright junta perfis (confirmado em Chrome real: 1 contexto para 2 perfis), o Chrome cria aba no último usado e o nosso código casava origem entre perfis. Prévia quase-certo 93±6% (H1) → final **quase-certo 93±6%** para o mecanismo; 2 projetos independentes (Chromium, Playwright) + código local + Chrome real. *Não* prova que foi só isso no seu notebook.
- **[fato, F3/F4/F8] O texto recebido é a etapa de endereço, sem envio.** Prévia provável 75±12% (H2) → final **50±10%** para “foi a mudança lmarena→arena” no seu caso: compatível, não observado; H5 também produz esse texto.
- **[fato, F8] “0 ms” não era tempo de modelo.** Prévia provavelmente-não 30% → final quase-certo-não 7%.
- **[fato, F9] Relaxar o guard de origem é inseguro.** Prévia provavelmente-não 30% → final quase-certo-não 7%.
- **[fato, F17/F18] Pedir `chrome://` ao Chrome pela linha de comando não funciona e não avisa.** Prévia provável 75±12% de funcionar (H6) → final **quase-certo-não 7%**; duas versões de Chrome real + fonte primária.
- **[fato, F19] O fluxo novo seleciona e separa dois perfis num Chrome real descartável.** Prévia 50±10% → final **provável 75±12%** para o Chrome real do usuário (o teste não passa pelo diálogo de aprovação nem usa conta real). Reteste em Chrome 156 e 155: PASS em 7 de 7 execuções do fluxo novo (F16/F19).

**Implementado:** aba de prova local `http://127.0.0.1` pedida ao Chrome nativo no perfil escolhido; navegação por CDP até `chrome://version` para ler o Profile Path; `browserContextId` real por aba; a aba de prova vira a aba do chat (nada de fechar a única janela do perfil); nenhuma aba de outro perfil é usada; serviço de API local corrigido; migração lmarena→arena só com a sua confirmação; recibo diz etapa, origem, pasta confirmada e se algo foi enviado; o texto da permissão agora manda **digitar** `chrome://inspect/#remote-debugging`.

## 6. Surpresa & implicação
- **Esperava:** H6, “provável 75±12%”, pré-registrada em 2026-10-27 (como desvio): bastaria pedir ao Chrome a página `chrome://version` no perfil escolhido.
- **Veio:** F17 · 2026-10-27 · results/ci/probe-40525730006/native-open-probe.json — “Opening in existing browser session.”, código 0, e `chrome_version: False` (nenhuma página aberta); F18 — “return url.SchemeIsHTTPOrHTTPS() || url.spec() == url::kAboutBlankURL;”.
- **Divergência:** inversão de pilar, não fator numérico. O Chrome responde **sucesso** a um pedido que descartou. Baseline da classe: ferramentas que “pedem ao navegador para abrir uma página” costumam tratar código 0 como sucesso; não encontrei estatística (lacuna).
- **Implicação:** sem o achado → o botão “Permissão do Chrome” e a prova de perfil seriam não-operações silenciosas (e o painel diria “Chrome solicitado”); com ele → só http(s) entra pela linha de comando, a prova navega por CDP e o texto de permissão manda digitar o endereço. Muda a decisão de “abrir página interna” para “abrir página local e navegar por CDP”.
- **Premortem:** se a política de URLs de lançamento mudar, o probe deixa de dar PASS → verificar a cada Chrome estável, até 2026-11-27.
- **Confiança final (Kent):** quase-certo 93±6% sobre o mecanismo e sobre H6 morta; fontes independentes: Chromium, Playwright e dois Chrome reais. T1 ✓ (a premissa é falsificável pelo probe), T2 ✓ (H6 vs H5), T3 ✓ (contraria o desenho anterior), T4 ✓ (ação e indicador datável), T5 n/a, T6 ✓ (específico de Chrome/Playwright).

## 7. Comparativo e alternativas descartadas
| Opção | Resultado |
|---|---|
| Renomear/reordenar a lista de perfis (0.6.0) | descartada: não muda a conexão (F1/F10/F13) |
| Só verificar o contexto padrão por CDP | descartada: não prova a aba antiga nem o perfil de abas novas |
| Relaxar o guard de origem | descartada por F9 |
| `context.new_page()` e checar depois | descartada: cai no último usado (F10); só serve como falha fechada |
| Aba de prova `chrome://version` pedida pela linha de comando | **descartada por F17/F18** (aceita e descartada) |
| Fechar a aba de prova antes de abrir o chat | descartada por F20 (derruba a única janela do perfil) |
| Copiar perfil / `user_data_dir` novo / Guest | descartada: perde sessão e viola a regra do projeto |
| Extensão ou ponte por perfil | não implementada; alternativa se o probe falhar no Chrome estável |
| **Aba de prova http local + navegação CDP + `browserContextId` por aba + guard de origem; a aba de prova vira a do chat** | **escolhida** |

**Contradição técnica (TRIZ):** “usar qualquer perfil pessoal” × “só o que o transporte expõe com segurança”. Resolvida com *prova antes do uso* e falha fechada; sem analogia entre campos.

## 8. Lacunas & incertezas
- **Não verificado:** o Chrome pessoal do usuário. O diálogo de aprovação (Chrome 144+) não pode ser aceito na CI; os experimentos usam `--remote-debugging-port` em pasta descartável. Se, com a aprovação, o Chrome expuser só o perfil padrão, o modo para com mensagem clara em vez de usar o perfil errado.
- Não observei a URL efetiva, o DOM, a versão do Chrome nem o perfil do usuário: não afirmo qual mecanismo produziu o texto recebido.
- O Chromium descartável sem janela respondeu `SHUTDOWN`/código 21 ao pedido de entrega (Actions 40519568084); com Chrome real e com janela deu código 0. Causa **não determinada**; por isso os testes bloqueantes emulam o pedido por CDP e o hand-off real fica no probe.
- Runners diferentes trouxeram Chrome 155 e 156. O 156 falhou antes da correção (F20) e passou depois, em 3 de 3; a explicação da falha anterior não foi isolada.
- Flatpak/Snap, outros nomes de binário e pastas de dados personalizadas não foram testados; pasta personalizada tem mensagem própria.
- Não li `TargetHandler::GetTargets`/auto-attach para saber se alguma camada filtra por perfil em modo de aprovação.
- Não achei estatística de falha para “automação sobre perfil pessoal”.

## 9. Fontes
Todas acessadas em 2026-10-27; a data de publicação/revisão está em cada ficha.
- F1 https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/ca6f83498014e74243117a2aa3830cf71091d64d/docs/advanced-usage.md — perfil padrão decidido pelo Chrome.
- F2 https://github.com/ChromeDevTools/chrome-devtools-mcp/issues/694 — não há como escolher perfil.
- F3 https://arena.ai/blog/lmarena-is-now-arena — mudança para arena.ai.
- F5 https://github.com/govarthenan/chrome-profiles/tree/4f4cd3b9bc658f4a4587244ed620593cfc2fc622 — alegação comunitária (não adotada).
- F6 https://github.com/chromium/chromium/blob/main/docs/user_data_dir.md — Profile Path identifica a pasta.
- F7 https://github.com/chromium/chromium/blob/main/components/webui/version/resources/about_version.ts e .html — campo `profile_path`.
- F10 https://github.com/chromium/chromium/blob/main/chrome/browser/devtools/chrome_devtools_manager_delegate.cc e devtools_browser_context_manager.cc — perfil usado por último.
- F11 https://github.com/chromium/chromium/blob/main/chrome/browser/devtools/remote_debugging_server.cc — ativação em estado global.
- F12 https://github.com/chromium/chromium/blob/main/content/browser/devtools/protocol/target_handler.cc — `browserContextId` por aba.
- F13 https://github.com/microsoft/playwright/blob/v1.64.1/packages/playwright-core/src/server/chromium/crBrowser.ts — agrupamento no contexto padrão.
- F14 https://github.com/chromium/chromium/blob/main/content/browser/devtools/devtools_http_handler.cc — modo de aprovação, `/json` 404.
- F18 https://github.com/chromium/chromium/blob/main/chrome/browser/ui/startup/url_util.cc — só http(s) e `about:blank` por linha de comando.
- F4/F8/F9/F15/F16/F17/F19/F20: repositório (`tests/`, `scripts/native_open_probe.py`) e evidências em `results/ci/probe-*/` e `results/ci/<run>/`.
