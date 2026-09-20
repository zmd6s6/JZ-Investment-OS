# PRODUCT-01 — Productization Contract & Onboarding Skeleton

- State: `PLANNED`
- Starts after: PR-08 is reviewed, merged, and repository status is synchronized
- Governing spec: `INVESTMENT_OS_MASTER_SPEC.md`
- Product plan: `docs/product/PRODUCTIZATION_ROADMAP.md`
- Beta gate: `docs/product/BETA_ACCEPTANCE.md`
- Safety baseline: `auto_trade=false`; no live brokerage order submission

## Objective

Create the first productization slice that turns the repository from a developer-facing system into a guided personal application.

This stage does **not** authorize real provider credentials, real investment-policy values, brokerage execution, or automatic trading.

## Deliverables

- [ ] Explicit onboarding state and first-run detection
- [ ] Setup Wizard shell with ordered steps:
  - market/asset scope
  - model provider placeholder
  - data provider placeholder
  - Portfolio onboarding placeholder
  - Watchlist placeholder
  - Investment Policy review
  - Initial Analysis readiness
- [ ] Settings top-level navigation and product-status page
- [ ] Product capability matrix: AVAILABLE / CONFIGURATION_REQUIRED / NOT_IMPLEMENTED
- [ ] UI must stop presenting hard-coded synthetic cards as if they were operational portfolio state
- [ ] Existing PR-08 read-only pages remain available but are clearly separated from product onboarding
- [ ] README updated with actual current capabilities and exact path to first-run UI
- [ ] `docs/PROJECT_STATUS.md` updated to show productization program
- [ ] E2E browser test for fresh install → onboarding start → no secret/provider/portfolio configured
- [ ] No weakening of Evidence, Risk Veto, approval, sizing, or immutable-history invariants

## Acceptance criteria

1. A fresh installation opens a deterministic Setup Wizard rather than an unexplained synthetic dashboard.
2. The UI clearly states which required capabilities are not configured and which are not yet implemented.
3. No user is instructed to edit database rows, construct raw JSON, or run internal developer scripts for onboarding.
4. No secret collection is implemented until PRODUCT-02 introduces the reviewed SecretStore path.
5. No real Portfolio data is required or embedded in fixtures.
6. No live-trading path, broker credential, or execution mutation is added.
7. Browser E2E proves the onboarding state survives restart using the supported application persistence boundary.
8. Documentation is truthful about what is Engineering Done versus Product Done.

## Out of scope

- real model calls
- provider API keys
- real data-provider authorization
- Portfolio import commit
- Watchlist mutations
- Analysis orchestration
- Approve/Reject UI
- manual execution recording
- live trading

These belong to later Productization stages.

## Verification plan

At minimum:

```text
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
uv run pytest -m integration --no-cov
uv run python scripts/check_domain_coverage.py
uv run python scripts/export_openapi.py --check
uv run python scripts/export_policy_schema.py --check
docker compose config --quiet
uv run pip-audit
uv run python scripts/check_secrets.py

cd web
npm test
npm run build
npm audit --json
```

Add an E2E acceptance test that starts from a clean database/application state and verifies the first-run onboarding surface.

## Definition of Product Done for this stage

A non-developer user can start the stack, open the browser, understand that initial configuration is required, and follow a guided sequence toward a usable system without encountering fake operational data or undocumented developer-only steps.

## Next stage

PRODUCT-02 — Settings, Secret Store & Provider Profiles.
