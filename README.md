# Personal AI Investment OS

Personal AI Investment OS 是一个以证据为先、可长期运行的个人投资研究与组合决策系统。它独立于 DSA：
DSA 通过适配器提供研究/数据，而本项目拥有 Thesis、Portfolio、Risk、Decision、Approval、Journal 和
Review 状态。

仓库当前包含 PR-01 至 PR-08 的开发工作：纯领域内核、PostgreSQL 持久化/审计/outbox 原语、合成
DSA/Evidence/Thesis/Committee/Risk/Decision 工作流、明确的批准与禁用实盘执行关卡，以及只读个人 UI。
worker 只能分派经模式验证、显式提供的合成日历；它不推断市场会话，也不连接真实市场数据供应商。
项目包含经审计的模型/数据提供方配置元数据与本地加密凭据存储。PRODUCT-03 已接入
OpenAI-compatible 模型网关和显式的模型连接测试；它不自动选择、启用或调用任何提供方，且仍不提供
真实数据供应商运行时、组合导入或实盘经纪商执行。

## 安全状态

- 当前模式：`DEVELOPMENT`
- 实盘交易：禁止
- 自动交易：由项目宪章禁用
- 测试数据：仅限合成或明确获授权的数据
- 权威规范：[`INVESTMENT_OS_MASTER_SPEC.md`](INVESTMENT_OS_MASTER_SPEC.md)

## 前置条件

- Git
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop 或带 Compose 的 Docker Engine
- 用于 PR-08 个人 UI 工作区的 Node.js 24+

PR-08 React 工作区位于 `web/`。仅用于开发的命令是在该目录中运行 `npm install`、`npm test` 和
`npm run build`。API 镜像构建静态 UI 并从自身 origin 提供它，因此其只读 `/api/v1/task-runs` 请求
无需浏览器 CORS 例外。

## 本地开发设置

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

已提交的 `.env.example` 仅含本地占位值。端口冲突时替换被忽略的 `.env` 文件中的值；绝不提交真实密钥。

### PRODUCT-03 模型提供方与凭据

在保存任何提供方凭据前，为 API 生成一个本地 Fernet 主密钥并仅写入被忽略的环境文件：

```text
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

将输出赋给 `INVESTMENT_OS_SECRET_STORE_KEY`，随后重启 API 容器。数据库、审计、Event、Outbox、日志和
HTTP 响应均不保存或回传凭据；数据库仅保存不可读的引用。丢失主密钥后不能恢复旧凭据，必须重新配置。
未设置主密钥时，系统设置仍可读取，但涉及凭据的保存与校验会明确失败关闭。模型“测试连接”仅在所有者
明确点击后才会发送一个不含 Evidence、Portfolio 或交易内容的最小 JSON 请求，用于检查认证和
结构化输出；非回环地址必须使用 HTTPS。数据提供方“测试配置”仍不发起网络请求，真实数据调用属于
后续 PRODUCT-04，且仍需要人工授权。

## 规范验证

从仓库根目录运行：

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

`uv run pytest` 现在需要 PostgreSQL 服务，因为 PR-02 的集成和迁移测试属于规范测试套件。使用
`docker compose up --detach --wait postgres` 启动它。领域覆盖率检查读取前一次测试产生的覆盖率数据。
除非实际运行，切勿报告检查已通过。

仅运行 PostgreSQL 验收切片而不覆盖完整覆盖率数据：

```text
uv run pytest -m integration --no-cov
```

## 数据库迁移

Compose 栈在 API 和 worker 启动前运行一次性 `investment-migrate` 服务。主机侧迁移验证：

```text
uv run alembic upgrade head
uv run alembic current
```

空开发数据库可使用 `alembic downgrade base` 再执行 `alembic upgrade head` 往返验证。不得降级已填充
数据库：应先备份并使用经过审查的前向修复迁移。参见 [`docs/runbooks/migrations.md`](docs/runbooks/migrations.md)。

## 运行引导栈

```text
docker compose up --build --detach --wait
uv run python scripts/smoke.py
```

预期服务：

- `${POSTGRES_PORT:-5432}` 上的 PostgreSQL
- 执行至已记录 head 修订版的一次性 Alembic 迁移
- `http://localhost:${API_PORT:-8100}` 上的 API
- `http://localhost:${API_PORT:-8100}/` 上的只读个人 UI
- 带数据库支持就绪标记的 Worker
- `INVESTMENT_OS_WORKER_SCHEDULE_CALENDAR_PATH` 设置时的可选合成日历分派；它写入持久 TaskRuns 和
  仅模拟 Daily 报告，绝不写入批准或执行动作。`config/synthetic-runtime-calendar.json` 是仅开发示例，
  默认未启用。

检查或停止栈：

```text
docker compose ps
docker compose logs investment-api investment-worker postgres
docker compose down
```

作为明确且具有破坏性的清理步骤，移除本地开发数据库：

```text
docker compose down --volumes
```

命名卷包含本地引导数据，除非另行备份，移除后无法恢复。

## 健康检查契约

- `GET /health/live`：仅进程存活。
- `GET /health/ready`：就绪状态及真实 PostgreSQL `SELECT 1` 探针。

健康负载明确报告 `mode=DEVELOPMENT` 和 `live_trading=false`，不会声称投资功能已经存在。

## 仓库地图

```text
src/investment_os/
├── domain/          # 纯值、Policy、状态机和规则
├── application/     # 严格边界、端口和用例
├── infrastructure/  # 数据库和外部适配器
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

工作模式见 [`docs/WORKING_MODE.md`](docs/WORKING_MODE.md)，当前阶段见
[`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)。

## 恢复与回滚

项目构建期间，PR-02 迁移仅包含合成/开发数据。要重建可丢弃的本地环境：

1. 仅在可丢弃本地 PostgreSQL 数据时执行 `docker compose down --volumes`；
2. 必要时移除被忽略的 `.venv` 和 `.env` 文件；
3. 执行 `uv sync --frozen --group dev` 并重启 Compose。

绝不使用破坏性 Git 命令作为恢复机制。保留无关的人类改动。
