# Personal AI Investment OS

这是一个以证据为先、可长期运行的个人投资研究与组合决策系统。它与 DSA 相互独立：DSA 只能通过 Adapter 提供研究/数据，本项目负责 Thesis、Portfolio、Risk、Decision、Approval、Journal 和 Review 状态。

英文原始说明见 [README.md](README.md)。如中文译文与已接受的规范或 ADR 存在歧义，以 `INVESTMENT_OS_MASTER_SPEC.md` 及相关 ADR 为准。

## 当前能力与安全状态

- 当前模式：`DEVELOPMENT`
- 实盘交易：禁止
- 自动交易：由项目宪章永久禁用
- 测试数据：仅合成数据或已明确授权的数据
- 权威规范：[INVESTMENT_OS_MASTER_SPEC.md](INVESTMENT_OS_MASTER_SPEC.md)
- 当前产品阶段：`PRODUCT-01`；首次打开 UI 会进入“设置向导”，并展示功能状态。

当前仓库已包含 PR-01 至 PR-08 的开发成果：纯领域内核、PostgreSQL 持久化/审计/Outbox 原语、合成 DSA/Evidence/Thesis/Committee/Risk/Decision 流程、明确的人类审批和禁止实盘执行闸门，以及只读个人 UI。运行时 Worker 只能调度显式给定、经 schema 验证的合成日历；它不会推断市场交易时段，也不连接真实市场数据提供方。

目前没有真实模型提供方配置、真实数据提供方配置、组合导入或实盘券商执行。`PRODUCT-01` 的引导状态仅记录“是否已开始设置”，不收集密钥、提供方详情、真实组合或真实投资政策数值。它不是交易终端。

## 前置条件

- Git
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop 或带 Compose 的 Docker Engine
- Node.js 24+（用于 `web/` 中的 React UI）

`web/` 中的开发命令为 `npm install`、`npm test` 和 `npm run build`。API 镜像会构建并在同一源提供静态 UI；浏览器无需为只读 API 请求额外配置 CORS。

## 本地开发

PowerShell：

```powershell
Copy-Item .env.example .env
uv sync --frozen --group dev
```

POSIX shell：

```sh
cp .env.example .env
uv sync --frozen --group dev
```

提交的 `.env.example` 只含本地占位值。端口冲突时修改被忽略的 `.env`；绝不提交真实密钥。

## 规范验证命令

在仓库根目录执行：

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

`uv run pytest` 包含 PostgreSQL 集成/迁移测试，因此先启动数据库：

```text
docker compose up --detach --wait postgres
```

只运行 PostgreSQL 验收切片（不覆盖完整覆盖率数据）：

```text
uv run pytest -m integration --no-cov
```

## 迁移

Compose 会在 API 和 Worker 前运行一次性 `investment-migrate` 服务。主机侧检查：

```text
uv run alembic upgrade head
uv run alembic current
```

空开发数据库可通过 `alembic downgrade base` 再 `alembic upgrade head` 往返验证。不得降级已填充数据库；应先备份并使用审查后的前向修复迁移。详见 [迁移运行手册](docs/runbooks/migrations.md)。

## 启动栈与首次使用

```text
docker compose up --build --detach --wait
uv run python scripts/smoke.py
```

预期服务：

- PostgreSQL：`${POSTGRES_PORT:-5432}`
- 一次性 Alembic 迁移服务
- API 与 UI：`http://localhost:${API_PORT:-8100}/`
- Worker：带数据库就绪标记

首次访问 UI 时：

1. 阅读“设置向导”中的市场范围、模型/数据提供方、组合/观察清单、政策复核和分析就绪步骤。
2. 点击“开始设置”只会写入非敏感的引导进度。
3. 在产品状态中确认提供方配置、组合导入和执行尚未开放。
4. 不要输入真实凭据、组合或执行信息；这些能力未在本阶段实现。

浏览器 E2E 需要已经启动的干净开发栈：

```text
cd web
npx playwright install chromium
npm run test:e2e
```

测试会核对首次进入、开始设置和刷新后的持久化状态。若本地库不是全新状态，先按本 README 的恢复说明在确认数据可丢弃后重建开发数据库。

可查看或停止栈：

```text
docker compose ps
docker compose logs investment-api investment-worker postgres
docker compose down
```

`docker compose down --volumes` 会删除不可恢复的本地开发数据库卷，除非另有备份，不应作为常规操作使用。

## 健康检查契约

- `GET /health/live`：仅进程存活。
- `GET /health/ready`：就绪状态及真实 PostgreSQL `SELECT 1` 探针。
- `GET /api/v1/onboarding`：读取首次引导状态。
- `POST /api/v1/onboarding/start`：幂等地开始引导，并在同一事务中写入事件与 Outbox。
- `GET /api/v1/product-capabilities`：返回真实的产品能力状态；不把未接入能力伪装成可操作功能。

健康响应明确标记 `mode=DEVELOPMENT` 和 `live_trading=false`，不声称投资功能已经可用。

## 仓库结构

```text
src/investment_os/
├── domain/          # 纯值对象、Policy、状态机和规则
├── application/     # 严格边界、端口和用例
├── infrastructure/  # 数据库与外部适配器
├── api/             # FastAPI 传输层
└── worker/          # 后台进程入口

tests/
├── unit/
├── property/
├── contract/
├── integration/
├── e2e/
└── fixtures/
```

工作模式见 [docs/WORKING_MODE.md](docs/WORKING_MODE.md)，当前阶段见 [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)，中文文档索引见 [docs/zh-CN/README.md](docs/zh-CN/README.md)。
