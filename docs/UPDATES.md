# Atualização automática — BrowserAPI 0.3.0

## Contrato entregue

Instale uma vez o `.deb` com supervisor. Depois disso, ao abrir BrowserAPI, ele
consulta a release estável mais recente de **Financia-Brasil/browserapi-lab** no
GitHub após 5 segundos e novamente a cada 6 horas enquanto estiver aberto.
Não instala um serviço permanente quando o aplicativo está fechado.

Atualizações compatíveis são baixadas, verificadas e aplicadas automaticamente
quando não há configuração, pergunta, envio ou outra tarefa em andamento. Não
há reenvio de mensagens. O programa troca o processo Python, não faz reload de
módulos em uso. A aba mantém endereço/token e recarrega a interface para a nova
versão. Não é preciso reinstalar `.deb`, reiniciar o computador ou clicar em um
botão para cada atualização compatível.

O checkbox **Atualização automática** fica visível e ligado por padrão nesta
versão, conforme pedido do usuário. Desligar persiste a preferência e impede
inclusive a aplicação de download pendente na próxima abertura. O programa não
pede senha de administrador para autoatualizar código em dados do próprio usuário.
O diretório do sistema instalado pelo `.deb` não é modificado pelo atualizador.

**Primeira migração:** versões anteriores não têm esse supervisor. É necessária
uma instalação inicial de 0.3.0 e encerrar o runtime antigo (reiniciar pelo menu
é o caminho gráfico simples). Isso não se repete nas atualizações ABI 1 seguintes.
Executar diretamente `python -m browserapi_lab.gui`/o entrypoint antigo não passa
pelo supervisor e não ativa autoatualização; a GUI informa que não é gerenciada.

## Confiança e integridade

- Editor fixo, não configurável por formulário/manifesto: repositório acima.
- HTTPS, sem redirecionamentos, sem token GitHub, cookies ou conta do usuário.
- Release estável → tag SemVer → commit imutável → manifesto e bundle por GitHub
  Contents API no mesmo commit. Não baixar `main` flutuante nem executar URL de
  manifesto. Tags anotadas são resolvidas com limite de profundidade.
- SHA256 + tamanho, ABI e dependências fixas; arquivo limitado em bytes, quantidade
  e tamanho descompactado. Sem symlinks, traversal, duplicatas ou caminhos livres.
- Compilação sintática de Python, identidade de versão, assets obrigatórios e
  frontend/backend coerentes antes de gravar ponteiro pendente.
- Diretórios por versão; código ativo nunca sobrescrito. Ponteiro JSON atômico,
  um supervisor por usuário, e a tarefa atual termina antes de trocar processo.

**SHA256 não é assinatura independente.** A confiança é no editor e na conta/
infraestrutura GitHub sob HTTPS: comprometimento desse repositório pode publicar
código executável. Isso é declarado na GUI; desligue a opção se não quiser
confiar em futuras versões desse editor. Não há criptografia caseira ou promessa
de resistência a um editor comprometido. Arquivos locais do mesmo usuário não
constituem fronteira de segurança contra esse próprio usuário.

## Recuperação e limites

Rede indisponível/rate limit/manifesto inválido preservam versão atual e exibem
aviso genérico sem detalhes privados; tentativa seguinte no próximo ciclo ou ao
reabrir. Não há download no thread HTTP nem espera de rede bloqueando tarefa.
Uma versão cujo processo falha no início volta à anterior/base e entra na lista
de rejeitadas (até 20). No período inicial de 30 segundos o supervisor verifica
sinal de inicialização do servidor. O aviso de restauração é mostrado na GUI.
Isso não prova ausência de defeitos posteriores ao início; testes de release
continuam obrigatórios. Não se promete sobreviver a toda falha de hardware/disco.

ABI 1 cobre código Python e assets stdlib + Playwright **1.64.1**, Python **3.11+**.
Trocar bibliotecas Python/nativas, supervisor ou dependências do SO exige novo
instalador e decisão explícita. Não atualizar sistema, Chrome ou credenciais.
Nenhum app pode garantir upgrades arbitrários do SO sem esse limite de confiança.
Diretórios antigos são preservados para rollback; não há limpeza automática de
versões neste marco. Não se fazem mensagens sintéticas para testar atualização.

## Publicação automatizada

O job `release` do workflow `lab` depende dos testes unitários e de navegador e
só executa em push de **main** aprovado. Não publica código de PR nem release em
falha. Incremento patch automático sobre a última release; para minor/major,
o desenvolvedor aumenta a base em `version.py`. Tag `vX.Y.Z`, `.deb`, runtime ZIP,
manifesto e SHA256SUMS são publicados com `gh`. Reexecutar o mesmo source SHA
não gera outra versão.

O job constrói um commit de release pela API, derivado do commit testado, com
versão materializada nos assets/runtime e downloads. A tag aponta para esse
commit; não altera main nem dispara loop de commits. Bundle passa pelo mesmo
validador usado no cliente. Não há credencial de assinatura armazenada no repo.
O job precisa estar integrado em main para publicar futuros pushes de main;
apenas existir nesta branch não instala o workflow em outra branch.

Não é atualização de regras durante um envio: toda atualização de código troca
o worker/servidor em ponto ocioso, mantendo supervisor e aba. Regras independentes,
inventário de perfis, otimizações, API e RAG continuam módulos distintos.
