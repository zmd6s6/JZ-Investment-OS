# Personal AI Investment OS

中文版本与本地化状态见 [README.zh-CN.md](README.zh-CN.md) 和
[docs/zh-CN/README.md](docs/zh-CN/README.md)。如译文与项目宪章或已接受 ADR 有歧义，以权威原始记录为准。

Personal AI Investment OS is an evidence-first, long-lived investment research and portfolio decision system. It is independent from DSA: DSA supplies research/data through an adapter, while this project owns Thesis, Portfolio, Risk, Decision, Approval, Journal, and Review state.

The repository currently includes PR-01 through PR-08 development work: a pure domain kernel,
PostgreSQL persistence/audit/outbox primitives, synthetic DSA/Evidence/Thesis/Committee/Risk/Decision
workflows, explicit approval and disabled-live-execution gates, and a read-only personal UI. The
worker can dispatch only a schema-validated, explicitly supplied synthetic calendar; it does not
infer market sessions or connect to a real market-data provider. The project includes only a
synthetic Agent Runtime and gateway contract; real model-provider configuration, real data-provider
configuration, portfolio import, and live brokerage execution are not provided.

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
- Node.js 24+ for the PR-08 personal UI workspace

The PR-08 React workspace is in `web/`. Its development-only commands are `npm install`, `npm test`,
and `npm run build` from that directory. The API image builds the static UI and serves it from its
own origin, so its read-only `/api/v1/task-runs` request does not require a browser CORS exception.

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

`uv run pytest` now requires the PostgreSQL service because PR-02 integration and migration tests
are part of the canonical suite. Start it with `docker compose up --detach --wait postgres`. The
domain coverage check reads the coverage data produced by the preceding test run. Do not report a
check as passed unless it was actually run.

Run only the PostgreSQL acceptance slice without replacing the full coverage data:

```text
uv run pytest -m integration --no-cov
```

## Database migrations

The Compose stack runs a one-shot `investment-migrate` service before API and worker startup. For
host-side migration verification:

```text
uv run alembic upgrade head
uv run alembic current
```

An empty development database can be round-tripped with `alembic downgrade base` followed by
`alembic upgrade head`. Do not downgrade a populated database: take a backup and use a reviewed
forward-fix migration. See [`docs/runbooks/migrations.md`](docs/runbooks/migrations.md).

## Run the bootstrap stack

```text
docker compose up --build --detach --wait
uv run python scripts/smoke.py
```

Expected services:

- PostgreSQL on `${POSTGRES_PORT:-5432}`
- One-shot Alembic migration to the recorded head revision
- API on `http://localhost:${API_PORT:-8100}`
- Read-only personal UI on `http://localhost:${API_PORT:-8100}/`
- Worker with a database-backed readiness marker
- Optional synthetic calendar dispatch when `INVESTMENT_OS_WORKER_SCHEDULE_CALENDAR_PATH` is set;
  it writes durable TaskRuns and a simulation-only Daily report, never an approval or execution
  action. `config/synthetic-runtime-calendar.json` is a development-only example and is not
  enabled by default.

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

PR-02 migrations contain only synthetic/development data during project construction. To rebuild a
disposable local environment:

1. run `docker compose down --volumes` only if local PostgreSQL data may be discarded;
2. remove the ignored `.venv` and `.env` files if needed;
3. run `uv sync --frozen --group dev` and restart Compose.

Never use destructive Git commands as a recovery mechanism. Preserve unrelated human changes.
