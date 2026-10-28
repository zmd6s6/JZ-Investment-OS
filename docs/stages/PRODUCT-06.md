# PRODUCT-06 — 端到端 Analysis Orchestration

- 状态：`PLANNED`
- 前置条件：`PRODUCT-05` 已由所有者接受；可用的已授权模型与数据档案、Portfolio/Watchlist 产品流均已验证
- 治理规范：`INVESTMENT_OS_MASTER_SPEC.md` §2、§4、§6、§9、§11、§12、§16 至 §19
- 相关 ADR：`ADR-0002`、`ADR-0003`、`ADR-0004`、`ADR-0005`、`ADR-0006`、`ADR-0007`、`ADR-0010`、
  `ADR-0015`、`ADR-0016`
- 安全基线：`auto_trade=false`；外部研究和模型输出均不可信；结果仅为影子 Decision

## 目标

让所有者能从 Portfolio 或 Watchlist 中选择一个标的，通过 UI 显式选择已启用的模型/数据档案并启动一次分析；系统以
持久化 `AnalysisRun` 展示排队、运行、成功、降级或失败，完整保留 Evidence → Features → Thesis → 两轮委员会
→ Risk → 确定性仓位规模计算 → Decision 的可追溯链路。

## 范围

1. 版本化、可审计的 `AnalysisRun` 状态机、请求快照、输入档案、as-of、预算、失败原因和关联标识。
2. `InvestmentAnalysisOrchestrator` 通过现有 application ports 编排研究、Evidence、Agent、Risk 和 Decision；
   domain 不依赖 API、供应商、LLM、调度器或 UI。
3. **结构化市场数据端口**：可替换的 market-data port/adapter（或明确列出的 DSA 受支持能力），至少覆盖
   reference price、instrument universe、sector/classification，以及本阶段/P8 实际使用的确定性特征输入。
   Instrument 身份/目录/搜索已在 P5 交付，本阶段扩展 quote/valuation/features，不重复或推迟目录能力。
   仅有博查 Web Search 文本检索不能冒充行情或证券全集；缺失必须失败关闭并显式标注。
4. **FX 与多币种估值契约**：跨币种 Portfolio 必须引入带 `as-of`/来源的 FX rate 输入与确定性换算；缺失或陈旧
   FX 失败关闭，禁止用默认汇率或 LLM 估算。首个 Beta 若只使用单币种 Portfolio，仍须显式记录该限制，并保证
   一旦出现异币种持仓/现金即失败关闭或要求配置 FX 源。
5. **确定性估值与 Sizing 上下文构建**：在进入 Risk/仓位引擎前生成带 `as-of`/来源的 reference price、NAV、
   weights、sector/gross exposure、volatility/liquidity 等 `SizingRequest` 所需输入，并与 P5 的 cash/base
   currency/持仓快照精确对账（含 FX 换算路径）。LLM 不得估算这些数值。
6. **Policy 版本固定**：AnalysisRun 与由此产生的 Decision 必须固定引用具体 `policy_version`（与 P5 审阅面
   展示的 active version 一致）；禁止使用“当前 Policy”漂移引用。真实限额数值仍不在本阶段选择或修改。
7. UI 中的立即分析、进度/失败展示、取消/重试的明确边界，以及从 Run 到只读 Decision 详情的导航。
8. 多数据源只能显式选择：记录实际 provider、查询、顺序、结果、失败和新鲜度；禁止按故障、成本或缺数据静默回退。
9. 对没有可用 Evidence、陈旧/冲突数据、无 FX/估值输入、模型输出无效、预算耗尽、供应商故障和 Risk Veto 的
   失败关闭展示。

## 不变量与范围外事项

- 每个事实性 Agent 主张必须引用有效 `evidence_id`；无效结构化输出不得静默降级为自由文本。
- Committee 最多两轮，保留 Devil's Advocate；LLM 只能解释和输出受约束结构，Features/Risk/仓位计算由确定性代码完成。
- Risk Veto 阻断 BUY、ADD 及任何增加暴露的结果；CIO 不得覆盖。
- Run 不得自动启用供应商、修改 Policy/Strategy、批准 Decision、记录执行或提交任何订单。
- 估值/特征输入必须可追溯到确定性计算或已校验数据源，并带业务时间；禁止前视（`available_at` 约束）。
- 本阶段不得把供应商连接测试或单次检索冒充完整分析；不得将 DSA 或任一提供方作为 Portfolio、Decision 或风险状态的
  权威来源。

## 人工边界

实际研究调用只能使用所有者已启用并授权的 provider profile，且遵守其市场、查询、保留和成本边界。若阶段开始时缺少
可调用的已授权模型或数据档案，先使用合成夹具完成工程验证，不得擅自发起真实网络调用。所有者无需在此阶段批准
任何投资结论；批准仍属于 P7。

## 验收标准

1. 用户可仅通过 UI 对已选 Portfolio/Watchlist 标的启动、跟踪并阅读一次真实应用分析运行；不需要 CLI 或手工 API。
2. 每次 Run 能回溯到明确的 provider/model profile、输入、Evidence、业务时间、Agent opinions、Risk、确定性
   仓位规模结果及 Decision；未知或失败信息显式保留。
3. Risk/Sizing 输入完整：reference price、NAV、weights、exposure、volatility/liquidity 等均可追溯到
   确定性 valuation/context builder 与 P5 快照对账；跨币种路径使用带 as-of/source 的 FX 与确定性换算，
   缺失/陈旧 FX 失败关闭；禁止空值通过。
4. 每次 AnalysisRun/Decision 显示并固定 `policy_version`；与 P5 审阅面一致，无漂移。
5. 未授权/禁用 profile、无 Evidence、无行情/universe/FX、超时、Schema 漂移、无效 Agent 输出、预算失败和 Veto
   都失败关闭且可见。
6. 不存在静默数据源回退、自动 Policy/Strategy 变更、自动批准或任何真实/模拟订单提交路径。
7. 正常、失败、边界、多源选择、FX/估值上下文、Policy 版本固定与 UI 进度路径具备单元、契约、集成、迁移和
   浏览器 E2E 证据。

## 完成前验证

运行受影响的格式、lint、类型、单元/属性/契约/集成/迁移、API/OpenAPI、前端构建和浏览器 E2E；真实网络验证仅在
所有者已明确授权的 profile 上进行，并记录脱敏结果。完成定义和证据齐备后方可 `READY_FOR_REVIEW`。

## MVP-202 参考估值纵切（2026-10-27）

工作分支已接通 `/valuation` 的当前账本冻结输入→显式来源参考价→Decimal分仓/NAV/权重/行业与总净暴露→来源与缺Sizing输入展示。人工数据仍非交易级；缺历史波动/流动性/Policy等保持失败关闭，不生成建议数量或完整分析。P6状态与Owner接受未改变。当前实测与未验证项见 `docs/agent/work-items/MVP-202.md`，不将此切片冒充完整P6。


## 独立复核与合入生效台账（2026-10-27）

主代理已对实现提交36e8c76独立复跑unit+真实PG 32/32（6.33秒）和本项真实浏览器3/3（6.8秒），读取ADR0039、领域/应用/SQL/API/UI未提出新源码阻塞。此为实际独立复核记录，不由实现者宣布Gate通过。

评论 https://github.com/zmd6s6/JZ-Investment-OS/pull/24#issuecomment-6440891519 提出的Release台账项已准备修正，状态fixed-awaiting-review：MVP-202 INTEGRATED与MVP-203 READY仅在本PR #24合入Release后生效；MVP-204/301继续依赖203，Owner PENDING、P6未完成、全部Sizing缺项保持。不能在未合入时将此分支队列当成已接受产品。

当时按root要求等待PR #23合入后安全merge Release，保留日历/行情/估值公共接线，再生成OpenAPI、运行受影响验证及新HEAD CI。此处台账先本地准备，与最终集成一次提交，避免重复元数据CI；不复用36e8c76旧CI作为最终合并依据。


## 最终Release同步与验证（2026-10-27）

PR #23已由root独立Gate合入Release `3e805bac141239b0ae3c02d6aa73a16adefed8c0`。本分支先本地提交条件式台账342b379，再非破坏merge Release形成31e4afa；保留市场/日历/估值三方app/bootstrap/App/nav/Settings/交付清单和精确路由allowlist，重生成OpenAPI。root只读复核合并接线未提出新问题；没有rebase/force或引用未合入能力。

合并代码重新实际验证：Windows全量486 passed / 85.94%（48.99秒），集成58 passed /428 deselected（20.73秒），domain行98.05% /分支87.89%；前端62/62（27.22秒）及build通过。ruff format267/check、mypy95、OpenAPI/PolicySchema检查、Compose config通过。仅重启本项18112并在本项15440 browser合成库升级已合入0015迁移，未操作Owner或其他Agent实例。

合并后真实API/DB/UI串行22/22（29.3秒，无跳过），输出 `.runtime/mvp202-release-merge-browser-20261027`；新增三方交付清单→估值入口 / 设置→日历预览确认 / 实际DB默认暂停并刷新 / 设置→人工行情入口接线用例。该用例不启用日历、不启动Worker或外部调用；401的独立Worker/恢复证据仍归PR #23，不能冒充本轮重新跑过18110限定恢复脚本。源码及输入快照/人工非交易级/Sizing缺口未放松。

评论6440891519的台账修复为fixed-awaiting-review，待root核对最终新HEAD CI后决定Gate；实现者不自宣Gate。MVP-202 INTEGRATED及203 READY仅随PR #24合入Release生效，204/301仍等待203，Owner PENDING/P6未完成。


## MVP-203 持久团队影子分析纵切（2026-10-28）

PR #26提供显式选择/出站同意、持久排队/阶段与角色产物、真实两轮、失败/有界取消/新Run重试和刷新。参考估值沿用202快照，Policy版本明确缺失或固定；Risk UNKNOWN、Sizing BLOCKED，没有建议数量与可审批InvestmentDecision，不构成完整P6或Owner接受。

本项实现者真实浏览器4/4（23.3秒）及CI547/79属于09974bb及相同产品代码树；root另对09974bb独立复跑32/32（14.55秒）、原样真实浏览器4/4（22.9秒），未放宽断言。前文36e8c76的32/3与2081658后的复验均只归MVP-202，不能当作本项独立通过。随后独立源码审查实际复现三项P1；已统一收紧预算最终SQL预留/可选typed冻结hash、模型eligible正文及研究最终factory完整hash，并通过具名修前失败/修后回归。09974bb的32/4不能替代新实现独立复审；新验证见工作项，最终Gate仍由独立方对新HEAD核对。

Queue203 INTEGRATED、204/301 READY仅随PR #26经实际独立Gate且合入Release生效；READY仅表示显式实现依赖满足，不是204深入追溯、可审批Decision或301批准已交付，不提前在未合入基线上领取。P6阶段接受、Checkpoint B与Owner仍PENDING，主规范与治理不变量不变。详细证据及限制见 `docs/agent/work-items/MVP-203.md`。
