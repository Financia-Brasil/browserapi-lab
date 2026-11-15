# Farol Beta Android

Build de teste do IAssistente Intergeracional, IFPA Bragança. Kotlin, WebView e TTS pt-BR. Guia determinístico local, sem backend de IA.

A branch `codex/farol-android-beta-20261115` usa GitHub Actions para compilar; alterações em `android/` geram APK debug, SHA256, testes e lint. O build da 0.1.1 passou em https://github.com/Financia-Brasil/browserapi-lab/actions/runs/43734503508.

Validação em aparelho físico: 25 verificações funcionais, 23 estendidas e 100 toques nos controles do guia. CI: 22 testes JavaScript e 13 testes Kotlin aprovados. `tests/device_test.py` inicia a suíte; depois execute `tests/extended_test.py`. Ambos recebem `--serial` e `--out`. `--reset` na suíte inicial apaga apenas o beta. `tests/privacy_probe.py` exige uma captura real não vazia; `tests/stress_test.py` parte da primeira tela do treino offline.

Versão 0.1.1-beta: mantém o erro e o endereço solicitado após falha de navegação. Uma nova tentativa ocorre somente quando pedida. Treino e dados de teste são fictícios. Backend de IA, Sessão Viva e o MVP completo continuam pendentes.
