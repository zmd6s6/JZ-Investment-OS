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

仅因领域模块、API、测试或 UI 占位项存在，项目并不视为“可正常使用”。首个可用 Beta 的标准是用户可从
Web UI 完成以下工作流：

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
→ 审阅 Decision Center
→ 在需要时明确批准或拒绝
→ 仅手工执行，并记录执行结果
→ 每日获得 AI 团队的报告、异常和复核提醒
```

产品必须保持下列底线：

- Evidence-first、不可变历史、明确业务时间和可审计性；
- `auto_trade=false`，没有有效人工批准绝不提交实盘订单；
- Risk Veto 阻止 BUY、ADD 和任何增加敞口，CIO/批准不得覆盖；
- Portfolio Manager 输出 `risk_intent`，确定性代码负责仓位规模计算、上限、手数取整和最终数量；
- Learning 只能提出/测试建议，不得激活策略、政策、提示词、阈值、权重或代码变更；
- 模型、网页、新闻、供应商输出和 DSA 输出都是不可信数据，绝不是指令。

## 2. 产品完成术语

### 工程完成（Engineering Done）

代码、测试、迁移、契约和基础设施满足一个工程阶段的验收条件，但用户可能仍无法完成真实的安全工作流。

### 产品完成（Product Done）

典型非开发者可以在受支持环境中完成真实但受治理约束的任务；UI 如实展示配置状态、数据来源、失败和
不可用能力，不要求内部脚本或直接数据库操作。

工程完成不等于产品完成。每个产品阶段都必须记录两者的证据和剩余人工决定。

## 3. 目标产品界面

产品应有以下顶层界面：设置、Portfolio、Watchlist/Opportunities、Analysis Runs、Decision Center、
Daily Reports、Review、Operations 和审计 Journal。所有页面必须标明数据 as-of、来源/新鲜度、模拟/实盘
状态、Risk Veto、待批准项和运行异常。未实现能力必须明确标为不可用，不能用合成卡片伪装为真实状态。

## 4. 首次运行 Setup Wizard

首次打开时，用户按顺序完成市场和资产范围、模型供应商、Agent/模型分配、数据/研究供应商、Portfolio、
Watchlist、Investment Policy 审阅和 Initial Analysis 就绪检查。向导可保存进度、可安全返回上一步，
但不能静默使用默认真实投资参数或密钥。

### 第 1 步 — 市场和资产范围

选择获支持且已授权的市场、货币、时区、交易日历和资产类别。日历会话、收盘时间和数据源必须是显式
配置；不得由服务器时钟、工作日或推测推断。真实市场/数据授权仍需人工决定。

### 第 2 步 — 模型供应商

供应商配置显示名称、模型、区域、可用性、预算和状态，但密钥只能写入经审查的 SecretStore。连接测试
必须为显式、经审计的最小请求；不得在日志、UI、事件、异常或 Agent 记录中泄露密钥。未经人工授权的
供应商不可启用。

### 第 3 步 — Agent/模型分配

为固定角色分配已授权模型与提示词包版本：Macro、Industry、Fundamental、Market/Quant、Event、
Devil's Advocate 和 CIO。角色权限、工具允许列表、预算、超时与降级规则是版本化配置；外部文本和
模型回复不能改变它们。

### 第 4 步 — 数据/研究供应商

记录供应商授权、许可、市场覆盖、数据延迟、来源层级、独立性和健康状态。所有采集结果需规范化为
Evidence，并保留 observed/effective/available/ingested 时间；不可用、陈旧、许可不清或不合格数据必须
显式失败，不能伪造结论。

### 第 5 步 — Portfolio 引导

导入或手工录入真实个人 Portfolio 的持仓、现金、成本、Core/Tactical 手数和 as-of；在提交前显示验证、
重复、缺失价格、货币、手数和风险提示。导入必须产生不可变快照和审计记录，不能覆盖历史或通过 UI
绕过 Policy/风险关卡。

### 第 6 步 — Watchlist

用户可创建、编辑和归档受审计 Watchlist 项，指定标的、市场、类别、初始 thesis 问题和复核频率。发现
机会并不等同于推荐或订单；无有效 Evidence 的项目必须明确为待研究。

### 第 7 步 — Investment Policy 审阅

展示已版本化 Policy、所有限制、风险预算、现金要求、Core/Tactical 边界、批准 TTL 和适用范围。真实数值
只能由人工选择、验证并批准后生效；`TEST_DEFAULT` 只能用于工程测试，不能伪装为真实 policy。

### 第 8 步 — Initial Analysis

只有前置配置和数据可用性满足时才可启动。系统创建明确的 AnalysisRun，冻结输入上下文，执行有限两轮
委员会、Risk、portfolio-fit 和确定性仓位规模计算，随后生成 Decision 或明确失败；没有任何隐式批准或
实盘执行。

## 5. 模型集成契约

### 5.1 架构

所有模型调用经 `LLMGatewayPort`、版本化严格 DTO、角色注册和提示词包。域层不依赖供应商 SDK。请求和
响应有关联 ID、版本、哈希、预算、超时、用量和经清洗的输出引用；自由格式文本绝不直接成为 AgentOpinion。

### 5.2 强制运行时行为

模式无效输出最多有限修复次数，之后为 `INSUFFICIENT_DATA`；事实观察必须引用冻结上下文中可见的
Evidence；模型错误、超时、成本超限、模式漂移和缺失数据均显式记录。委员会最多两轮，始终包含
Devil's Advocate，且保留异议。

### 5.3 故障转移

故障转移只能发生在已授权的供应商/模型配置间，保留原请求语义、预算和审计来源。不得把失败替换为
未经验证的散文、静默较低质量模型或高置信度结论。

### 5.4 成本控制

为供应商、角色、运行和期间设置显式预算、token 上限、超时和并发限制。超过限制即失败闭合；成本记录
不含提示词原文、密钥或个人数据。

## 6. 密钥处理

密钥只能由专门的、经过审查的 SecretStore 管理，采用最小权限、加密静态存储、轮换、撤销和审计。配置
读取接口不得返回明文；日志、错误、浏览器本地存储、截图、测试夹具、事件和 outbox 均不得出现密钥。
PRODUCT-01 不收集密钥；SecretStore 路径须在后续 ADR/阶段中实现和验证。

## 7. Portfolio 产品契约

Portfolio 展示不可变快照、Core/Tactical 分离、现金、价格/货币 as-of、待处理容量和数据质量。导入、
更正和删除采用追加版本/明确撤销而非原地改写。用户看到的目标、数量和限制必须来自确定性代码；UI 不得
计算或替换 Risk Veto、Policy 上限、手数取整或最终数量。

## 8. Watchlist 和机会发现

### Watchlist

Watchlist 维护用户意图、标的标识、研究状态、复核时间、证据覆盖和归档历史。它不授予交易权限，也不把
研究缺口隐藏为可操作建议。

### Opportunities

机会发现只能产生带来源、时间、筛选条件和不确定性的候选项。候选项要进入 Decision 路径，必须经过
Evidence、Thesis、委员会、Risk、Portfolio 和批准关卡；不得由排名、热度或模型文本直接形成买入。

## 9. 运行时 Analysis Orchestrator

编排器从明确用户动作或显式日历任务启动，创建可重放 AnalysisRun 和冻结 `AnalysisContext`，并顺序连接
Evidence 可用性检查、独立角色、两轮委员会、Thesis、Risk、portfolio-fit、确定性仓位规模计算和 CIO。
每个步骤必须记录输入/输出版本、哈希、时间、失败和关联 ID。失败不会自动跳过、重试为不同业务输入或
创建 Decision/批准/订单。

## 10. AnalysisRun

AnalysisRun 是不可变且可审计的运行容器，至少记录触发者、原因、业务时间、市场日历、输入快照、
Evidence 可见性、角色/提示词/模型版本、预算、状态、失败、关联 ID 和产物引用。重试须遵循幂等键和
明确恢复策略；新数据、价格或 policy 变化不得与旧运行混合。

## 11. 决策中心（Decision Center）

Decision Center 显示完整 Decision Journal：Evidence、Thesis、Agent 观点、异议、Risk 结果、
Portfolio-fit、仓位规模计算、Core/Tactical 动作、未知项、条件、复核计划和批准状态。它必须区分研究
建议、待批准决定、模拟记录、手工执行记录和实盘交易（V1 始终不可用）；不得用摘要掩盖 Veto 或失败。

## 12. 人工批准和手工执行

具名人工动作 `APPROVE`、`REJECT`、`REVOKE` 只追加并受 Policy TTL、输入/价格漂移和状态约束。只有
当前有效批准可关联模拟或手工执行回执；撤销、到期、Veto 或输入漂移阻止增加风险。V1 实盘适配器必须
拒绝每个请求，手工执行只是记录外部人工行为，不能成为经纪商下单通道。

## 13. 调度器和 worker 运行时

Daily/Weekly/Monthly/Quarterly 任务要求明确市场时区、日历会话、`as_of`、幂等键、咨询锁、持久 TaskRun
和事务性 outbox。默认环境不推断会话；重放只读取截至业务时间可用的输入。失败、重试耗尽和异常必须在
Operations/UI 中可见，且调度器不能绕过 Risk Veto、批准或禁用实盘执行。

## 14. Dashboard 契约

Dashboard 是只读操作面，展示 Portfolio、Decision、Watchlist、报告、数据新鲜度、任务健康、异常和待办。
每个数值显示来源和 as-of；没有数据或数据陈旧时显示明确的无动作状态。不得把合成或占位数据标为真实。

## 15. 报告

日、周、月报告明确区分事实、确定性计算、Agent 判断、假设和人工决定，保留来源引用和时间。固定模拟/
禁止自动交易标记必须显著；报告只表达建议与状态，不能创建、批准或执行订单。

## 16. Beta 所需 API 表面

### Providers / Settings

配置读取/更新、密钥状态、供应商连接测试、模型/角色分配、市场日历和 policy 审阅 API 必须有带版本 DTO、
认证/授权、审计、输入验证和经清洗错误；密钥明文永不返回。

### Portfolio / Watchlist

提供 Portfolio 快照读取、导入预览/提交、错误报告、Watchlist 生命周期和 Opportunities 查询。所有修改
必须走类型化应用边界并留下不可变历史。

### Analysis

提供 Initial Analysis 启动、AnalysisRun 状态、产物读取和失败/重试可见性。启动需要明确权限和冻结输入，
不接受自由文本覆盖治理。

### Decisions

提供 Decision Journal、`APPROVE`/`REJECT`/`REVOKE`、模拟/手工执行记录和复核读取。任何实盘订单端点
在 V1 均不存在或明确拒绝。

### Reports / Operations

提供报告、TaskRuns、运行异常、健康、数据新鲜度、outbox/投递状态和支持信息的只读接口。管理任务运行
必须要求明确 `as_of` 和 `dry_run`，并保留锁与幂等语义。

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

每个阶段须遵循 Master Spec、ADR、活动阶段契约和 `AGENTS.md`：行为需要正常/失败/边界测试；模式和
OpenAPI 漂移必须检查；迁移需升级与恢复方案；数据、密钥和日志需安全审查；不可变历史、Evidence、
Risk Veto、人工批准与确定性仓位规模计算必须有具名不变量测试。产品 UI 不是绕过应用端口或领域规则的
便利层。

## 19. 仍在 Codex 权限之外的人工治理决定

真实 Investment Policy 限制、供应商/数据许可和授权、市场/资产范围、模型/预算、数据保留、真实
Portfolio、经纪商集成、实盘执行、策略激活以及任何降低风险/证据/批准/不可变性要求的变化，均需明确
人工决定与适当 ADR。Codex 可以实现已授权边界，不能替所有者作出这些决定。

## 20. 产品化成功声明

当首个 Beta 的用户可在不接触内部实现细节的前提下安全完成研究、Portfolio、分析、Decision、人工批准、
手工执行记录、报告和复核闭环，且每一步均保持 Evidence、不可变历史、确定性风险/仓位规模计算和
`auto_trade=false` 时，产品化才算成功。
