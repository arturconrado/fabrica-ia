# Teste local operacional

## Preparação

Use uma chave de provedor nova e não versionada. Qualquer chave já exposta em conversa, log ou histórico deve ser revogada antes da homologação.

```bash
cp .env.example .env
# substitua os placeholders; a stack base não executa geração técnica
docker compose up --build
```

Serviços base: web `http://localhost:3000`, API `http://localhost:8000`, Keycloak `http://localhost:8081`, LiteLLM `http://localhost:4000`, MinIO `http://localhost:9000` e console MinIO `http://localhost:9001`. Temporal UI `http://localhost:8080` pertence ao perfil full. As portas locais são publicadas apenas em `127.0.0.1`; o nome `localhost` continua válido e a stack não fica exposta na LAN.

O login local usa OIDC Authorization Code + PKCE. O navegador nunca recebe uma credencial em `NEXT_PUBLIC_*` nem exige colar Bearer token. Access e refresh tokens ficam em cookies `HttpOnly`; o BFF encaminha autenticação e tenant à API. O realm local inicial contém somente `operator@local.dev`; a senha é a configurada para desenvolvimento no arquivo de realm.

`docker compose up` não executa seed. Se um volume anterior ainda contiver registros históricos, preserve-o para auditoria e use um diretório novo sem apagar dados:

```bash
ASF_DATA_ROOT=/tmp/asf-clean docker compose up --build
```

## Cinco clientes

Execute o bootstrap assistido uma vez por tenant, sempre com o `sub` OIDC exato do operador:

```bash
docker compose run --rm local-onboarding python -m app.cli.bootstrap_tenant \
  --tenant-id cliente-01 --tenant-name 'Cliente 01' \
  --subject 'OIDC-SUBJECT-DO-OPERADOR' \
  --confirm 'bootstrap assisted pilot tenant'
```

Repita para `cliente-02` até `cliente-05`. A UI deverá listar exatamente as memberships do operador. Antes de inserir conhecimento ou iniciar missão, confirme o tenant ativo no seletor superior.

## Validação automatizada

```bash
cd apps/api && .venv/bin/pytest -q
cd apps/web && npm run build
cd apps/web && npm run test:e2e
docker compose config
```

O Playwright autentica no Keycloak pelo PKCE, verifica cookies HttpOnly, refresh, todas as rotas operacionais, ausência dos mocks conhecidos, axe, teclado, reduced motion, breakpoints e uma ingestão/consulta RAG real. `ASF_TEST_COMPLETED_RUN_ID` habilita também o cockpit de uma run contratada já auditada.

Para a infraestrutura production-like completa:

```bash
make docker-doctor
make docker-full-up
make docker-full-validate
```

O perfil completo exige uma chave nova de OpenRouter/OpenAI, aliases `asf-fast`, `asf-reasoning` e `asf-code`, teto de US$ 15/run, Temporal, MinIO e Kind. O validador cria ContractFlow e ServiceDesk pelo fluxo contratado, executa os sete perfis allowlisted, confere os 17 gates e compara os fingerprints de código e proposta.

O saldo do provider deve comportar as duas missões e seus retries auditados. HTTP 402 é bloqueio de homologação, não deve ser contornado reduzindo a saída abaixo do contrato. Modelos `:free` podem ser usados apenas para diagnóstico manual: rate limit 429 ou roteamento sem garantia impede tratá-los como provider operacional.

O cliente confidencial `software-factory-validation` existe somente no perfil de teste para smoke automatizado. Ele não habilita password grant e não substitui o PKCE da interface.

## Homologação manual

1. Autenticar pelo Keycloak e confirmar que nenhum 401 aparece na interface.
2. Validar os cinco tenants no portfólio sem conteúdo RAG agregado.
3. Em cada tenant, criar/selecionar uma base, indexar um canário exclusivo e confirmar que IDs de outro tenant retornam 404/vazio.
4. Confirmar as oito ofertas, criar um engajamento por contrato, gerar/adaptar o plano com IA e aprová-lo antes da ativação.
5. Validar fila/WIP, equipe AI homologada, revisão do entregável, decisão humana, entrega final e métrica de resultado com fonte/proveniência.
6. Criar uma missão pelo fluxo contratado. Endpoints diretos de run devem responder `409` fora do perfil `test`.
7. Confirmar `software_factory_ai_native_v2`, orçamento, modelo por papel e contexto RAG explicitamente autorizado.
8. Confirmar eventos SSE, papéis/SOPs, artifacts Markdown, `FileChange`, hashes, `model_call_id`, testes, gates, HRS e topologia igual ao YAML.
9. Validar a visão restrita do aprovador e registrar decisão humana idempotente.
10. Confirmar package e entrega promovida, XP ligado ao ledger e nenhuma alteração de gate causada por gamificação.
11. Guardar IDs, logs e packages como evidência; não marcar a missão real como aprovada sem provider válido e teste efetivamente executado.

## Encerramento

```bash
docker compose down
make docker-full-down
```

Não use `down -v` em volumes que contenham evidência ou dados do cliente.
