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
| H5 *(adicionada depois do início do loop; ver Desvios)* | Mesmo com o perfil certo aberto, o uso de abas ignorava o perfil: Playwright agrupa abas de todos os perfis, criar aba por CDP usa o perfil usado por último e o código casava “mesma origem” entre perfis | Fonte primária mostra que as abas de perfis diferentes ficam em contextos separados no Playwright e que createTarget respeita o perfil pedido | Playwright (tag fixada) + Chromium + código local | provável 75±12% (no momento em que foi adicionada) | confirmada no código e nas fontes — F10/F12/F13/F15; correção validada em CI: ver F16 |

Sub-perguntas: (1) escopo do endpoint/perfil; (2) identidade verificável da conexão; (3) redirecionamento Arena; (4) etapa exata e recibo; (5) recuperação simples sem trocar conta ou reenviar.
Fermi pré-fonte: perfis listados (2) × instalações selecionadas (1) × endpoints por instalação (1) = 2 escolhas para 1 endpoint (ordem 10^0); não esperar 2 identidades só pelo inventário. Latência do pré-voo local: comparação de 2 URLs + consultas DOM (0 chamadas de envio) → milissegundos, arredondamento a 0 possível. Não é medição de modelo.
Baseline de referência: usuário relata falha apesar de testes sintéticos; estes não estimam taxa de sucesso pessoal. Não existe amostra de contas reais para projetar homologação.

**Desvios do plano declarados:**
- H5 foi adicionada depois de ler F10 e F12 (não existia no pré-registro). H1–H4 não foram reescritas; só a coluna de resultado.
- `gh search code` não existe nesta versão do CLI; `version.html` no caminho que a documentação sugeria retornou 404; a busca `site:` no repositório do MCP voltou vazia. Rotas trocadas para a API de busca de código do GitHub e para a árvore de diretórios do repositório, que localizaram os arquivos F7/F10–F14.
- A matriz abaixo trata H1–H5 como **não exclusivas** (cobrem eixos diferentes). Ela audita inconsistências; não calcula a probabilidade posterior de uma causa única.

## 2. Coleta/fichas
Datas de acesso: 2026-10-27, salvo indicação. “Revisão” é a data do último commit que tocou o arquivo (API do GitHub). Código lido da linha principal do Chromium não é, necessariamente, o do Chrome estável instalado.

### Sub-pergunta 1 — o que o endpoint consentido realmente seleciona?
- **F1 · fato primário · Chrome DevTools MCP, docs/advanced-usage.md · revisão 2026-09-15 (ca6f834980)** · https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/ca6f83498014e74243117a2aa3830cf71091d64d/docs/advanced-usage.md · “If the user has multiple active profiles, the MCP server will connect to the default profile (as determined by Chrome).” *Discrimina H1 vs “escolher na lista seleciona o perfil”.* Documenta o MCP, não o Playwright.
- **F2 · fato primário · issue #694 do MCP · aberta 2025-12-19, comentário de mantenedor 2026-10-14** · https://github.com/ChromeDevTools/chrome-devtools-mcp/issues/694 · “there's no way to control which profile will be automated by the MCP server.” Solução (`--profile-directory`) ainda “em avaliação”. Mesmo projeto de F1: **não** conta como confirmação independente.
- **F10 · código primário · Chromium, chrome_devtools_manager_delegate.cc e devtools_browser_context_manager.cc · revisão 2026-10-23 (ee558d4082)** · https://github.com/chromium/chromium/blob/main/chrome/browser/devtools/chrome_devtools_manager_delegate.cc · em `CreateNewTarget`: “Profile* profile = ProfileManager::GetLastUsedProfile();”; em `GetDefaultBrowserContext`: “auto* last_profile = ProfileManager::GetLastUsedProfileIfLoaded();”. *Discrimina H1/H5 vs “Default é o diretório Default”:* o padrão é o **último usado**; criar aba por CDP cai nele, não no perfil escolhido.
- **F11 · código primário · remote_debugging_server.cc · revisão 2026-10-05 (9bb1a1e18b)** · https://github.com/chromium/chromium/blob/main/chrome/browser/devtools/remote_debugging_server.cc · “return local_state->GetBoolean(prefs::kDevToolsRemoteDebuggingEnabled);” [inferência: `local_state` é o “Local State” da pasta de dados, logo a ativação é da instalação, não de cada perfil]. Não pedir ao usuário que ative por perfil.
- **F12 · código primário · target_handler.cc · revisão 2026-10-21 (dabb873bb1)** · https://github.com/chromium/chromium/blob/main/content/browser/devtools/protocol/target_handler.cc · “target_info->SetBrowserContextId(host->GetBrowserContext()->UniqueId());”. *Discrimina:* cada aba carrega a identidade real do seu perfil, que o aplicativo pode usar para filtrar.
- **F13 · código primário · Playwright, packages/playwright-core/src/server/chromium/crBrowser.ts na tag v1.64.1 (a versão fixada em requirements.txt) · revisão 2026-10-03 (626808d289), tag 2026-10-13 (cfe490d941)** · https://github.com/microsoft/playwright/blob/v1.64.1/packages/playwright-core/src/server/chromium/crBrowser.ts · “// TODO: auto attach only to pages from our contexts.” seguido de “context = this._defaultContext as CRBrowserContext;”. *Discrimina H5 vs “o Playwright separa os perfis”:* contextos desconhecidos caem no contexto padrão; `context.pages` mistura perfis.
- **F14 · código primário · devtools_http_handler.cc · revisão 2026-10-21 (dabb873bb1)** · https://github.com/chromium/chromium/blob/main/content/browser/devtools/devtools_http_handler.cc · “// If we require user approval, we do not require guid.”; no mesmo modo, os caminhos `/json` respondem 404. [inferência: nada nessa camada filtra por perfil; o filtro, se existir, está em outra]. Confirma por que o aplicativo lê o arquivo de porta e não faz sondagem HTTP.

### Sub-pergunta 2 — como provar o perfil recebido, sem ler cookies ou contas?
- **F6 · fato primário · Chromium, docs/user_data_dir.md · revisão 2025-09-12 (1f2119bcde)** · https://github.com/chromium/chromium/blob/main/docs/user_data_dir.md · “Look for the `Profile Path` field. This gives the path to the profile directory.” Identifica a **pasta**, não a conta do site.
- **F7 · código primário · about_version.html (revisão 2026-08-11, 80664deb97) e about_version.ts (revisão 2026-06-29, c077c11d20)** · https://github.com/chromium/chromium/blob/main/components/webui/version/resources/about_version.ts · `getRequiredElement('profile_path').textContent = profilePath;` e `<td class="version" id="profile_path">`. O valor chega de forma assíncrona: esperar o campo ficar não vazio.
- **F5 · alegação comunitária, não homologada · govarthenan/chrome-profiles · publicada 2026-10-22 (4f4cd3b9bc)** · https://github.com/govarthenan/chrome-profiles/tree/4f4cd3b9bc658f4a4587244ed620593cfc2fc622 · “A reliable way to find the new tab: compare the page list before and after `open`.” Promete dirigir outros perfis; seu script só abre janelas. **Contradiz F1** sem provar visibilidade por CDP. Aproveitado: abertura nativa; descartado: a promessa.

### Sub-pergunta 3 — o redirecionamento da Arena explica o texto recebido?
- **F3 · fato primário · Arena Team · publicado 2026-01-28** · https://arena.ai/blog/lmarena-is-now-arena · “That evolution is why we are now Arena. Now available at: arena.ai.” (O trecho de busca dizia agosto; a página primária diz janeiro: vale a da página.)
- **F4 · fato local · revisão-base dfbf8d0** · browserapi_lab/config.py e chat.py · “'lmarena': 'https://lmarena.ai/'” e “if origin(page.url) != origin(config.url): return 'wrong_origin'”. O texto que o usuário colou é exatamente `REMEDIES['wrong_origin']`: **não** é erro de apontamento de campo. *Discrimina H2 vs defeito de seletor.*

### Sub-pergunta 4 — que etapa falhou e por que “0 ms”?
- **F8 · fato local testado · commit 6de2131** · tests/test_navigation.py · “sender.assert_not_called()”; “self.assertNotIn('response_wait_ms', result.timings)”. Núcleo: 243 testes OK. Origem configurada diferente da aberta → nenhuma chamada ao envio. *Mata H3:* o “0 ms” era a etapa de pré-voo rotulada como “inclui espera da resposta”. (O relógio já cobria o pré-voo; o defeito era o rótulo, não a medição.)

### Sub-pergunta 5 — recuperar sem trocar de conta nem reenviar
- **F9 · contraprova em Chromium na Actions 40515014165 (2026-10-27)** · tests/test_chat_browser.py · “test_removing_origin_guard_allows_send_to_wrong_destination_counterexample … ok”. Com o guard desligado **na fixture**, houve envio para a origem errada. *Mata H4.* Aquela execução teve outros 2 testes com erro; não é aprovação da suíte.
- **F15 · fato local com teste de mutação · 2026-10-27** · browserapi_lab/llm_api.py (antes) · `matches=[p for p in self.session.context.pages if ... origin(p.url)==target]` escolhia aba da mesma origem em **qualquer** perfil. O teste `test_personal_chrome_never_matches_same_origin_tab_from_another_profile`, rodado com o arquivo antigo, **falhou** (o prompt iria à aba “another-account”) e, com a correção, passa. *Discrimina H5:* o vazamento era real na lógica. Prova de lógica em fixture; não prova que ocorreu com o usuário (o teste do painel não usa esse caminho).
- **F16 · resultado da CI para o desenho novo · Actions 40519568084 (commit 627fcfa)** · **PENDENTE no momento desta escrita.** Preencher apenas esta ficha e a coluna de resultado.

## 3. ACH — cada evidência contra todas as hipóteses
⊕ compatível/favorável · ⊖ inconsistente · 0 não decide.

| Evidência | H1 endpoint não escolhe perfil | H2 guard barra após mudança de origem | H3 “0 ms” = envio rápido | H4 retirar guard é seguro | H5 uso de abas ignorava o perfil |
|---|---|---|---|---|---|
| F1/F2 padrão decidido pelo Chrome | ⊕ | 0 | 0 | 0 | 0 (é o MCP) |
| F3/F4 domínio novo + guard exato | 0 | ⊕ | ⊖ (neste mecanismo) | 0 | 0 |
| F5 promessa comunitária | tensão sem prova | 0 | 0 | 0 | 0 |
| F6/F7 Profile Path nativo | via de prova | 0 | 0 | 0 | via de prova |
| F8 sem chamada de envio | 0 | ⊕ | **⊖ decisiva** | 0 | 0 |
| F9 contraprova do guard | 0 | ⊕ | 0 | **⊖ decisiva** | 0 |
| F10 createTarget = último usado | ⊕ (refina) | 0 | 0 | 0 | ⊕ |
| F11 ativação por instalação | 0 | 0 | 0 | 0 | 0 |
| F12 identidade por aba | meio de arbitragem | 0 | 0 | 0 | ⊕ (permite filtrar) |
| F13 Playwright agrupa perfis | ⊕ | 0 | 0 | 0 | **⊕⊕ decisiva** |
| F15 teste de mutação | 0 | 0 | 0 | 0 | ⊕ |

**Eliminadas:** H3 (F8) e H4 (F9). **Sobrevivem e se somam:** H1, H2, H5. “Quem matou quem”: F8 matou H3; F9 matou H4. F13 transformou H1 de “limitação de conexão” em “o aplicativo apagava a fronteira entre perfis dos dois lados”.

## 4. Premortem e linchpin
**Cenário (2027-10-27): a correção fracassou.** Causas plausíveis: o Chrome estável deixou de expor a aba interna `chrome://version` por CDP; o pedido nativo `--profile-directory` mudou de comportamento ou o Chrome do usuário não é o binário `google-chrome` (Flatpak/Snap); uma prova de pasta foi vendida como prova de conta.

| Linchpin (premissa que sustenta tudo) | Indicador de reversão | Verificação datável |
|---|---|---|
| A aba de prova com código único aparece por CDP e mostra o Profile Path | mensagem “O Chrome não abriu a verificação do perfil escolhido” em uso real; falha do teste de integração | a cada versão estável do Chrome; conferir `doctor-browser.json` da CI (Chrome 155.0.8059.39 em 2026-10-27) e o teste F16 até 2026-11-27 |
| Pedido nativo de perfil é entregue ao processo existente | `open_profile` recusado ou aba nova em outro perfil | idem; o código para sem reutilizar |
| Pasta correta ≠ conta correta | usuário vê avatar/modelo errado no site | a conferência manual continua obrigatória; o recibo diz “pasta” |
| Código lido da linha principal vale para o Chrome estável | prova falha só no estável | teste real do usuário no Linux Lite (não feito) |

## 5. Resumo executivo (Kent: prévia → final)
- **[fato, F10+F13+F15] A falha “2 perfis → 1” vinha do desenho, não do rótulo.** Playwright junta perfis, o Chrome cria aba no último usado e o nosso código casava origem entre perfis. Prévia: quase-certo 93±6% (H1) → final: **quase-certo 93±6%** para o mecanismo; fontes independentes: 2 projetos (Chromium, Playwright) + código local. *Não* é prova de que foi isso, e só isso, no seu notebook.
- **[fato, F3/F4/F8] O texto recebido é a etapa de endereço, sem envio.** Prévia: provável 75±12% (H2) → final: **50±10%** para “foi a mudança lmarena→arena” no seu caso (compatível, não observada). O número caiu porque H5 oferece outra causa para o mesmo texto.
- **[fato, F8] “0 ms” não era tempo de modelo.** Prévia: provavelmente-não 30% (H3 de ser envio) → final: quase-certo-não 7%.
- **[fato, F9] Relaxar o guard de origem é inseguro.** Prévia: provavelmente-não 30% → final: quase-certo-não 7%.
- **[inferência, F16 pendente] O desenho novo seleciona o perfil escolhido.** Prévia (ao decidir): 50±10% → final: *ver F16*; mesmo com CI verde só vale para Chromium descartável, não para o seu Chrome.

**Implementado:** abertura nativa da prova e do chat no perfil escolhido; prova pelo Profile Path; `browserContextId` real por aba; nenhuma aba de outro perfil é usada; serviço de API local corrigido; migração lmarena→arena só com a sua confirmação, preservando os campos; recibo diz etapa, origem e se algo foi enviado; painel mostra “Perfil confirmado pelo Chrome: pasta”.

## 6. Surpresa & implicação
- **Esperava:** H1, “quase-certo 93±6%”, pré-registrada em 2026-10-27: o endpoint não escolhe o perfil, então bastaria bloquear quando o perfil recebido fosse outro.
- **Veio:** F13 · 2026-10-27 · https://github.com/microsoft/playwright/blob/v1.64.1/packages/playwright-core/src/server/chromium/crBrowser.ts — “// TODO: auto attach only to pages from our contexts.”; F15 — o teste de mutação mostrou que o nosso serviço de API enviaria o prompt à aba de outro perfil.
- **Divergência:** não é um fator numérico (o Fermi de 2 escolhas para 1 endpoint se confirmou). É **inversão de pilar**: o risco não era só “perfil errado conectado”, era “perfil certo aberto e aba errada usada” — e isso é de segurança (conta alheia), não de conveniência. Baseline da classe: ferramentas de automação sobre navegador pessoal geralmente tratam o perfil como atributo do processo, não da aba; não encontrei estatística de casos (lacuna).
- **Implicação:** sem o achado → renomear/reordenar a lista e avisar “confira a conta”, deixando o envio ir para a aba errada; com ele → ligar **toda** aba ao `browserContextId` e abrir o chat pelo Chrome nativo. Muda a decisão de “melhorar rótulos” para “remover o casamento de aba entre perfis”.
- **Premortem:** se o Chrome estável não expõe a aba de prova, o modo para (falha fechada) em vez de usar o primeiro contexto → indicador: mensagem de prova ausente; verificar até 2026-11-27.
- **Confiança final (Kent):** quase-certo 93±6% sobre o mecanismo; fontes independentes: 2/2 (Chromium, Playwright), mais código local. Testes T1–T6: T1 ✓ (pode ser invertida se uma versão do Playwright separar perfis), T2 ✓ (H5 vs H1), T3 ✓ (contraria o plano de só bloquear), T4 ✓ (ação e indicador datável), T5 n/a (sem analogia entre campos), T6 ✓ (frase específica de Chromium+Playwright; não sobrevive à troca de tema).

## 7. Comparativo e alternativas descartadas
| Opção | Resultado |
|---|---|
| Renomear/reordenar a lista de perfis (versão 0.6.0) | descartada: não muda a conexão (F1/F10/F13) |
| Só verificar o contexto padrão por CDP | descartada: não prova a aba antiga nem o perfil de abas novas (F10/F13) |
| Relaxar o guard de origem | descartada por F9 (envio à origem errada) |
| `context.new_page()` e checar depois | descartada: cai no último usado (F10); só serve como falha fechada |
| Copiar perfil / `user_data_dir` novo / Guest | descartada: perde sessão, duplica dispositivo, viola a regra do projeto |
| Extensão ou ponte por perfil | não implementada: exigiria distribuição e permissões novas; fica como alternativa se a prova falhar no Chrome estável |
| **Abertura nativa + prova pelo Profile Path + `browserContextId` por aba + guard de origem** | **escolhida** |

**Contradição técnica (TRIZ):** “usar qualquer perfil pessoal” × “só o que o transporte expõe com segurança”. Resolvida com *prova antes do uso* e falha fechada; não há analogia entre campos nesta síntese.

## 8. Lacunas & incertezas
- Não observei a URL efetiva, o DOM, a versão do Chrome nem o perfil do usuário. Não posso afirmar qual dos mecanismos produziu o texto recebido.
- Não li `TargetHandler::GetTargets`/o auto-attach para saber se alguma camada filtra por perfil em modo de aprovação. O teste F16 roda em modo padrão, não em modo de aprovação.
- Código do Chromium lido: linha principal (arquivos revisados entre 2026-06 e 2026-10); Chrome estável pode divergir.
- Chrome por Flatpak/Snap, outros nomes de binário e pastas de dados personalizadas não foram testados; a pasta personalizada produz mensagem própria, não “troca de conta”.
- Não achei estatística de falha para a classe “automação sobre perfil pessoal” (busca por “multiple profiles” trouxe só issues).
- Sub-perguntas abertas pelos achados: o Chrome estável mantém `chrome://version` acessível por CDP? O pedido nativo funciona em Snap/Flatpak?

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
- F4/F8/F9/F15/F16: repositório, `tests/` e Actions (commits citados nas fichas).
