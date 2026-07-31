# Third-party optimization pattern notices

No third-party source code, hook, binary or automatic updater from the projects below is bundled. The production candidate contains original internal, version-pinned protocol adapters based on the reviewed public behavior. Those adapters are independently governed by factory schemas, tenant isolation, budgets, ledger and quality gates.

## Ponytail

- Project: https://github.com/DietrichGebert/ponytail
- Reviewed version: `4.8.4`
- Reviewed revision: `16f29800fd2681bdf24f3eb4ccffe38be3baec6b`
- License at review time: MIT
- Production adapter: `app.plugins.ponytail`, pinned to the revision above; activate/instructions/review/audit/debt/gain/help are mapped to typed, auditable factory operations.
- Factory constraint: minimalism never overrides requirements, tenant isolation, security, accessibility, deterministic gates, HRS, tests or human approval.
- Codex host: the marketplace snapshot is pinned to the reviewed revision, `ponytail@ponytail` is enabled, the local default is `full`, automatic updates remain disabled and hook trust is never bypassed.

## Cavekit

- Project: https://github.com/JuliusBrussee/cavekit
- Reviewed revision: `c322f0bb6db82163041930467f3ce32754d42827`
- License at review time: MIT
- Production adapter: `app.plugins.cavekit`, pinned to the revision above; grill/spec/research/review/build/check/backprop/deepen/caveman are curated per workflow role.
- Factory constraint: Temporal remains the durable orchestrator; tenant-private context, ledger provenance, sandbox execution and workflow controls are not replaced.
