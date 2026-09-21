# PRODUCT-01 — 产品化与引导配置骨架

- 状态：`READY_FOR_REVIEW`
- 前置条件：PR-08 已审查、合并，并已同步项目状态
- 治理规范：`INVESTMENT_OS_MASTER_SPEC.md`
- 产品计划：`docs/product/PRODUCTIZATION_ROADMAP.md`
- Beta 门槛：`docs/product/BETA_ACCEPTANCE.md`
- 安全基线：`auto_trade=false`；不得提交任何实盘券商订单

## 目标

交付产品化的第一个切片，将当前面向开发者的系统转变为带有明确引导的个人应用。

本阶段不授权真实提供方凭据、真实投资政策数值、券商执行或自动交易。

## 交付项

- [x] 显式的引导配置状态与首次启动识别
- [x] 按顺序展示的设置向导壳：
  - 市场/资产范围
  - 模型提供方占位项
  - 数据提供方占位项
  - 组合初始化占位项
  - 观察清单占位项
  - 投资政策复核
  - 初始分析就绪
- [x] 顶层“设置向导”和“产品状态”导航
- [x] 产品能力矩阵：`AVAILABLE` / `CONFIGURATION_REQUIRED` / `NOT_IMPLEMENTED`
- [x] UI 不再将硬编码合成卡片表现为可运营的组合状态
- [x] PR-08 的只读演示页保留为可访问页面，并与产品引导清楚隔离
- [x] README 说明当前实际能力与首次进入 UI 的准确路径
- [x] `docs/PROJECT_STATUS.md` 记录产品化计划
- [x] 浏览器 E2E：全新安装 → 开始引导 → 未配置提供方或组合
- [x] 不削弱证据、风险否决、审批、仓位计算或不可变历史不变量

## 验收标准

1. 全新安装会打开确定性的设置向导，而不是未经解释的合成仪表盘。
2. UI 明确展示哪些能力尚未配置，哪些能力尚未实现。
3. 不要求用户为完成引导而编辑数据库行、构造原始 JSON 或运行内部开发脚本。
4. 在 PRODUCT-02 引入经过审查的 `SecretStore` 路径前，不实现任何凭据收集。
5. 不要求、也不在测试夹具中嵌入任何真实组合数据。
6. 不新增实盘交易路径、券商凭据或执行写操作。
7. 浏览器 E2E 通过受支持的应用持久化边界证明引导状态可跨重启保留。
8. 文档如实区分“工程完成”和“产品完成”。

## 范围外

- 真实模型调用
- 提供方 API 密钥
- 真实数据提供方授权
- 组合导入提交
- 观察清单写操作
- 分析编排
- 批准/拒绝 UI
- 手工执行记录
- 实盘交易

这些工作属于后续产品化阶段。

## 验证计划

至少运行：

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
npx playwright install chromium
npm run test:e2e
npm audit --json
```

E2E 必须从干净的本地开发数据库/应用状态运行；测试会验证浏览器中的首次引导、开始设置和刷新后的持久化状态，且 API 响应不含提供方、凭据或组合字段。

## 本阶段的产品完成定义

非开发者可以启动服务、在浏览器打开产品、理解仍需初始配置，并沿受引导的顺序前进；过程中不会遇到伪装成运营数据的合成信息，也不需要查找未记载的开发者专用步骤。

## 验证证据（2026-09-21）

- `uv run ruff format --check .`：通过。
- `uv run ruff check .`：通过。
- `uv run mypy src`：通过（64 个源文件）。
- `uv run pytest -q`：通过（309 项）。
- `uv run pytest -m integration --no-cov`：通过；其中迁移与引导状态集成测试验证了状态、事件和 Outbox。
- `uv run python scripts/check_domain_coverage.py`：领域行覆盖率 97.96%，分支覆盖率 86.75%。
- `uv run python scripts/export_openapi.py --check` 与 `uv run python scripts/export_policy_schema.py --check`：通过。
- `docker compose config --quiet`、`uv run python scripts/check_secrets.py`：通过。
- `npm test`、`npm run build`、`npm audit --json`：通过；前端审计为零漏洞。
- `docker compose up --detach --wait` 后执行 `npm run test:e2e`：通过（Chromium，首次进入 → 开始设置 → 刷新后持久化）。

首次 E2E 尝试在 API 尚未启动时出现连接挂断；随后启动完整 Compose 栈并以同一测试通过。该失败未掩盖，也不代表产品行为失败。

## 下一阶段

PRODUCT-02 — 设置、密钥存储与提供方档案。
