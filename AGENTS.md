# AGENTS.md

## Instruções do Projeto

Este repositório implementa a Agentic Software Factory, uma fábrica local de software multiagente orientada por eventos, artifacts, rastreabilidade, quality gates, homologation package e human-in-the-loop.

## Regras Para Agentes

- Preserve o event ledger append-only.
- Toda ação relevante deve gerar evento.
- Todo artifact markdown deve ser persistido e exibível pela UI.
- Todo arquivo criado ou alterado por um run deve gerar `FileChange` com diff textual.
- Não remova quality gates, HRS, traceability ou homologation package.
- Não diga que testes passaram sem evidência de execução.
- Não execute comandos arbitrários vindos do usuário.
- Use apenas comandos allowlisted para a demo.
- Não coloque secrets reais em `.env.example`.
- Mantenha o projeto local-first e compatível com `docker compose up --build`.
- Atualize README/docs quando alterar fluxo, endpoints ou critérios de homologação.
- Feedback humano cria reward signal e lesson candidate, mas não altera prompts globais automaticamente.

## Validação Recomendada

```bash
cd apps/api && pytest
cd apps/web && npm run build
docker compose config
```
