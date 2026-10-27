# Dossiê: perfis CDP e falha antes do envio
**Data:** 2026-10-27 · **Rotas planejadas:** web em paralelo, documentação/código primário via GitHub, testes locais/Actions.
**Pergunta original → operacional:** “melhorar tudo; dois perfis vão para um e teste falha” → decidir como vincular o Chrome realmente conectado ao perfil selecionado e tratar redirecionamentos sem enviar para outra conta/site.

## 1. Hipóteses pré-registradas
Escritas após leitura dos anexos e código local, antes da coleta web; só atualizar Resultado.
| # | Hipótese afirmativa | O que a mata | Fonte-alvo | Kent prévia | Resultado |
|---|---|---|---|---|---|
| H1 | O endpoint por instalação não seleciona o diretório do perfil no CDP; as duas opções podem conectar ao mesmo contexto | Evidência primária de seleção de Profile N pelo endpoint/BrowserContext usado | Chrome DevTools MCP/Chromium + browser.py | quase-certo 93±6%, código já lido | favorável — F1/F2 e código local; seleção arbitrária não comprovada |
| H2 | O guard de origem impede o envio depois de um redirecionamento do domínio do chat | Origem configurada e efetiva iguais no caso; teste reproduz sem guard de origem | origem de Arena e preflight/config locais | provável 75±12% | mecanismo reproduzido — F3/F4/F8; causa pessoal ainda não confirmada |
| H3 | O “0 ms” prova que houve uma tentativa de envio rápida | preflight retornar antes de send_message e nenhum envio em teste | chat.exchange + teste de regressão | provavelmente-não 30% | morta — F8: sender não chamado; nenhuma espera de resposta |
| H4 | Remover o guard de origem resolve o problema com segurança | Um destino alheio/login passa a receber um envio em teste | teste de guard com site não relacionado | provavelmente-não 30% | morta — F9: guard removido permitiu envio na origem errada (fixture) |

Sub-perguntas: (1) escopo do endpoint/perfil; (2) identidade verificável da conexão; (3) redirecionamento Arena; (4) etapa exata e recibo; (5) recuperação simples sem trocar conta ou reenviar.
Fermi pré-fonte: perfis listados (2) × instalações selecionadas (1) × endpoints por instalação (1) = 2 escolhas para 1 endpoint (ordem 10^0); não esperar 2 identidades só pelo inventário. Latência do pré-voo local: comparação de 2 URLs + consultas DOM (0 chamadas de envio) → milissegundos, arredondamento a 0 possível. Não é medição de modelo.
Baseline de referência: usuário relata falha apesar de testes sintéticos; estes não estimam taxa de sucesso pessoal. Não existe amostra de contas reais para projetar homologação.

## 2. Coleta/fichas
Todas as datas de acesso abaixo: 2026-10-27. Código local é evidência do produto, não amostra de contas pessoais.

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

- **F8 · fato local testado · implementação 2026-10-27, commit 6de2131** · tests/test_navigation.py e browserapi_lab/chat.py · “sender.assert_not_called()” / “self.assertNotIn('response_wait_ms', result.timings)”. Execução do núcleo: 243 testes, 20,017 s, OK, 17 skips de classes com navegador. O teste reproduz endereço configurado lmarena.ai vs efetivo arena.ai; nenhuma chamada ao sender. Suporta H2 como mecanismo e mata H3. Não demonstra o redirecionamento no computador pessoal.
- **F9 · contraprova executada em Chromium na Actions 40515014165 (2026-10-27), teste passou embora suíte geral tenha falhado em dois outros testes** · tests/test_chat_browser.py::test_removing_origin_guard_allows_send_to_wrong_destination_counterexample · altera origem configurada para unrelated.example mantendo fixture local, verifica bloqueio, desliga guard só no teste e verifica envio. Trecho do log: “test_removing_origin_guard_allows_send_to_wrong_destination_counterexample (test_chat_browser.TestChatWorkflow.test_removing_origin_guard_allows_send_to_wrong_destination_counterexample) ... ok”. Nunca executar em conta pessoal. A suíte geral dessa rodada teve 343 testes, 2 erros, 1 skip; não apresentá-la como aprovada.

### Rodada 3 — estreitamento do “perfil padrão” e vínculo por target
F10 — Chromium, main, publication unknown, accessed 2026-10-27, via gh API.
https://github.com/chromium/chromium/blob/main/chrome/browser/devtools/devtools_browser_context_manager.cc
“Profile* profile = ProfileManager::GetLastUsedProfile();”
“auto* last_profile = ProfileManager::GetLastUsedProfileIfLoaded();”
GetBrowserContexts enumerates otr_profiles_, not personal profile inventory. This narrows “default” to last used in inspected revision; do not equate with directory Default. Trunk is not user's Chrome version.
F11 — Chromium, main, publication unknown, accessed 2026-10-27.
https://github.com/chromium/chromium/blob/main/chrome/browser/devtools/remote_debugging_server.cc
“return local_state->GetBoolean(prefs::kDevToolsRemoteDebuggingEnabled);”
The permission server enablement is installation Local State. No basis for asking to disable remote debugging separately in each personal profile.
F12 — Chromium, main, publication unknown, accessed 2026-10-27.
https://github.com/chromium/chromium/blob/main/content/browser/devtools/protocol/target_handler.cc
“target_info->SetBrowserContextId(host->GetBrowserContext()->UniqueId());”
Each target carries the actual BrowserContext identity. A default-context probe does NOT alone prove an arbitrary existing chat tab belongs to it. Required: bind a browser-owned nonce tab opened natively in selected profile, prove its Profile Path, retain browserContextId only in memory and filter chat targets by it; no arbitrary context[0].

A investigação adicional mudou o desenho: não só verificar uma nova aba no contexto padrão (isso não prova o perfil de uma aba antiga). Abrir nativamente uma aba chrome://version com nonce no perfil escolhido, reencontrá-la no CDP, verificar o diretório real e reter o browserContextId. Filtrar/revalidar a identidade das abas antes de navegar. Seleção nativa é tentativa verificada, nunca garantia sem prova. Teste de alternância entre dois perfis descartáveis adicionado; pendente CI.

## 3. ACH — cruzamento por evidência
As hipóteses cobrem eixos diferentes e **não são mutuamente exclusivas**. Esta matriz audita inconsistências, não calcula probabilidades posteriores de causas exclusivas. ⊕ compatível/favorável; ⊖ inconsistente; 0 não decide.

| Evidência | H1 perfil não selecionado | H2 guard após mudança de origem | H3 0 ms prova envio | H4 retirar guard é seguro |
|---|---|---|---|---|
| F1/F2: default determinado pelo Chrome | ⊕ | 0 | 0 | 0 |
| F3/F4: domínio oficial novo, default antigo e guard exato | 0 | ⊕ | ⊖ para esse mecanismo | 0 |
| F5: alegação comunitária de abrir outro perfil | tensão: alegação contrária, sem prova CDP | 0 | 0 | 0 |
| F6/F7: identidade nativa via Profile Path | alternativa verificável, não seleção | 0 | 0 | 0 |
| F8: bloqueio pré-voo, sender não chamado | 0 | ⊕ mecanismo | ⊖ decisiva | 0 |
| F9: contrafactual do guard em fixture | 0 | ⊕ mecanismo | 0 | ⊖ decisiva |
| F10/F11/F12: last-used, estado global, identidade por target | estreita H1: nativo pode selecionar, endpoint sozinho não | 0 | 0 | 0 |

**Eliminada H3:** uma execução pode terminar antes do envio. O relógio original já media o pré-voo; não é correto dizer que o timer só começava depois. O defeito demonstrado é o rótulo “inclui espera da resposta” em um ramo onde não houve espera. H4 eliminada por F9: desligando o guard na fixture, houve envio apesar de origem configurada alheia. H1/H2 podem coexistir; não reduzir a falha do usuário a um seletor.

## 4. Premortem e linchpin
**Cenário 2027-10-27:** a correção fracassou porque uma prova de diretório foi vendida como prova de conta, ou o Chrome mudou a página interna e o app voltou a escolher o primeiro contexto silenciosamente.

| Risco / premissa de sustentação | Indicador de reversão | Verificação datável |
|---|---|---|
| chrome://version pertence ao navegador e fornece Profile Path | campo ausente, vazio ou caminho divergente | teste em Chromium em cada build; revisão 2026-10-27; falhar fechado |
| Diretório correto não implica login correto no chat | usuário vê avatar/conta diferente no site | confirmação manual antes de cada envio; não registrar email/cookies |
| Allow pode só conceder perfil padrão | inventário tem 2 escolhas mas prova só passa em 1 | testar ambas na instalação real antes de declarar múltiplos perfis homologados |
| Migração é lmarena.ai HTTPS → arena.ai HTTPS | outro host/porta/subdomínio ou URL com token | testes negativos em cada build; não oferecer confiança genérica |
| Fixture não replica o site pessoal | teste sintético passa e usuário continua bloqueado | não marcar homologação pessoal; próxima observação real deve distinguir perfil/origem/etapa sem conteúdo privado |

## 5. Resumo executivo — decisão
**Decisão única:** manter o transporte consentido, mas torná-lo **verificado e fail-closed**: perfil real antes do chat; confirmação explícita de migração; recibo da etapa antes de recomendar reconfigurar seletores.

- [Fato F1/F2 + inferência de código] Listar diretórios não seleciona CDP. H1: quase-certo 93±6% prévia → quase-certo 93±6% final sobre o defeito arquitetural, **não sobre a causa exclusiva no notebook**. Fontes primárias F1/F2 são correlacionadas.
- [Fato F3/F4 + reprodução F8] Configuração antiga e endereço novo produzem exatamente wrong_origin sem envio. H2: provável 75±12% prévia → quase-certo 93±6% final para o mecanismo; **provável 75±12% para explicar o relato**, pois URL efetiva pessoal não foi observada.
- [Fato F8] H3: provavelmente-não 30% prévia → quase-certo-não 7% final; “0 ms” não é teste de resposta da IA. Os bins são julgamentos, não frequências empíricas.
- [Inferência de segurança] H4: provavelmente-não 30% prévia → quase-certo-não 7% enquanto exigimos a invariante de destino autorizado; contraprova em navegador F9 eliminou a proposta de segurança irrestrita. Não relaxar guard para qualquer URL.

Implementado: passagem de personal_profile até BrowserConfig; abertura nativa no perfil escolhido com nonce; prova temporária do caminho inteiro; vínculo das abas ao browserContextId real sem persistir caminho/ID; interrupção em divergência/ausência; arena.ai como novo default; migração legada consentida preservando campos; estágios e origens sanitizadas no recibo; painel sem falsa latência do modelo. Updater, exclusão e apontamento preservados.
**Não prometido:** que toda versão pessoal do Chrome exponha todos os targets. Há agora tentativa nativa de seleção, seguida de prova, não apenas bloqueio do default. O teste de alternância de dois perfis descartáveis está na CI 40516514793; não inferir homologação pessoal.

## 6. Surpresa & implicação
- **Esperava:** H1 quase-certo 93±6%, isto é, o inventário não era seleção efetiva. Não fingir que a confirmação desse palpite foi uma surpresa.
- **Veio, mais específico:** F10 mostra que “default” no código inspecionado é **last-used**, não necessariamente o diretório Default; F11 mostra que ativação remota é global à instalação; F12 fornece identidade real por target. **Estreitamento do pilar:** não é correto concluir nem que abrir janela prova perfil, nem que é sempre impossível selecionar outro. A tentativa nativa precisa ser seguida de prova no target e filtragem das abas; verificar só uma aba nova no contexto também não basta para confiar numa aba antiga.
- **Divergência quantitativa:** prévia 2 escolhas / 1 endpoint; código tem 1 endpoint por instalação. Sem divergência ≥10× e sem número inventado de perfis suportados. Baseline: não há distribuição histórica de contas pessoais; testes sintéticos anteriores não fornecem taxa de sucesso real.
- **Implicação datada 2026-10-27:** sem o achado, abriríamos a janela selecionada e declararíamos perfil corrigido. Com ele, abrir uma prova com nonce no perfil escolhido, comparar identidade fornecida pelo Chrome e vincular cada aba por browserContextId; bloquear se não corresponde. T1 (reverter com prova de seleção CDP), T2 (limitação de transporte vs defeito só de origem), T4 (guard implementado), T6 (aplica-se a esse protocolo específico); não usar analogia decorativa.
- **Premortem/reversão:** se a CI não ler Profile Path, o verificador precisa corrigir compatibilidade; nunca aceitar o primeiro contexto. Se surgir seleção oficial documentada e teste de dois perfis pessoais no mesmo endpoint, reavaliar o limite. Verificar nesta build de 2026-10-27.
- **Confiança final:** quase-certo 93±6% sobre a necessidade da prova; 1 projeto oficial para seleção + 1 projeto primário Chromium para identidade. Nenhum teste pessoal ainda.

## 7. Comparativo e descartes
| Opção | Resultado / motivo |
|---|---|
| Renomear as opções de perfil | descartada como solução técnica: não altera conexão |
| Abrir perfil nativo e presumir seleção | descartada como prova isolada; tentativa seguida de prova nativa/ID escolhida após F10–F12 |
| Aceitar primeiro contexto / relaxar origem | descartada: pode agir em conta/site errado |
| Copiar perfil ou abrir duplicata com user_data_dir | descartada: viola privacidade/sessão pessoal e não atende usuário |
| Abertura nativa + prova com nonce + identidade por target + guard | escolhida: solicita perfil real, verifica aba e preserva migração consentida; falha fechado se indisponível |
| Ponte/extensão instalada por perfil | possível investigação futura, não implementada nem opção exigida ao usuário; precisaria distribuição gráfica segura e validação de permissões |

Contradição técnica: “escolher qualquer perfil pessoal” vs “usar apenas o perfil que o transporte consentido expõe”. A solução atual usa abertura nativa para solicitar o perfil; não inventa contextos nem expande permissões do transporte. Nenhuma analogia entre campos foi usada.

## 8. Lacunas & incertezas
- Sem URL efetiva, DOM, conta ou versão do Chrome do usuário: não declarar que a Arena redirecionou aquela execução específica.
- Prova do diretório não prova email/conta/conversa. Não coletar esses dados para fabricar homologação.
- Dois caminhos de fonte Chromium retornaram 404; gh search code não está disponível nessa versão do CLI. Recuperação por árvore/API localizou fonte real F7.
- Nenhuma distribuição de sucesso em Linux Lite pessoal. Fixture não mede compatibilidade de Arena ao vivo, frames isolados ou shadow roots.
- A rodada 3 mudou o desenho: o browserContextId real permite distinguir targets e a abertura nativa solicita o perfil. Se a versão não expõe a aba com nonce, não há seleção suportada; não oferecer outro login como fallback.
- Primeira CI 40515014165 falhou em 2 testes de prova: teste antigo não passava seleção e teste novo usava headless shell sem WebUI. Corrigidos para seleção explícita e Chromium completo. O motivo CSP foi apenas risco defensivo: trocar wait_for_function por leitura nativa evita eval, sem alegar que CSP causou a falha observada. CI final de prova/alternância ainda pendente; atualizar resultados, não hipóteses.

## 9. Fontes e rastreabilidade
F1–F7 registradas acima no momento da coleta: URL, publicação/revisão disponível, acesso e trecho literal. F8/F9 são fontes do produto no Git, datadas 2026-10-27. Snippets de busca não usados como prova. Referências metodológicas anexadas lidas separadamente para não depender do primeiro output truncado. Desvios e falhas de rota declarados, sem multiplicar F1/F2 como fontes independentes.
