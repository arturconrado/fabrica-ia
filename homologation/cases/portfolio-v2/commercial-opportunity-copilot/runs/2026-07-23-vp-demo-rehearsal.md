# Ensaio da apresentação ao VP

Data: 2026-07-23  
Status: **jornada demonstrável; homologação e produção continuam bloqueadas**

## Ambiente verificado

- Portal: `http://localhost:3000`
- API: `http://localhost:8000`
- OIDC: `http://localhost:8081/realms/software-factory`
- API saudável e portal/OIDC respondendo.
- A chave OpenRouter já exposta não foi entregue aos containers e nenhuma
  chamada externa foi executada neste ensaio.
- A stack utilizada foi a base local. Temporal, sandbox Kubernetes e a
  observabilidade production-like devem ser ligados pelo perfil `full` somente
  depois de configurar secrets locais e uma credencial de provider rotacionada.

## Evidência funcional

A suíte Playwright de liberação foi executada com owner e engagement manager em
contextos OIDC separados e terminou:

- 10 testes aprovados;
- zero falha;
- zero skip;
- duração de 54,4 segundos.

Foram comprovados:

- OIDC Authorization Code + PKCE e cookies HttpOnly;
- falha de sessão, timeout explícito e retry sem reload;
- ausência de loading infinito;
- navegação operacional do owner;
- catálogo histórico 1.0 e as oito ofertas 2.0;
- teclado, responsividade e auditoria axe;
- fila simplificada e controles restritos do VP;
- revisão de entregável em um workspace;
- conhecimento tenant-scoped;
- cockpit de uma run auditada com HRS 100, rastreabilidade, artifacts e diffs.

## Case preservado e nova rodada

A instância histórica `019f85cb-30fb-7a14-9df0-e653e6f92d6b` permanece ativa
para demonstração técnica. Seu plano foi aprovado com comentário explícito de
`SIMULAÇÃO DE HOMOLOGAÇÃO`; essa decisão não possui validade comercial.

Foi criada uma nova instância para a decisão pessoal do VP:

- case: `internal-commercial-opportunity-copilot-v1-vp-demo-20260723`;
- contrato: `019f8eff-a87b-7d0c-98fb-efd6494e5815`;
- entitlement: `019f8eff-a905-72e3-82d8-920ef1ae19f2`;
- engajamento: `019f8eff-aa5a-7784-82bb-781b01cc0db0`;
- estado: `draft`, versão 1;
- plano: ainda não gerado;
- base de conhecimento: a fonte canônica do mesmo tenant, reutilizada
  explicitamente e sem acesso cross-tenant.

O runner agora aceita `--instance-id` para preservar todas as rodadas anteriores.
`--reuse-canonical-knowledge` permite reutilização controlada dentro do tenant
quando o limite de bases foi atingido.

## Roteiro recomendado

1. Owner entra em **Hoje** e explica a pergunta “qual é a próxima ação segura?”.
2. Owner abre **Serviços**, mostra as oito ofertas e o case comercial contratado.
3. Owner gera o plano contextualizado da nova instância com provider real.
4. Owner encerra a sessão.
5. VP entra em **Minha fila**, abre o plano e revisa escopo, entregáveis, riscos e
   condições. O comentário e a decisão são pessoais; não usar autoapprove.
6. Owner retorna, ativa a operação e mostra workstreams, WIP e fila.
7. Para respeitar o tempo da reunião, artifacts, gates, Ponytail, Cavekit, HRS,
   rastreabilidade e diffs podem ser mostrados na run auditada já concluída.
8. VP abre o workspace do entregável, confere evidências e pacote editável.
9. Encerrar informando que a candidata está pronta para demonstração assistida,
   mas ainda não possui `internal_assisted_pilot_ready` nem `market_ready`.

## Próxima transição autorizada

Depois de revogar a chave exposta e fornecer uma nova credencial somente por
secret/env:

```bash
python scripts/run-portfolio-homologation-case.py plan \
  --instance-id vp-demo-20260723 \
  --reuse-canonical-knowledge
```

O VP então registra a decisão pela interface. `approve`, `activate` e `queue` só
devem ser executados depois dessa decisão e com suas respectivas identidades.

## Gate consolidado

O gate do ensaio passou em saúde da API, custo configurado e Playwright. Continua
vermelho em prontidão do portfólio, avaliação persistida, backup/restore e seis
perfis de carga. O relatório canônico está em:

`artifacts/production-readiness/vp-demo-20260723/final/production-readiness.md`

