# Personal AI Investment OS

Personal AI Investment OS is an evidence-first, long-lived investment research and portfolio decision system. It is independent from DSA: DSA supplies research/data through an adapter, while this project owns Thesis, Portfolio, Risk, Decision, Approval, Journal, and Review state.

The repository has completed the local implementation of **PR-01 domain foundations** and is ready
for review. It provides exact value objects, strict test Policy validation, and governed state
machines. It does not provide investment advice, persisted portfolio decisions, runtime investment
agents, or trade execution.

## Safety status

- Current mode: `DEVELOPMENT`
- Live trading: forbidden
- Automatic trading: disabled by project constitution
- Test data: synthetic or explicitly authorized only
- Governing specification: [`INVESTMENT_OS_MASTER_SPEC.md`](INVESTMENT_OS_MASTER_SPEC.md)

## Prerequisites

- Git
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop or Docker Engine with Compose

Node.js is not required in PR-00. ADR-0001 defers the React workspace until PR-08, when the UI contract exists.

## Local development setup

PowerShell:

```powershell
Copy-Item .env.example .env
uv sync --frozen --group dev
```

POSIX shell:

```sh
cp .env.example .env
uv sync --frozen --group dev
```

The committed `.env.example` contains local placeholders only. Replace values in the ignored `.env` file if ports conflict; never commit real secrets.

## Canonical verification

Run from the repository root:

```text
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
uv run python scripts/check_domain_coverage.py
uv run python scripts/export_openapi.py --check
uv run python scripts/export_policy_schema.py --check
docker compose config
uv run pip-audit
uv run pip-licenses --format=markdown --with-urls
uv run python scripts/check_secrets.py
```

These are the authoritative baseline and PR-01 checks. The domain coverage check reads the coverage
data produced by the preceding test run. Do not report a check as passed unless it was actually run.

## Run the bootstrap stack

```text
docker compose up --build --detach --wait
uv run python scripts/smoke.py
```

Expected services:

- PostgreSQL on `${POSTGRES_PORT:-5432}`
- API on `http://localhost:${API_PORT:-8100}`
- Worker with a database-backed readiness marker

Inspect or stop the stack:

```text
docker compose ps
docker compose logs investment-api investment-worker postgres
docker compose down
```

Remove the local development database as an explicit, destructive cleanup step:

```text
docker compose down --volumes
```

The named volume contains local bootstrap data and cannot be recovered after removal unless separately backed up.

## Health contract

- `GET /health/live`: process liveness only.
- `GET /health/ready`: readiness plus a real `SELECT 1` PostgreSQL probe.

Health payloads explicitly report `mode=DEVELOPMENT` and `live_trading=false`. They do not claim that investment functionality exists.

## Repository map

```text
src/investment_os/
├── domain/          # pure values, Policy, state machines, and rules
├── application/     # strict boundaries, ports, and use cases
├── infrastructure/  # database and external adapters
├── api/             # FastAPI transport
└── worker/          # background process entry point

tests/
├── unit/
├── property/
├── contract/
├── integration/
├── e2e/
└── fixtures/
```

See [`docs/WORKING_MODE.md`](docs/WORKING_MODE.md) for the operating model and [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) for the current stage.

## Recovery and rollback

PR-01 has no domain migrations or real portfolio data. To rebuild the local environment:

1. run `docker compose down --volumes` only if local PostgreSQL data may be discarded;
2. remove the ignored `.venv` and `.env` files if needed;
3. run `uv sync --frozen --group dev` and restart Compose.

Never use destructive Git commands as a recovery mechanism. Preserve unrelated human changes.
