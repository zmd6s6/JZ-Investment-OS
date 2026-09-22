# PRODUCT-03 — 真实模型运行时

- 状态：`READY_FOR_REVIEW`
- 前置条件：PRODUCT-02 与 ADR-0013 已由所有者接受
- 治理规范：`INVESTMENT_OS_MASTER_SPEC.md`
- 相关 ADR：`ADR-0001`、`ADR-0004`、`ADR-0010`、`ADR-0013`、`ADR-0014`
- 安全基线：`auto_trade=false`；模型输出和所有外部内容均为不可信数据

## 目标

通过既有 `LLMGatewayPort` 提供可配置的 OpenAI-compatible 模型路径。角色仍先解析显式分配，
再解析 `DEFAULT`，并保留实际 provider/model、请求边界和失败结果的可审计元数据。

## 首个纵切面

- [x] OpenAI-compatible HTTP 适配器，不导入供应商 SDK
- [x] 角色到启用模型档案的失败关闭解析
- [x] 仅在用户明确点击时执行的模型连接测试
- [x] JSON 对象输出请求、响应解析和严格 AgentOpinion 校验链
- [x] 请求超时、模型档案与调用请求 Token 上限、无重定向和脱敏错误
- [x] 非回环端点强制 HTTPS；本地开发仅允许回环 HTTP
- [x] AgentRun 保留实际 provider/model 与既有安全输出哈希
- [x] 设置页明确显示 P3 连接测试语义
- [x] 每任务/每日 Token 与成本的原子预算预留、结算和不可变用量记录
- [x] 可版本化的档案定价；定价、预算或预留不可用时失败关闭
- [x] 所有 Agent 角色的显式映射与 `DEFAULT` 继承 UI；不跨提供方回退

## 明确范围外

- 自动选择、自动启用或自动回退模型提供方
- 未经所有者授权的真实供应商调用、许可证决定或真实费用额度
- 数据提供方运行时（PRODUCT-04）
- Portfolio 导入、分析编排、批准、执行或任何实盘交易

## 验收标准

1. 配置的 OpenAI-compatible 档案可通过角色分配供 `AgentRuntime` 使用，且不会泄漏凭据。
2. 使用合成 Evidence 的契约夹具可穿过实际适配器、`AgentRuntime`、严格 AgentOpinion 与 Evidence
   校验链；无效输出、认证、HTTP 或超时失败均变为显式 `INSUFFICIENT_DATA`。
3. 连接测试只在所有者的显式 UI/API 动作后发出最小、无 Evidence/Portfolio/交易内容的请求，并返回
   脱敏状态和延迟；审计仅记录结果状态。
4. 外部端点必须使用 HTTPS；仅 `localhost`、`127.0.0.1` 和 `::1` 可使用 HTTP 供本地开发。
5. Risk Veto、确定性仓位计算、人类批准与 `auto_trade=false` 不发生变化。
6. 每次模型网络调用（包括连接测试）在发送前原子预留任务/日 Token 与成本；预算或定价缺失、用量不可验证、预留失败或超限均不得发送请求。

## 验证计划

- OpenAI-compatible MockTransport 契约：正常响应、HTTP/认证失败、非 TLS 外部端点、结构化连接测试和
  完整 AgentOpinion 路径。
- 现有 AgentRuntime、LLMGateway、设置 API 与持久化审计回归。
- 全量格式、lint、类型、Python/前端测试、OpenAPI、密钥扫描、依赖审计和 Compose 配置。

## 所需人工决定

真实提供方、许可、费用预算和任何实际凭据均由所有者决定。实现与 MockTransport 验证不构成对真实模型、
真实投资数据或任何交易行为的授权。

## 实现与验证证据

- `OpenAICompatibleLLMGateway` 使用 `httpx`，通过 `ProviderSettingsService.model_for_role`
  解析角色档案，并仅在内存中从 `SecretStore` 读取 credential。请求禁用重定向，外部端点强制 HTTPS，
  并将档案和调用方的 timeout/Token 上限取更严格值。
- 连接测试只发送固定的无业务 JSON 请求；它将认证、HTTP、响应 Schema 与 JSON 对象失败统一脱敏为
  `CONNECTION_FAILED`，并只持久化测试结果状态。提供方原始输出不写入审计记录。
- `ADR-0014` 规定预算策略、定价快照、预留、日/任务账本与追加式用量记录。修复请求保留同一
  `request_id`，因此与初始请求共享任务累计额度；不确定的失败保留预留以避免低估使用量。
- 2026-09-22：`ruff format --check .`、`ruff check .`、`mypy src`、`docker compose config --quiet`、
  `scripts/export_openapi.py --check`、`scripts/export_policy_schema.py --check`、
  `scripts/check_secrets.py`、`pip-audit` 与 `scripts/check_domain_coverage.py` 均通过。
- 2026-09-22：修改后已通过 `ruff format --check .`、`ruff check .`、`mypy src`、
  `scripts/export_openapi.py --check`、`docker compose config --quiet`、P3 MockTransport 与预算单元测试
  （12 项）以及前端 Vitest（4 项）和生产构建。完整 `pytest` 在本机集成环境未完成，交由 PR CI 复验。
  P3 MockTransport 契约覆盖正常角色路由、实际模型元数据、Token 超限、非 TLS 外部端点、显式连接测试、
  完整 AgentOpinion 路径和 HTTP 失败降级；预算测试覆盖缺少策略/定价的失败关闭及修复共用累计额度。
- 2026-09-22：`web` 的 Vitest 4 项、生产构建和隔离 Compose 栈的 Playwright 2 项均通过。隔离栈使用
  独立端口、卷与临时测试主密钥，验证结束后已移除。
- 2026-09-22：在所有者显式授权和本地运行时配置下，DeepSeek V4.1 Flash 的最小连接测试已通过（861 ms）。
  该请求不含 Evidence、Portfolio 或交易内容；认证、HTTPS、预算预留、可验证用量结算和 JSON 对象输出均已验证。
  凭据、实际定价与测试限额未写入仓库、日志或评论。
- 2026-09-22：使用仅含 UUID/哈希的合成 Evidence，真实 DeepSeek 已完成
  `OpenAICompatibleLLMGateway → AgentRuntime → 严格 AgentOpinion → Evidence 引用校验` 网络验收。
  首次响应即通过（无修复）；记录的脱敏遥测为 `DeepSeek V4.1 Flash` / `deepseek-flash`、2689 ms、
  425 输入 Token、452 输出 Token、USD 0.0006699。未发送真实 Evidence、Portfolio 或交易数据，未记录原始
  模型输出或凭据。
