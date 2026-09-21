# Personal AI Investment OS — 产品化路线图

> 状态：拟议执行计划
>
> 权威：从属于 `INVESTMENT_OS_MASTER_SPEC.md`、已接受 ADR 和活动阶段契约
>
> 目的：将既有 Investment OS 内核转化为所有者无需编写代码、SQL、JSON 或 curl 命令即可使用的产品
>
> 安全基线：`auto_trade=false`；V1 不提交实盘经纪商订单

---

## 1. 产品目标

仅因领域模块、API、测试或 UI 占位项存在，项目并不视为**可正常使用**。

只有当用户可从 Web UI 完成以下工作流时，产品才达到首个可用 Beta：

```text
首次启动
→ 配置市场范围
→ 配置已授权模型供应商
→ 配置已授权数据/研究供应商
→ 导入或手工录入真实个人 Portfolio
→ 创建 Watchlist
→ 审阅/确认 Investment Policy 设置
→ 运行 Initial Analysis
→ 获得含 Evidence / Thesis / Agent opinions / Risk / 仓位规模计算的完整 Decision
→ Approve 或 Reject
→ 可选地记录一笔 MANUAL 执行
```

完成引导后，正常日常工作流是：

```text
已授权市场/研究数据
→ Evidence
→ 确定性 Features
→ Thesis 更新
→ 专家 Agent 第一轮
→ 冲突检测 / 有界第二轮
→ Portfolio Manager
→ Risk Manager
→ 确定性仓位规模计算
→ CIO Decision
→ Decision Center / Daily Report
→ 人工 Approve / Reject
→ 可选的 MANUAL 执行记录
→ 后续 Outcome / Review
```

普通使用中，任何用户都不应需要操作 Python、SQL、原始 JSON、curl 或内部数据库表。

## 2. 产品完成术语

### 工程完成（Engineering Done）

一个组件已实现、经过测试、尊重架构边界并通过必需 CI。

### 产品完成（Product Done）

组件已接入运行中的产品，并可通过受支持的用户工作流访问。

一个未接入运行时的 class、adapter、API 或 React 界面**不是产品完成**。

示例：

- 没有运行中 worker 触发的 Scheduler classes：仅工程完成。
- 没有导入/引导的 Portfolio domain objects：仅工程完成。
- 没有真实可配置供应商的 model gateway interfaces：仅工程完成。
- 由硬编码合成数据支持的 UI cards：仅工程完成。
- 没有批准交互界面的 approval domain objects：仅工程完成。

Beta 门槛要求端到端工作流达到产品完成。

## 3. 目标产品界面

Web 应用最终必须提供以下面向用户的区域：

1. **Setup Wizard**
2. **Dashboard**
3. **Portfolio**
4. **Watchlist**
5. **Opportunities**
6. **Decision Center**
7. **Thesis / Research Detail**
8. **Reports**
9. **Settings / Providers / System Health**

既有四个 PR-08 只读视图只是展示基础，并非最终产品契约。

## 4. 首次运行 Setup Wizard

新安装必须检测引导尚未完成，并打开 Setup Wizard。

### 第 1 步 — 市场和资产范围

初始支持范围应可配置；V1 预计支持以下产品结构所需范围：

- A 股股票；
- 香港股票 / ETF；
- 在存在适当已授权数据源时人工管理的基金持仓。

用户选择市场范围和市场时区/日历配置文件。

### 第 2 步 — 模型供应商

用户配置一个或多个模型配置文件。

最低字段：

```text
name
provider_type
base_url
model_name
credential_ref
timeout_seconds
max_tokens
enabled
```

V1 实现应在既有 `LLMGatewayPort` 后提供一个 **OpenAI-compatible adapter**。

这必须支持兼容供应商，且不将领域代码耦合至供应商 SDK。

必需 UX：

- 创建/编辑/禁用配置文件；
- 掩码密钥展示；
- Test Connection；
- 结构化输出能力检查；
- 延迟/错误结果；
- 存储后绝不向浏览器返回密钥。

### 第 3 步 — Agent/模型分配

支持：

```text
Default Model
Macro
Industry
Fundamental
Market/Quant
Event
Portfolio Manager
Risk Manager
Devil's Advocate
CIO
Review
```

V1 可以将每个角色分配给一个默认模型，但模式必须支持角色级分配。

每个 AgentRun 必须保留实际使用的供应商/模型。

### 第 4 步 — 数据 / 研究供应商

通过应用端口配置一个已授权供应商。

首选的第一项集成：

```text
ResearchProviderPort
        ↑
     DSAAdapter
```

UI 必须支持：

- 供应商端点/配置；
- 必要时的凭据引用；
- Test Connection；
- 能力展示；
- 上次成功同步；
- 数据新鲜度/健康状态。

供应商授权/许可仍是人工治理决定。不得静默启用任何供应商。

### 第 5 步 — Portfolio 引导

用户必须可以：

- 手工添加持仓；
- 导入 CSV；
- 如果同阶段实现成本合理，导入 Excel；
- 在提交前预览和验证。

首个 Beta 不要求经纪商自动同步。

所需导入流：

```text
Upload
→ Parse
→ Normalize symbol
→ Match/Create Instrument
→ Validate currency / quantity / cost / bucket
→ Preview
→ Human Confirm
→ Commit
→ Audit
```

上传在明确确认前绝不修改 Portfolio。

建议导入字段：

```text
account
market
symbol
name
asset_type
currency
quantity
avg_cost
bucket
```

不得将任何真实个人 portfolio 数据提交至仓库夹具、日志、截图或测试。

### 第 6 步 — Watchlist

用户可以搜索/添加/移除标的，并检查生命周期状态：

```text
DISCOVER → WATCH → SETUP → BUYABLE → HOLD
```

### 第 7 步 — Investment Policy 审阅

用户审阅所有当前生效值。

在所有者明确批准真实值前，产品必须显著标记 `TEST_DEFAULT`，且不得将它们呈现为真实投资 policy。

真实 policy 选择仍受 Master Spec 治理。

### 第 8 步 — Initial Analysis

一项受支持动作启动第一次完整影子分析。

```text
Run Initial Analysis
```

该动作不执行交易。

## 5. 模型集成契约

### 5.1 架构

```text
AgentRuntime
   ↓
LLMGatewayPort
   ↓
OpenAICompatibleLLMGateway
   ↓
Configured provider
```

领域代码不得导入模型 SDK。

### 5.2 强制运行时行为

保留既有 AgentOpinion 和模型治理要求：

- 严格 Pydantic/JSON schema；
- 事实观察要求 Evidence；
- 最多两次 schema 修复尝试；
- 失败成为明确 failure / INSUFFICIENT_DATA；
- 不得将自由文本回退为有效 opinion；
- 超时有界；
- 记录 provider/model/prompt/schema/input hash/output 元数据；
- 外部模型输出不可信。

### 5.3 故障转移

首个 Beta 可选，但数据模型应支持以后显式回退。

任何回退必须：

- 在 AgentRun 中可见；
- 绝不静默；
- 保留 schema/invariants；
- 绝不默认将不可用分析转换为 BUY/ADD。

### 5.4 成本控制

展示或强制执行：

- 单次调用 token 上限；
- 角色级超时；
- 在供应商数据允许时的每日 token/成本预算；
- 预算超出时的明确降级行为。

## 6. 密钥处理

API keys 和供应商 tokens 不得以普通明文设置存储或返回。

引入 `SecretStore` 抽象。

最低 V1 要求：

- 本地静态加密密钥存储或其他经过审查的本地密钥机制；
- 数据库/配置仅存储 `credential_ref`；
- 在日志、审计负载、API 响应、截图、测试和导出报告中排除密钥；
- UI 只显示掩码值；
- 修改密钥创建可审计配置事件，但不存储旧明文值。

个人/本地 V1 不要求生产级云密钥管理器。

## 7. Portfolio 产品契约

Portfolio 必须成为用户拥有的运营对象，而不只是领域模型。

必需能力：

- Portfolio 摘要；
- 现金；
- NAV；
- 货币；
- 持仓；
- Core/Tactical 拆分；
- 平均成本；
- 当前权重；
- 行业/主题敞口；
- 风险容量；
- 最新 Decision；
- 最新 Thesis 状态；
- 对账状态。

每次导入/更新均保留可审计性和业务时间。

不得静默推断缺失成本/数量。

## 8. Watchlist 和机会发现

### Watchlist

用户拥有的监控清单，包含：

- 当前生命周期状态；
- Thesis 状态；
- 数据新鲜度；
- 下一监控条件；
- 最新 Decision；
- 进入/离开清单的原因。

### Opportunities

系统必须支持所有者定期发现候选项的要求。

每周工作流：

```text
market universe
→ deterministic tradability filter
→ deterministic financial/quality filters
→ industry/growth/valuation filters
→ timing filter
→ bounded candidate set
→ AI deep research only for candidates
```

不得对整个市场范围无差别运行高成本强模型分析。

Opportunity UI 必须展示：

- 标的为何进入漏斗；
- 哪些 Evidence 可用/缺失；
- 当前生命周期状态；
- 推进所需条件；
- 是否存在 Portfolio 容量。

## 9. 运行时 Analysis Orchestrator

创建一个应用层编排用例，例如：

```text
InvestmentAnalysisOrchestrator
```

输入契约应包含：

```text
portfolio_id
instrument_id or scope
as_of
trigger
correlation_id
```

编排器负责连接已受治理的组件，而非替换它们。

预期流程：

```text
authorized data sync
→ Evidence validation
→ FeatureSnapshot
→ Thesis evaluation/update
→ frozen AnalysisContext
→ specialist Agent Round 1
→ deterministic conflict detection
→ targeted Round 2 + Devil's Advocate
→ Portfolio Manager risk_intent
→ Risk Assessment
→ deterministic Position Sizing
→ CIO
→ InvestmentDecision
→ immutable persistence
→ report/update event
```

既有失败闭合的 Risk、Evidence、仓位规模计算、批准和不可变性约束仍具权威性。

## 10. AnalysisRun

长时间分析需要持久、用户可见的运行对象。

建议状态：

```text
QUEUED
RUNNING
PARTIAL
SUCCEEDED
FAILED
CANCELLED
```

必需可见性：

- trigger；
- as_of；
- started/finished；
- current stage；
- 降级/失败组件；
- correlation id；
- 不泄露密钥/原始敏感负载。

API/UI 必须提供受支持的 **Run Analysis Now** 动作。

该动作只运行分析，绝不创建实盘经纪商订单。

## 11. 决策中心（Decision Center）

Decision Center 是主要的日常交互界面。

每个 Decision 展示：

- instrument；
- Action；
- confidence；
- Core action；
- Tactical action；
- current weight；
- proposed target weight；
- proposed delta quantity；
- Thesis state；
- Risk gate；
- major risk flags；
- Evidence freshness；
- top reasons；
- unknowns；
- dissent；
- watch/invalidation conditions；
- next review；
- 精确的 Decision/Thesis/Policy/Strategy/Prompt/Formula versions。

Agent opinions 必须作为可下钻详情，而不是受治理 Decision 的替代物。

## 12. 人工批准和手工执行

提供受支持用户动作：

```text
APPROVE
REJECT
REVOKE
```

批准必须使用既有不可变/失败闭合领域语义。

V1 保持：

```text
auto_trade=false
```

Beta 要求中不包含任何经纪商订单端点。

用户在外部完成交易后，UI 可以记录一笔 `MANUAL` 执行：

- quantity；
- price；
- fees；
- executed_at；
- 经清洗的外部引用 / 备注。

批准不是执行。

Risk Veto 永远不能被 UI 覆盖。

## 13. 调度器和 worker 运行时

只有正在运行的 worker 实际评估到期任务并进行分派时，调度器才算 Product Done。

必需运行时链：

```text
investment-worker
→ authorized/explicit Market Calendar
→ due jobs
→ durable dispatcher
→ advisory lock
→ TaskRun
→ business handler
→ Event/Outbox
→ Report/Decision effects
```

必需节奏：

- Daily；
- Weekly；
- Monthly；
- Quarterly。

调度必须保留明确市场时区、业务 `as_of`、重试/重放、幂等性、有界失败，且不得假设服务器本地时间。

集成/E2E 验证必须证明运行时分派；直接调用 dispatcher 的测试不能作为唯一证明。

## 14. Dashboard 契约

Dashboard 应回答：

1. 今天什么需要动作？
2. 我的 Portfolio 发生了什么变化？
3. 是否存在活跃 Risk Veto？
4. 哪些 Decisions 等待批准？
5. 哪些 Evidence/Data 已陈旧？
6. 出现了哪些新机会？
7. 定时任务是否成功？
8. 什么需要人工关注？

不得将 Dashboard 做成通用市场新闻流。

## 15. 报告

日/周/月报告应从已验证内部对象生成，并清晰区分：

- 事实；
- 确定性计算；
- Agent 判断；
- 假设/未知项；
- 人工决定。

每日报告至少应包含：

- 需要动作；
- 继续持有；
- 观察；
- 新发现；
- 风险/数据/运行异常。

## 16. Beta 所需 API 表面

精确 URI 命名可以通过审查过的 API 设计改变，但产品必须提供等价能力。

### Providers / Settings

```text
GET/PUT settings
GET/POST model-providers
POST model-providers/{id}/test
GET/POST data-providers
POST data-providers/{id}/test
```

### Portfolio / Watchlist

```text
GET portfolio
POST portfolio/import/preview
POST portfolio/import/commit
POST portfolio/positions
GET/POST watchlist
DELETE watchlist/{id}
```

### Analysis

```text
POST analysis-runs
GET analysis-runs/{id}
```

### Decisions

```text
GET decisions
GET decisions/{id}
POST decisions/{id}/approve
POST decisions/{id}/reject
POST decisions/{id}/revoke
POST decisions/{id}/manual-executions
```

### Reports / Operations

```text
GET reports/daily/latest
GET reports/weekly/latest
GET reports/monthly/latest
GET task-runs
```

每项修改均要求验证、审计、适用时的幂等性，以及适合个人部署模型的授权。

## 17. 产品化交付阶段

### P0 — 正确完成当前 PR-08

在开始新产品化阶段前，必须完成：

- 将调度器接入实际 worker/运行时；
- 通过集成/E2E 证明运行时分派；
- 更正 PR-07 合并 SHA 文档；
- 更新过期 README 的当前能力/限制；
- 保留当前 PR-08 阶段的合成/只读约束。

PR-08 必须审查并合并后才能实施 P1。

### P1 — 产品化契约与引导骨架

交付：

- 本产品化契约被接受并纳入仓库；
- Setup Wizard 外壳；
- 引导状态；
- Settings 导航；
- 明确的 Beta 验收引用；
- 尚不接入真实密钥/供应商。

验收：新安装进入确定性引导工作流，而非无法解释的合成仪表盘。

### P2 — 设置、Secret Store 与供应商配置文件

交付：

- SystemSettings；
- ModelProviderProfile；
- DataProviderProfile；
- RoleModelAssignment；
- SecretStore；
- 供应商 CRUD/测试 API；
- Settings UI。

验收：供应商密钥可以安全配置，连接测试可见且可审计。

### P3 — 真实模型运行时

交付：

- OpenAI-compatible LLM adapter；
- 通过既有 `LLMGatewayPort` 的真实可配置模型路径；
- 角色分配；
- 超时/预算/错误处理；
- AgentRun 中的供应商/模型元数据。

验收：合成 Evidence 夹具可以经完整 AgentOpinion 模式路径运行已授权真实模型，且不削弱失败闭合行为。

### P4 — 已授权数据供应商运行时

交付：

- 可运行的 DSAAdapter 或其他明确已授权供应商；
- 供应商健康/新鲜度；
- 规范化 Evidence 摄取；
- 真实/影子数据边界。

验收：一个已授权真实标的可以产生可追溯 Evidence，且不直接耦合 DSA/私有数据库。

### P5 — Portfolio 与 Watchlist 产品

交付：

- Portfolio UI/API；
- 手工持仓录入；
- CSV 导入预览/确认；
- 对账；
- Watchlist CRUD；
- 标的搜索/规范化。

验收：所有者无需接触 SQL/JSON/代码即可载入个人 Portfolio；真实 portfolio 数据不会进入仓库资产。

### P6 — 端到端 Analysis Orchestration

交付：

- AnalysisRun；
- InvestmentAnalysisOrchestrator；
- 立即运行分析；
- 进度/失败可见性；
- 完整 Evidence → Decision 持久化。

验收：一个选定标的可使用已配置模型/数据供应商完成完整影子投资周期。

### P7 — 交互式决策与批准

交付：

- 由真实 API 支撑的 Decision 列表/详情；
- Evidence/Thesis/Agent/Risk/仓位规模计算下钻；
- Approve/Reject/Revoke；
- 手工执行记录。

验收：所有者可完全通过 UI 处理 Decision；不可能产生任何实盘经纪商订单。

### P8 — 每日 AI 团队运行时

交付：

- 定时数据同步；
- Portfolio/Watchlist Evidence diff；
- 自动分析触发；
- 每日报告；
- 每周机会筛选；
- 每月 Portfolio 复核；
- 明确失败/降级状态。

验收：到期市场会话使正在运行的 worker 在无需手工 CLI 调用时产生预期的持久分析/报告效果。

### P9 — Beta 验收

运行 `docs/product/BETA_ACCEPTANCE.md` 中完整验收门槛。未通过 P9，不得声称产品可正常使用。

### PR-09 — Outcome、Review/Learning、加固与发布

PR-09 在可用 Beta 之后执行，完成：

- Outcome；
- Review/Attribution；
- Agent 性能评估；
- StrategyProposal；
- Backtest；
- Shadow 验证；
- 人工治理的激活；
- 备份/恢复；
- 安全/性能加固；
- 可追溯性矩阵；
- 发布检查清单。

## 18. 产品化所需工程纪律

从 P1 起：

- 不得只实现一个 class；应将其接入运行时。
- 不得只实现一个 API；应连接受支持的 UI 流。
- 不得只实现一个 UI；除明确 demo 状态外，应由真实应用 API 支撑。
- 不得使用硬编码合成卡片来声称产品工作流完成。
- 每项修改均须有正常/失败/边界测试。
- 关键工作流要求 E2E 覆盖。
- 真实个人数据不得进入仓库夹具。
- 供应商密钥不得进入日志和 API 响应。
- 保留失败闭合的 Risk 和批准语义。
- 保留 `auto_trade=false`。
- 不得为了加快产品化而削弱 Master Spec。

## 19. 仍在 Codex 权限之外的人工治理决定

Codex 可以实现可配置机制，但不得自行选择以下真实值：

- 真实 Investment Policy 限制；
- 实际供应商/许可授权；
- 保留/隐私/成本边界；
- 真实批准主体和 TTL；
- 影响所有者支出的模型供应商预算限制；
- 真实数据源优先级；
- 经纪商集成；
- 启用实盘执行；
- StrategyProposal 激活。

当其中一个决定仅阻塞某个子功能时，Codex 应继续全部独立的安全工作。

## 20. 产品化成功声明

首个 Beta 在所有者能够如实声明以下内容时才成功：

> 我可以启动栈、打开浏览器、配置我已授权的模型和数据供应商、导入我的 Portfolio、管理 Watchlist、运行或接收定时分析、检查 Evidence/Thesis/Agent/Risk/仓位规模计算、接收 CIO Decision、Approve 或 Reject，并记录一笔手工执行——而无需接触源代码、SQL、原始 JSON 或内部工具。

在该声明可被证明为真之前，即使单个工程阶段均为绿色，项目仍处于产品化阶段。
