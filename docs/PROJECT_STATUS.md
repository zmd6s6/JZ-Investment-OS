# 项目状态

> 这是唯一的当前状态记录。推进阶段时必须在同一变更中更新它。

## 当前快照

- 项目：Personal AI Investment OS
- 当前模式：`DEVELOPMENT`
- 活跃 Release：`MVP-BETA`
- Integration branch：`release/mvp-beta`
- 当前里程碑：P5 可见验收收口；P6/P8 无真实依赖 Work Item 允许并行推进
- 阶段状态：`PRODUCT-05 = IN_PROGRESS`（PR #17 已合并，等待所有者可见产品验收）
- 实盘交易：`FORBIDDEN`
- 权威规范：`INVESTMENT_OS_MASTER_SPEC.md`
- 自治控制面：`docs/agent/RELEASE.md` + `docs/agent/WORK_QUEUE.yaml`
- 上次状态更新：`2026-10-28`

## 已建立

- MVP-402本工作分支已接通有限本地范围、人工自然年年报事实、确定性四指标与有界候选 / 历史页面；本切片真实UI / API / DB合成验证21场景通过，但整体能力PARTIAL：全市场、深研、周定时尚未提供，不代表完整402 / P8或Owner接受。记录随本PR合入Release生效，详见 `docs/agent/work-items/MVP-402.md`。

- MVP-202已实现并验证只读 `/valuation` 参考估值与对账：冻结P5现金/分仓，追溯人工报价Evidence，缺价/FX阻断完整NAV；Sizing缺项可见且不生成建议数量。实现时Windows后端458/85.42%、集成45、前端53与完整浏览器21项通过；主代理独立复验32项unit/PG与3项真实浏览器通过。已安全同步PR #23后的Release，合并代码重跑486/85.94%、集成58、前端62、真实浏览器22项通过；INTEGRATED及MVP-203 READY仅随PR #24合入Release生效，最终CI/Gate由独立方核对；未完成P6或Owner验收，实际证据见 `docs/agent/work-items/MVP-202.md`。

- MVP-401=INTEGRATED，此记录随PR #23通过最终独立Gate合入Release生效。`/calendar`提供有来源与市场时区的CSV预览 / 持久化导入、新版本默认暂停、STATUS_ONLY独立启停与真实Worker日历状态报告。91801d0由root独立复跑日历四文件28/28（8.75秒）、真实恢复浏览器1/1（15.7秒），覆盖失败换源恢复和两种并发交错；旧c0ad765独立25/2只归属旧实现。91801d0六CI绿、Linux454 / 85.50%及集成51是该精确提交的工程证据，最终合入按PR当前HEAD核验。Owner部署 / 验收PENDING；不调用付费模型或真实来源，不含团队分析，完整P8仍PLANNED。详细边界见 `docs/agent/work-items/MVP-401.md`。
- MVP-201已由PR #22通过独立Gate合入Release：人工行情 typed port、同事务持久化与 `/market-data` 中文录入 / 来源追溯 / 刷新路径；CNY单币种、缺FX失败关闭。Owner部署与Checkpoint人工验收PENDING；人工数据不等于已核实市场事实，完整P6仍未完成。真实验证及限制见 `docs/agent/work-items/MVP-201.md`。

- MVP-101已由PR #21通过独立Gate合入Release。独立复验捕获的现金草稿迟到覆盖已补6项修前失败测试，前端34/34、浏览器15/15；root独立现金 / 预览 / 反馈16/16、本项浏览器7/7通过。组合 / 分仓成本 / 现金 / CSV对账刷新、跨组合迟到响应、目录Watchlist与实际政策只读审阅均有合成浏览器证据。Owner验收仍PENDING、P5仍IN_PROGRESS。详见 `docs/agent/work-items/MVP-101.md`。
- MVP-000已由PR #20合入Release：`/acceptance`与只读交付清单API区分工程、集成证据、服务装配及待人工验收；提供实际入口、操作 / 失败指引，未实现功能不链接至假入口。未部署所有者实例，不表示Checkpoint接受；验证与限制见 `docs/agent/work-items/MVP-000.md`。
- 主工程规范、根工作约定、持续工作模式以及 ADR/阶段文档约定均已建立。
- Python 3.12 项目元数据、锁文件、健康检查、Compose、CI、OpenAPI、依赖/许可证检查与密钥扫描已具备。
- ADR-0001 至 ADR-0016 已被接受；其中明确了模块化单体边界、DSA Adapter、多提供方研究运行时、证据与时间语义、双轮委员会、风险否决、确定性仓位、学习治理、调度锁与 Outbox、安全、纯领域内核及显式多市场日历语义。
- 纯领域值对象、投资政策、Instrument/Thesis/Decision/Strategy 状态机，以及 Core/Tactical、风险否决、人类审批和学习权限不变量已实现并以失败关闭方式保护。
- 数据库迁移、乐观版本控制、审计/事件历史、不可变工件守卫、工作单元、事务 Outbox、咨询锁和幂等 TaskRun 已验证。
- PR-01 至 PR-07 已合并到 `main`；各自的合并提交记录仍保留在 Git 历史。
- PR-08 已由 PR #8 合并到 `main`，合并提交为 `9e3dad77142336918b24849b99cdadd1068effb8`。它交付了只支持显式合成日历的运行时调度、持久化 TaskRun、事务 Outbox 与仅模拟的报告；默认 Compose 环境不启用日历。
- PRODUCT-01 已完成首次启动引导状态、服务端能力矩阵、设置向导 UI、独立 PR-08 合成演示路由以及单元/集成/浏览器 E2E 验证。引导 HTTP 接口通过应用层用例访问持久化端口；模型与数据提供方在 PRODUCT-02 前如实标为 `NOT_IMPLEMENTED`。该状态不保存凭据、真实组合或投资政策数值。

## 尚未实现或尚未验证

- P5的PR #17已合并，MVP-101可见路径复验与修复已由PR #21合入Release；仍须所有者本人Checkpoint验收，才能将PRODUCT-05标为ACCEPTED。
- P6：产品工作流中的端到端分析编排、持久化 AnalysisRun 以及完整 Evidence → Decision 影子链路。
- P7：Decision 审阅、批准/拒绝/撤销 UI 与只记录事实的手工执行产品流。
- P8：用户可见的日/周/月 AI 团队定时运行、机会筛选、Portfolio 复核及报告。
- P9：按 Beta 验收门槛完成的端到端产品验证和所有者接受。
- PR-09 的 Outcome、Review/Learning、发布加固与发布验证必须在 P9 接受后才可恢复；在此之前不得继续推进或视为发布依据。
- 除已实现的 PR-07 S10 和 PR-08 调度重放/幂等性切片以外的完整验收场景覆盖。

不得仅因为主规范存在就推断以上项目已经完成。

## 当前授权工作

所有者于 2026-10-26 授权切换到 `MVP-BETA` Release Train：允许多个开发 Agent 对无真实依赖的 Work Item 并行自治开发；Gatekeeper 在 CI、治理、不变量、文档真实性和可见验收门禁全部满足后可自动合并到 `release/mvp-beta`。所有者不再逐 PR 驱动，只在治理决定和 Checkpoint 上参与。

PRODUCT-05（`IN_PROGRESS`）已覆盖 Instrument 目录、Portfolio 手工/CSV、Watchlist、Policy 只读审阅与产品页。PR #17 已于 2026-10-10 合并到 `main`；当前缺口是所有者可见验收与状态收口，而不是再次开发同一大阶段。
2026-09-29 收口：隔离库集成 3 项、浏览器 E2E 4 项、单元+集成 310 项、`ruff`/`mypy src`、OpenAPI check 通过；
迁移 `20260929_0011`。`detect-secrets` 本机未安装标 `NOT VERIFIED`；`docker-compose config` 通过。待所有者验收后
方可 `READY_FOR_REVIEW`。

PRODUCT-01 已由 PR #12 合并到 `main`。PRODUCT-02 已由 PR #13 合并到 `main`，并且 ADR-0013
已由所有者于 2026-09-22 接受。PRODUCT-03 已由 PR #14 合并到 `main`（合并提交
`6753da5`）：它交付 OpenAI-compatible 模型网关、显式连接测试、角色分配、超时/Token 上限、
预算失败关闭和完整 AgentOpinion 验收，不选择或自动启用任何真实提供方，也不执行任何交易。
DeepSeek V4.1 Flash 已获所有者授权进行一次最小真实网络验收。所有者录入的定价、测试预算和凭据均只存在于
本地运行时配置；2026-09-22 已在无真实 Evidence、Portfolio 或交易数据的连接测试中验证认证、HTTPS 调用、预算
预留、可验证用量结算和 JSON 对象输出。同日又以合成 Evidence 完成真实模型的完整
`OpenAICompatibleLLMGateway → AgentRuntime → 严格 AgentOpinion → Evidence 引用校验` 路径：无修复成功，
用量为 425 输入 / 452 输出 Token，脱敏成本为 USD 0.0006699。该验证不构成分析编排、真实投资数据或任何交易行为的授权。
PRODUCT-04 已由 PR #15 合并到 `main`（`ba9b4fa`）：它完成了多提供方显式 registry、博查 Web Search 基础设施适配器、
受限连接测试、统一 DTO 和显式 Evidence 摄取 API 的合成验证。设置 API/UI 可显示每个数据档案最近一次
显式连接测试及最近成功同步的无凭据状态、时间、数量和延迟。所有者已选择博查并在本地保存加密凭据引用；
该档案保持禁用。2026-09-22 经所有者明确授权，以固定无敏感测试词完成一次最小真实连接验证（HTTP 200、
供应商 code 200、1 条结果、约 1.28 秒），未保存搜索正文或创建 Evidence。所有者现已确认博查可用于
个人投资研究、结果保留 365 天，以及首次公开查询“宁德时代 最新公告”（最多 5 条）。重新保存档案后，
该查询已于 2026-09-23 成功写入 5 条新的不可信搜索 Evidence，连接测试约 634ms，且档案随后恢复禁用；
未启动分析、决策或交易。该批次的来源发布时间存在较早记录，不能据此宣称“最新”；既有不可变 Evidence 不会
被原地改写。ADR-0016 与前向迁移已
交付 365 天档案配置、未来到期时间映射及 API SecretStore 命名卷；当前本地容器尚未重建迁移，以保护现有凭据。

2026-09-29，所有者重新确认产品执行顺序：P4 已接受，必须先完成并接受 P5、P6、P7、P8、P9，之后才可恢复
PR-09。因此产品路线图要求 P5–P9 先于 PR-09；当前活跃实现阶段为 `PRODUCT-05`（`IN_PROGRESS`）。任何尚未合并的 PR-09 预研不属于 `main` 的
已接受交付，不能作为当前活动阶段、可用 Beta 或发布就绪声明。

## 已记录的范围决定

- 发布的政策为 `TEST_DEFAULT`；选择真实限额仍需人工明确决定。
- A 股范围仅授权 SSE/SZSE 日历语义和合成研究/模拟夹具，不授权数据提供方、真实 A 股组合数据、政策限额、券商执行或实盘交易。
- 所有者已授权当前 Beta Release Train 的多 Agent 并行开发与独立 Gatekeeper 自动合并到 `release/mvp-beta`；直接更新 `main` 仍通过 Release Checkpoint PR。
- 业务 Work Item 必须达到 Engineering Done + Integrated Done + User Visible Done，才能在 Checkpoint 后标记 DONE。

## 路线图

| 阶段 | 状态 | 人工验收 | 说明 |
|---|---|---|---|
| PR-00 | ACCEPTED | 已合并到 `main` | 基础工程工作已交付并接受 |
| PR-01 | ACCEPTED | 已合并到 `main` | 2026-09-17 |
| PR-02 | ACCEPTED | 已合并到 `main` | 2026-09-18 |
| PR-03 | ACCEPTED | 已合并到 `main` | 2026-09-18 |
| PR-04 | ACCEPTED | 已合并到 `main` | 2026-09-19 |
| PR-05 | ACCEPTED | 已合并到 `main` | 2026-09-20 |
| PR-06 | ACCEPTED | 已合并到 `main` | 2026-09-20 |
| PR-07 | ACCEPTED | 已合并到 `main` | 2026-09-20 |
| PR-08 | ACCEPTED | 已合并到 `main` | 调度、报告和只读技术基础；产品闭环由 P5–P9 继续推进 |
| PRODUCT-01 | ACCEPTED | 已由 PR #12 合并到 `main` | 首次引导与产品状态 |
| PRODUCT-02 | ACCEPTED | PR #13 已合并；ADR-0013 已接受 | 设置、密钥存储与提供方档案 |
| PRODUCT-03 | ACCEPTED | 已由 PR #14 合并；MockTransport、隔离浏览器及已授权 DeepSeek 的合成 Evidence 真实网络验收均通过 | 真实模型运行时 |
| PRODUCT-04 | ACCEPTED | 已由 PR #15 合并到 `main`（`ba9b4fa`） | 多提供方数据运行时 |
| PRODUCT-05 | IN_PROGRESS | PR #17 已合并；等待浏览器可见验收 | Portfolio 与 Watchlist 产品 |
| PRODUCT-06 | PLANNED | 里程碑接受依赖 P5；独立 Work Item 可并行 | 端到端 Analysis Orchestration |
| PRODUCT-07 | PLANNED | 里程碑接受依赖 P6；独立 UI/契约工作可并行 | 交互式决策与批准 |
| PRODUCT-08 | PLANNED | 里程碑接受依赖 P7；Calendar 等独立 Work Item 可并行 | 每日 AI 团队运行时 |
| PRODUCT-09 | PLANNED | 依赖 PRODUCT-08 `ACCEPTED` | Beta 验收 |
| PR-09 | BLOCKED | 解除条件：PRODUCT-09 经所有者 `ACCEPTED`，且所有者明确要求恢复 | Outcome、Review/Learning、加固与发布 |

## 状态更新规则

- 未记录验证证据时，禁止将阶段标为 `READY_FOR_REVIEW`。
- 需要人工治理审查的阶段不得由 Codex 单方面标为 `ACCEPTED`。
- 阻塞项必须记录负责人、精确条件、已尝试替代方案和解除事件。PR-09 的负责人为所有者；精确解除条件为
  PRODUCT-09 `ACCEPTED` 与所有者明确恢复指令；已采取的替代方案是转而推进 P5–P9。
- 详细清单与证据放在对应阶段文档；本文件保持简明。
- 阶段 ACCEPTED 顺序保持 P5→P9；实现调度改由 Release Work Queue 驱动，无真实依赖的后续阶段 Work Item 不必等待前一阶段整体 ACCEPTED。
