# Metas de produto — respostas comprovadas, não promessas

As seis perguntas do usuário passam a ser critérios de aceitação. Este marco
amplia o laboratório com configuração e teste assistido de chats. Não antecipa
FastAPI, fila, SSE ou API OpenAI-compatible.

| Meta | Critério para responder SIM | Evidência necessária |
|---|---|---|
| M1 — Meu navegador | Escolher Chrome/Edge instalado, Chromium gerenciado ou binário Chromium explícito, sempre com perfil dedicado e janela visível | Integração por produto; indicar claramente produtos ainda não homologados |
| M2 — Meu chat | Selecionar Gemini/LMArena ou URL própria e salvar configuração independente por chat | Teste multi-chat, isolamento de perfis e teste assistido do site real |
| M3 — Confirma que funciona | Um envio autorizado produz mensagem nova e resposta nova válida para a tentativa; recibo com data, versão e latências | Teste positivo, timeout, login, CAPTCHA, rate limit, resposta antiga e ambiguidade |
| M4 — Consigo resolver | Erro identifica etapa e apresenta ação concreta; assistente de reparo permite apontar controles na página sem console/JavaScript/CSS manual | Fluxo de seletores quebrados → reparo → novo teste; sem reenvio automático |
| M5 — Velocidade próxima de API | Medir TTFT, total e atraso de captura; definir orçamento do overhead, separando tempo do site/modelo; comparar com API real equivalente somente se houver acesso autorizado | P95 de captura no fixture e no site real; sem afirmar equivalência a API por medição local |
| M6 — Fácil e simples | Assistente de configuração, seleção manual de modelo, comando de checagem, status e ajuda; sem editar arquivos | Testes da CLI, pacote instalado e reparo; avaliação humana ainda necessária |

## Regras de aprovação

- `implementado`, `testado local/CI` e `homologado em site real` são estados diferentes.
- Um recibo de compatibilidade é válido para aquela execução/configuração; não é contrato permanente.
- Somente o usuário faz login, CAPTCHA e seleção do modelo.
- Mensagem de teste real requer confirmação explícita; nenhum retry de envio ambíguo.
- Nunca abrir o perfil pessoal padrão ou extrair sua sessão.
- Metas dependentes de autenticação, rede ou participação humana permanecem abertas
  até existir a evidência correspondente. Não marcar todas como SIM artificialmente.

Acompanhamento atualizado ao fim deste marco em `docs/PRODUCT_VALIDATION.md`.
