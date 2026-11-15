# Farol Beta Android

Prova de conceito nativa em Kotlin, com WebView e voz Android. O APK é compilado **somente na nuvem, pelo GitHub Actions da conta Financia-Brasil**. O computador local edita os arquivos, baixa o APK e executa os testes via ADB.

Disponível: consentimento com recusa, treino offline, navegador HTTPS, guia local com destaque, TTS pt-BR, pausa, reformulação e fluxos locais. A versão 0.2 adiciona assistente Android global por gesto/botão, painel sobre outros aplicativos e consulta à OpenAI por gateway autenticado. A ativação e os resultados de cada teste ficam registrados em `../evidencia/ai-overlay-2026-11-15/`.

Limites: esta versão não implementa o MVP inteiro da especificação. Ainda não há Sessão Viva contínua, GeckoView, cache de planos completos, aprendizagem adaptativa, abas ou acesso a iframes de outros domínios. O contexto de outro aplicativo é fornecido pelo Android no momento da chamada do assistente; para atualizar após uma ação, feche e chame o Farol novamente. Os fluxos salvos de sites reais guardam a origem do portal; o guia é calculado novamente. O treino retoma a etapa, sem guardar o preenchimento. WebView é a alternativa de POC permitida pela especificação, não a engine prevista para release.

## Compilação remota

Build validado: [GitHub Actions — Farol Beta 0.1.1](https://github.com/Financia-Brasil/browserapi-lab/actions/runs/43734503508). Código na branch independente `codex/farol-android-beta-20261115` de `Financia-Brasil/browserapi-lab`.

Toolchain: Java 17, Gradle 8.11.1, SDK 35, AGP 8.9.2 e Kotlin 2.1.20. O workflow `.github/workflows/android-beta.yml` executa testes Python do gateway, 22 testes JavaScript, 21 testes JUnit, lint e assembleDebug, e publica o Farol e o aplicativo separado de exercício com SHA256 e relatórios. A chave do provedor fica exclusivamente no gateway; o APK recebe apenas um token de pareamento revogável.

O Codespace `Financia-Brasil / fluffy-guide-77w5wv9xj994f9p6`, em `/workspaces/farol-beta`, gerou a versão 0.1.0. Em 15/11 retornou HTTP 402 por faturamento; o build da versão 0.1.1 passou a usar Actions. Os scripts `scripts/setup-codespace.sh` e `scripts/build-codespace.sh` preservam a alternativa de Codespace e recusam execução fora desse ambiente.

A versão 0.1.1 corrige o recarregamento automático da página anterior após falha de navegação. A mensagem e o endereço com falha permanecem visíveis. “Explicar tela” repete apenas o endereço solicitado.

## Instalar e testar

Pacote de teste: `com.ifpa.iassistente.beta`. Nome no aparelho: **Farol Beta**. Usa assinatura debug estável, guardada no GitHub Actions Secret `FAROL_TEST_KEYSTORE_BASE64`. A ausência desse secret interrompe o build. O cache anterior não persistiu a chave e não serve para garantir atualizações. A migração de 0.1.0 para 0.1.1 exigiu reinstalar apenas o Farol Beta porque as assinaturas dos dois ambientes são diferentes.

```bash
adb devices -l
adb -s SERIAL install -r artifacts/Farol-0.1.1-beta.apk
python3 tests/device_test.py --reset --serial SERIAL --out ../evidencia/android-2026-11-15
python3 tests/extended_test.py --serial SERIAL --out ../evidencia/android-2026-11-15
```

O teste precisa de Python com `websocket-client`. Abre o app de teste, recusa e aceita o consentimento, executa treino, erro, timeout, pausa, conclusão, persistência e entrada pelo teclado. Os dados são fictícios. Não limpa outros aplicativos. A opção `--reset` apaga somente os dados do Farol Beta para preparar a suíte inicial. A suíte estendida vem em seguida e cobre HTTPS, esquemas bloqueados, falha e repetição de rede, rotação, largura de 375px, fonte ampliada e revogação do consentimento. As configurações de fonte, rotação e tamanho são restauradas ao final. `tests/stress_test.py` executa 100 toques nos controles da primeira tela do treino offline. `tests/privacy_probe.py` refaz isoladamente uma captura real e não vazia, sem apagar o beta. Os resultados desta versão estão em `../evidencia/android-2026-11-15/relatorio-validacao.md`.

DevTools está habilitado somente no build debug para testes via ADB. Não há ponte JavaScript nativa exposta às páginas. O app não clica nem preenche: as ações automatizadas pertencem exclusivamente ao teste externo.

## Privacidade e fontes

A captura contém origem, papel, rótulo saneado e indicação de preenchimento. Ela não contém valores de inputs, textarea ou select, nem caminho, query ou fragmento da URL. A captura do navegador de treino permanece local. No assistente global, somente uma pergunta voluntária e rótulos permitidos de controles são enviados após consentimento específico. Textos livres do outro aplicativo são descartados. A aplicação não envia screenshots à IA. Sites reais recebem o que o usuário enviar diretamente a eles.

Backups e transferência de dados são bloqueados. A permissão de microfone é opcional e o microfone só abre após tocar em Falar; o reconhecedor Android pode usar a nuvem. O painel usa VoiceInteractionSession do assistente escolhido pelo usuário. Não requer serviço de acessibilidade global nem SYSTEM_ALERT_WINDOW. Arquivos e conteúdo Android não são acessíveis pelo WebView; conexões inseguras e esquemas de apps são bloqueados.

Fontes da verdade: `../docs/especificacao-funcional-iassistente.md`, `../docs/decisoes-farol.md`, `../docs/handoff-implementacao-farol.md`. Evidências ficam em `../evidencia/android-2026-11-15/`, fora da pasta publicada no Pages.

Atkinson Hyperlegible: Google Fonts / Braille Institute, licença OFL incluída em `android/app/src/main/assets/fonts/OFL.txt`.

## Assistente global e IA — teste 0.2

Em “Preparar assistente”, escolha Farol como assistente do Android. Depois, mantenha Início pressionado ou use o gesto de assistente configurado no aparelho. O painel aparece sobre o aplicativo atual sem abrir a tela principal do Farol. Não há palavra de ativação nem escuta permanente nesta versão. O app informa quando usa guia local ou resposta da OpenAI e não clica ou digita pelo usuário.

O ambiente de campo inicial usa USB e um gateway Python leve neste computador. A inferência acontece na OpenAI. O celular depende do gateway e do `adb reverse`; não é uma implantação independente com servidor público. O navegador continua exigindo HTTPS; somente o build debug aceita HTTP em loopback para este teste. Produção exige gateway HTTPS autenticado.

Crie `.secrets/openai.env` local com as variáveis de `backend/.env.example`, permissão 600 e chave exclusiva com Responses Write. Não envie o arquivo para GitHub nem empacote no APK. Inicie e pareie:

```bash
python3 backend/farol_backend.py --env .secrets/openai.env
python3 backend/pair_device.py --serial SERIAL --env .secrets/openai.env
```

O gateway limita consultas a 5 por minuto e 50 por dia por processo, sem repetição automática. Requisições têm até 60 controles e respostas só podem destacar IDs recebidos. O teste usa `gpt-6-luna`, Responses com saída estruturada e `store:false`. O backend não registra perguntas, capturas ou credenciais. Evidências saneadas em arquivos privados do beta são somente para depuração e são apagadas em “Apagar dados”.

Os créditos de API precisam estar disponíveis na organização da chave. Entrar no ChatGPT não fornece uma chave para o app. A conta inspecionada nesta rodada mostrou Plus e saldo de API US$0,00; uma consulta real foi aceita, sem compra ou recarga. Isso não garante disponibilidade contínua.
