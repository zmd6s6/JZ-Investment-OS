# PRODUCT-01 — 产品化契约与引导骨架

- 状态：`PLANNED`
- 开始条件：PR-08 已审查、合并，且仓库状态已同步
- 约束规范：`INVESTMENT_OS_MASTER_SPEC.md`
- 产品计划：`docs/product/PRODUCTIZATION_ROADMAP.md`
- Beta 门槛：`docs/product/BETA_ACCEPTANCE.md`
- 安全基线：`auto_trade=false`；不得提交任何实盘经纪商订单

## 目标

创建第一个产品化纵切面，将仓库从面向开发者的系统转变为带引导的个人应用。

本阶段不授权真实供应商凭证、真实投资 policy 值、经纪商执行或自动交易。

## 交付物

- [ ] 明确的引导状态和首次运行检测
- [ ] 含有序步骤的设置向导外壳：
  - 市场/资产范围
  - 模型供应商占位项
  - 数据供应商占位项
  - Portfolio 引导占位项
  - Watchlist 占位项
  - Investment Policy 复核
  - Initial Analysis 就绪状态
- [ ] 设置顶级导航和产品状态页面
- [ ] 产品能力矩阵：AVAILABLE / CONFIGURATION_REQUIRED / NOT_IMPLEMENTED
- [ ] UI 不得继续将硬编码合成卡片呈现为可运营的 portfolio 状态
- [ ] 既有 PR-08 只读页面保持可用，但与产品引导清晰分离
- [ ] README 更新为实际当前能力和首次运行 UI 的准确路径
- [ ] `docs/PROJECT_STATUS.md` 更新以显示产品化计划
- [ ] 新安装 → 开始引导 → 未配置密钥/供应商/portfolio 的 E2E 浏览器测试
- [ ] 不削弱 Evidence、Risk Veto、批准、仓位规模计算或不可变历史不变量

## 验收标准

1. 新安装打开确定性的设置向导，而不是无法解释的合成仪表盘。
2. UI 清晰说明哪些必需能力未配置以及哪些尚未实施。
3. 引导不得要求用户编辑数据库行、构造原始 JSON 或运行内部开发脚本。
4. 在 PRODUCT-02 引入经过审查的 SecretStore 路径前，不实现任何密钥收集。
5. 不要求真实 Portfolio 数据，也不得将其嵌入夹具。
6. 不新增实盘交易路径、经纪商凭证或执行修改。
7. 浏览器 E2E 通过受支持的应用持久化边界证明引导状态在重启后仍保留。
8. 文档如实说明哪些是 Engineering Done，哪些是 Product Done。

## 范围外事项

- 真实模型调用
- 供应商 API 密钥
- 真实数据供应商授权
- Portfolio 导入提交
- Watchlist 修改
- Analysis 编排
- Approve/Reject UI
- 手工执行记录
- 实盘交易

这些事项属于后续产品化阶段。

## 验证计划

至少执行：

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

新增从干净数据库/应用状态开始、验证首次运行引导界面的 E2E 验收测试。

## 本阶段产品完成（Product Done）定义

非开发者用户可以启动栈、打开浏览器、理解初始配置是必需的，并沿引导顺序走向可用系统，而不会遇到
伪造的运营数据或未记录的仅开发者步骤。

## 下一阶段

PRODUCT-02 — 设置、Secret Store 与供应商配置文件。
