# ADR-0011: LiteLLM Model Gateway

## Status
Accepted

## Context
Production agents need real LLM calls, routing, budgets and auditable model usage without hard-coding one provider.

## Decision
Use LiteLLM as the model gateway, with OpenRouter as the default configured upstream and OpenAI direct credentials as a supported alternative. Model calls are persisted in `model_calls`.

## Trade-offs
- Positive: provider portability and centralized model audit.
- Negative: one more runtime service and real LLM costs in local validation.
- Mitigation: model budgets, tenant audit and explicit release gates make cost and usage visible.
