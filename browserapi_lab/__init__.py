"""browserapi-lab.

Laboratorio de pesquisa e validacao para automacao de interfaces web de chats de IA.

Este pacote NAO e a API final compativel com OpenAI. Ele produz componentes medidos
(descoberta, envio, observacao de streaming, extracao, sessao e benchmark) que serao
reutilizados no aplicativo futuro.

Regra de dependencias (ADR-008): apenas a biblioteca padrao do Python e, na borda de
integracao com o navegador, o playwright. Importacoes de playwright sao sempre tardias
para que o nucleo continue testavel sem navegador instalado.
"""

__version__ = "0.1.0"

SCHEMA_VERSION = "1.0"
