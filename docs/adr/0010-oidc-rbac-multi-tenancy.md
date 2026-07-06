# ADR-0010: OIDC, RBAC And Tenant Isolation

## Status
Accepted

## Context
The factory must isolate projects, runs, artifacts, approvals, feedback, learning and batch data between organizations.

## Decision
Use OIDC/JWKS for authentication, role-based authorization for mutating operations and `tenant_id` on operational resources. Docker Compose imports a Keycloak realm and does not use a development bearer-token bypass.

## Trade-offs
- Positive: compatible with Keycloak, Auth0, Clerk, Entra and Cognito.
- Negative: every route must maintain tenant filtering discipline.
- Mitigation: route tests cover isolation and operational docs block release on tenant leaks.
