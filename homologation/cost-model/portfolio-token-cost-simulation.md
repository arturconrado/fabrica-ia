# Simulação de tokens e custos do portfólio 2.1

> Simulação determinística; nenhuma chamada de IA é executada. Valores em USD e sem impostos, câmbio ou ferramentas cobradas à parte.

## Preços utilizados

Snapshot: `2026-07-31T14:09:54Z` · fonte: `https://openrouter.ai/api/v1/models`.

| Papel | Modelo | Entrada / 1M | Saída / 1M | Cache read / 1M |
|---|---|---:|---:|---:|
| default | `openai/gpt-5.4-mini` | US$ 0.7500 | US$ 4.5000 | US$ 0.0750 |
| fast | `google/gemini-3.1-flash-lite` | US$ 0.2500 | US$ 1.5000 | US$ 0.0250 |
| reasoning | `anthropic/claude-sonnet-4.6` | US$ 3.0000 | US$ 15.0000 | US$ 0.3000 |
| code | `anthropic/claude-sonnet-4.6` | US$ 3.0000 | US$ 15.0000 | US$ 0.3000 |

## Totais por oferta — execução ingênua de comparação

Cada valor inclui um plano de engajamento. AI Office representa um ciclo; a homologação completa acrescenta o segundo ciclo sem repetir o plano.

| Oferta | Enxuto | Esperado | Conservador | Tokens esperados (in/out) | Chamadas equivalentes* |
|---|---:|---:|---:|---:|---:|
| AI Value Discovery | US$ 0.5651 | US$ 1.0519 | US$ 1.7568 | 91,150 / 51,900 | 11.00 |
| AI Governance & Risk Framework | US$ 0.7478 | US$ 1.3998 | US$ 2.3420 | 117,110 / 69,900 | 14.00 |
| AI Enterprise Launchpad | US$ 0.7565 | US$ 1.4159 | US$ 2.3621 | 117,460 / 70,900 | 14.00 |
| AI Workforce Productivity Accelerator | US$ 0.7453 | US$ 1.3934 | US$ 2.3227 | 117,460 / 69,400 | 14.00 |
| AI Engineering Productivity Accelerator | US$ 2.9955 | US$ 5.3091 | US$ 14.1241 | 816,496 / 254,768 | 125.48 |
| AI Use Case Pilot | US$ 7.5671 | US$ 13.2754 | US$ 37.9447 | 2,223,568 / 632,704 | 349.44 |
| AI Office as a Service | US$ 0.1288 | US$ 0.2250 | US$ 0.3250 | 99,800 / 59,600 | 12.00 |
| AI Adoption Kit & Governance Cockpit | US$ 0.7034 | US$ 1.3149 | US$ 2.1880 | 108,800 / 65,900 | 13.00 |

| Escopo | Enxuto | Esperado | Conservador |
|---|---:|---:|---:|
| Oito ofertas, um ciclo cada | US$ 14.2095 | US$ 25.3854 | US$ 63.3655 |
| Homologação com dois ciclos do AI Office | US$ 14.2631 | US$ 25.4878 | US$ 63.5423 |

\* Chamadas equivalentes incluem a reserva probabilística de retries; por isso podem ser fracionárias.

## Efeito da topologia eficiente

A topologia candidata 2.1 consolida os seis entregáveis técnicos do Pilot em uma execução e materializa uma execução compartilhada no Engineering.

| Cenário | Runtime atual | Compartilhado recomendado | Economia |
|---|---:|---:|---:|
| lean | US$ 14.2631 | US$ 7.0270 | US$ 7.2360 (50.7%) |
| expected | US$ 25.4878 | US$ 12.8196 | US$ 12.6682 (49.7%) |
| conservative | US$ 63.5423 | US$ 26.5730 | US$ 36.9693 (58.2%) |

## Custo esperado por entregável — comparação ingênua

`human` e `integration` não chamam modelo. Em `technical_run`, o valor é o custo integral da fábrica hoje disparada por aquele entregável.

### AI Value Discovery

Plano compartilhado do engajamento: US$ 0.1177.

| Entregável | Modo | Modelo | Tokens in/out | Custo esperado | Alocação |
|---|---|---|---:|---:|---|
| diagnóstico de maturidade em IA | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| mapa dos processos analisados | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| inventário de oportunidades | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| fichas detalhadas dos casos de uso | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| matriz de impacto risco e complexidade | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| ranking de oportunidades | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| business cases preliminares | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| mapa de dependências | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| arquitetura de referência | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| roadmap corporativo de IA | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| apresentação executiva para decisão | human | none | 0 / 0 | US$ 0.0000 | human_or_integration_no_model_call |

### AI Governance & Risk Framework

Plano compartilhado do engajamento: US$ 0.1278.

| Entregável | Modo | Modelo | Tokens in/out | Custo esperado | Alocação |
|---|---|---|---:|---:|---|
| inventário corporativo de IA | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| política corporativa de IA | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| catálogo de riscos | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| matriz de classificação | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| RACI de governança | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| fluxo de submissão e aprovação | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| checklist de avaliação de casos de uso | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| checklist de avaliação de fornecedores | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| modelo de AI System Card | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| modelo de registro de decisões | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| processo de gestão de incidentes | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| modelo de auditoria | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| painel inicial de governança | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |

### AI Enterprise Launchpad

Plano compartilhado do engajamento: US$ 0.1333.

| Entregável | Modo | Modelo | Tokens in/out | Custo esperado | Alocação |
|---|---|---|---:|---:|---|
| modelo operacional de IA | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| estrutura de governança inicial | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| catálogo de casos de uso | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| ambientes configurados | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| biblioteca de prompts | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| assistentes e workflows | agent | reasoning | 8,540 / 6,500 | US$ 0.1231 | direct |
| playbooks por área | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| guias de utilização | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| materiais de treinamento | human | none | 0 / 0 | US$ 0.0000 | human_or_integration_no_model_call |
| modelo de champions | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| dashboard executivo | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| dashboard de adoção | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| backlog de evolução | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| plano de expansão | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |

### AI Workforce Productivity Accelerator

Plano compartilhado do engajamento: US$ 0.1333.

| Entregável | Modo | Modelo | Tokens in/out | Custo esperado | Alocação |
|---|---|---|---:|---:|---|
| mapa de atividades por função | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| catálogo de casos de uso | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| biblioteca de prompts | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| assistentes por função | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| templates | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| workflows | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| playbooks | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| guias rápidos | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| materiais de capacitação | human | none | 0 / 0 | US$ 0.0000 | human_or_integration_no_model_call |
| repositório de boas práticas | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| plano de comunicação | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| modelo de champions | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| dashboard de uso | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| backlog de melhorias | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |

### AI Engineering Productivity Accelerator

Plano compartilhado do engajamento: US$ 0.1281.

| Entregável | Modo | Modelo | Tokens in/out | Custo esperado | Alocação |
|---|---|---|---:|---:|---|
| assessment do processo de engenharia | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| baseline dos indicadores | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| catálogo de casos de uso | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| política de uso de IA na engenharia | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| padrões de segurança | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| playbooks por função | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| prompts e agentes especializados | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| templates técnicos | technical_run | mixed | 362,443 / 100,334 | US$ 2.1114 | one_full_factory_run |
| quality gates | technical_run | mixed | 362,443 / 100,334 | US$ 2.1114 | one_full_factory_run |
| ambientes configurados | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| materiais de capacitação | human | none | 0 / 0 | US$ 0.0000 | human_or_integration_no_model_call |
| dashboard de engenharia | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| backlog de expansão | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |

### AI Use Case Pilot

Plano compartilhado do engajamento: US$ 0.1281.

| Entregável | Modo | Modelo | Tokens in/out | Custo esperado | Alocação |
|---|---|---|---:|---:|---|
| documento do problema | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| desenho funcional | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| arquitetura da solução | technical_run | mixed | 362,443 / 100,334 | US$ 2.1114 | one_full_factory_run |
| piloto funcional | technical_run | mixed | 362,443 / 100,334 | US$ 2.1114 | one_full_factory_run |
| dataset de avaliação | technical_run | mixed | 362,443 / 100,334 | US$ 2.1114 | one_full_factory_run |
| integrações previstas | integration | none | 0 / 0 | US$ 0.0000 | human_or_integration_no_model_call |
| relatório de testes | technical_run | mixed | 362,443 / 100,334 | US$ 2.1114 | one_full_factory_run |
| relatório de segurança | technical_run | mixed | 362,443 / 100,334 | US$ 2.1114 | one_full_factory_run |
| relatório de qualidade | technical_run | mixed | 362,443 / 100,334 | US$ 2.1114 | one_full_factory_run |
| demonstração executiva | human | none | 0 / 0 | US$ 0.0000 | human_or_integration_no_model_call |
| backlog produtivo | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| mapa de riscos | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| recomendação de evolução | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |

### AI Office as a Service

Plano compartilhado do engajamento: US$ 0.1226.

| Entregável | Modo | Modelo | Tokens in/out | Custo esperado | Alocação |
|---|---|---|---:|---:|---|
| backlog corporativo de IA | agent | fast | 8,540 / 4,200 | US$ 0.0084 | direct |
| portfólio priorizado | agent | fast | 8,540 / 5,000 | US$ 0.0096 | direct |
| fichas de avaliação | agent | fast | 8,540 / 5,000 | US$ 0.0096 | direct |
| dashboard executivo | agent | fast | 8,540 / 4,200 | US$ 0.0084 | direct |
| relatório de adoção | agent | fast | 8,540 / 5,000 | US$ 0.0096 | direct |
| relatório de riscos | agent | fast | 8,540 / 5,000 | US$ 0.0096 | direct |
| atas de governança | agent | fast | 8,540 / 5,000 | US$ 0.0096 | direct |
| registro de decisões | agent | fast | 8,540 / 5,000 | US$ 0.0096 | direct |
| plano de ações | agent | fast | 8,540 / 5,000 | US$ 0.0096 | direct |
| atualização do roadmap | agent | fast | 8,540 / 4,200 | US$ 0.0084 | direct |
| materiais de capacitação | human | none | 0 / 0 | US$ 0.0000 | human_or_integration_no_model_call |
| recomendações executivas | agent | fast | 8,540 / 5,000 | US$ 0.0096 | direct |

### AI Adoption Kit & Governance Cockpit

Plano compartilhado do engajamento: US$ 0.1330.

| Entregável | Modo | Modelo | Tokens in/out | Custo esperado | Alocação |
|---|---|---|---:|---:|---|
| repositório corporativo configurado | agent | reasoning | 8,540 / 6,500 | US$ 0.1231 | direct |
| estrutura de navegação | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| perfis e acessos | integration | none | 0 / 0 | US$ 0.0000 | human_or_integration_no_model_call |
| políticas | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| templates | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| matriz de riscos | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| catálogo de casos de uso | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| biblioteca de prompts | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| calculadora de ROI | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| checklists | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| dashboards | agent | reasoning | 8,540 / 4,200 | US$ 0.0886 | direct |
| documentação de administração | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| guia de atualização | agent | reasoning | 8,540 / 5,000 | US$ 0.1006 | direct |
| treinamento dos administradores | human | none | 0 / 0 | US$ 0.0000 | human_or_integration_no_model_call |

## Premissas e limites

- O plano é uma chamada `reasoning` por engajamento, com teto de 8 mil tokens de saída.
- Cada entregável `agent` é uma chamada própria; DOCX, XLSX e ZIP usam estimativas diferentes de conteúdo fonte.
- A execução técnica usa os 18 papéis e os budgets compilados da política 2.14.0, incluindo unidades segmentadas, reserva de retry e cache somente onde reutilizável.
- Os tetos de US$ 2, US$ 3 e US$ 15 são proteções de gasto, não previsões de consumo.
- A simulação não inclui entrevistas humanas, armazenamento, CPU, observabilidade, web search, impostos ou câmbio.
- Preços de modelos mudam. Atualize o snapshot e regenere o relatório antes de formar preço comercial.

## Gate de orçamento da homologação

- Esperado: US$ 12.8196 / limite US$ 15.0000.
- Conservador: US$ 26.5730 / limite US$ 30.0000.
- Hard stop global: US$ 50.0000.
- Resultado: **PASSOU**.
