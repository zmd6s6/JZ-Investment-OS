# PRODUCT-06 — 端到端 Analysis Orchestration

- 状态：`IN_PROGRESS`（2026-10-15 整体交互复查更正；聚焦修复可评审，完整页面化证据摄取、逐次来源选择与运行控制尚未满足阶段契约）
- 前置条件：`PRODUCT-05` 已由所有者接受；可用的已授权模型与数据档案、Portfolio/Watchlist 产品流均已验证
- 治理规范：`INVESTMENT_OS_MASTER_SPEC.md` §2、§4、§6、§9、§11、§12、§16 至 §19
- 相关 ADR：`ADR-0002`、`ADR-0003`、`ADR-0004`、`ADR-0005`、`ADR-0006`、`ADR-0007`、`ADR-0010`、
  `ADR-0015`、`ADR-0016`、`ADR-0017`
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

## 实施记录

- 2026-10-15（本机无感授权，所有者明确要求）：
  - ADR-0017 增加本地启动配对 / HttpOnly 会话；原 Bearer 保留 CLI / 显式兼容模式，不再出现在默认日常操作里。
  - Compose API / PostgreSQL 默认绑定 `127.0.0.1`；精确 Host / Origin 与写入自定义头校验，未配对不读取业务 API。
  - 120 秒配对码原子单次消费；30 天会话跨标签页 / API 重启，断开后服务端撤销。独立标准库 SQLite 只存摘要、到期时间与授权事件；无业务数据库迁移。
  - Windows 双击 `打开投资工作台.cmd`；启动器只读取必要的非秘密部署元数据，拒绝全网卡 / 多部署猜选，不显示开发令牌或供应商凭据。
  - 验证：隔离全量 **433 passed / 82.55%**、前端 **43 passed** 与构建、旧浏览器 **13/13**、新增本机会话浏览器 **3/3**；不调用真实提供方。
  - 浏览器验证使用 `E2E_BROWSER_CHANNEL=chrome`；本机会话测试额外指定隔离 `E2E_BASE_URL=18106` 和 `E2E_LOCAL_ACCESS_STORE_PATH`，不对用户认证库签发测试授权。默认 Playwright 浏览器缺失，不新增下载依赖。
  - 18102 已部署，API / PostgreSQL 实际发布地址均为 `127.0.0.1`；保留原凭据与投资数据卷。Computer Use 实测启动器配对、清除地址栏短效码、刷新续用和连接说明，当前浏览器已连接。
  - 正常 / 失败 / 边界覆盖：过期、重复兑换、并发只成功一次、错误 Host / Origin、缺失 CSRF、读取越权、凭据不回显、断开后的旧 Cookie 重放、重启续用。
  - OpenAPI 增加三个 auth 路径及版本化会话响应；无旧业务 API / Agent Schema / 投资规则变更。
  - 回滚：保留回环绑定，显式改回 `bearer` 并重建 API；不删除投资库或提供方凭据卷。本次不构成整个 P6 接受。

- 2026-10-15（整体流程与交互复查）：
  - 复现窄侧栏令牌输入约 30px；改为可聚焦、可回车验证、可关闭的原生模态输入，15 秒超时后恢复操作。
  - 增加全页使用指南、配置顺序、分仓 / 凭据 / Token / 计费信息；反馈不再强制页面跳回顶部。
  - 补观察清单分析入口、显式组合确认和调用说明；分析按钮不再冒泡载入编辑；报告可查看全部组合、名称、完整引用和未知项。
  - 风险否决展示读取实际 Risk gate，不把“未尝试 BUY”误读成“无否决”；缺评估不显示虚假“否”。
  - 视觉和 Grid / 表格响应式调整；390 / 800 / 1280px 授权可操作，主页面窄屏不撑宽。
  - 验证：前端 **38 passed**、构建通过；无需供应商调用的 Chrome 浏览器 **13 passed**；
    另一个隔离库后端最终 **407 passed / 82.50%**；domain 行 **98.06%** / 分支 **88.04%**；
    Ruff、mypy、OpenAPI / Policy Schema、密钥扫描、Compose config 通过。仅更正能力矩阵的陈旧文案；无 API Schema / 迁移 / 投资治理变更。
  - 不继续 P7；剩余产品缺口及验收边界见 `docs/product/UX_REVIEW_2026-10-15.md`，用户操作见 `docs/product/USER_GUIDE.md`。
  - 本轮未跑真实付费模型 / Tushare / FX 验收；回滚仅需撤销 UI 变更并重建，不改既有凭据和数据。

- 2026-10-15（访问授权与交互反馈聚焦修复）：
  - 修正设置页和角色映射 DELETE 绕过统一鉴权的问题；继续使用原有 Bearer 中间件。
  - 新增 `POST /api/v1/auth/check`：只验证既有写入权限，无数据库写入、凭据回显或供应商调用；
    UI 先验证再保存本地令牌，不改变认证模式、安全要求或令牌的会话存储范围，因此不引入新的治理 ADR。
  - 设置保存、连接测试、档案状态与角色映射提供处理中、防重入和结果提示；错误区分 401/403、
    服务端未配置、字段校验、冲突、超时和网络故障。错误不展示原始响应、请求输入或凭据。
  - 报告刷新/读取失败留在当前页，可重试；估值技术 JSON 折叠，缺行情影响用中文解释。
  - 验证：独立数据库 `investment_os_ux_20261015_1009` 全量 pytest **407 passed** / **82.48%**；
    domain 行 **98.06%** / 分支 **88.04%**；前端 Vitest **25 passed** 与生产构建通过；
    `interaction_feedback.spec.ts` **2/2**（本地授权→保存→无供应商凭据提示；报告等待→失败→重试）通过。
  - 浏览器命令：配置隔离 `E2E_BASE_URL`、合成 `INVESTMENT_OS_API_WRITE_TOKEN` 和
    `E2E_BROWSER_CHANNEL=chrome`，执行 `npm run test:e2e -- interaction_feedback.spec.ts --workers=1`。
    默认 Playwright 浏览器在本机缺失，使用已安装 Chrome 验证；未新增浏览器或生产依赖。
  - 本轮未重跑调用真实模型的旧分析 E2E，不使用任何真实供应商凭据。
  - 回滚：撤销本聚焦修复后重新构建；无数据库迁移，无需更换或删除凭据、访问令牌和既有记录。

- 2026-10-10（首个可用纵切）：
  - `AnalysisRun` 持久化（迁移 `20261010_0015`）、`InvestmentAnalysisOrchestrator` 通过既有委员会/Agent/CIO 门执行；
    无 Evidence 失败关闭；跨币种缺 FX 失败关闭；缺行情显式 `MISSING_REFERENCE_QUOTES`。
  - MarketDataPort + 合成/内存适配器；确定性 NAV/估值字段与 `TEST_DEFAULT` 固定 policy_version_label。
  - API：`POST/GET /api/v1/analysis-runs`；UI：`/analysis` 运行列表与详情、组合持仓「立即分析」。
  - 验证：`tests.unit 327`（含编排 2 项）、`ruff`/`mypy`、`npm run build`、前端 7/7、OpenAPI、迁移+P5 集成 6 项通过。
  - **NOT VERIFIED**：浏览器 E2E、真实模型网络调用、密钥扫描、完整 pytest 中与分析无关的旧集成在本环境未全部重跑。
- 2026-10-10（续）：
  - Tushare Decimal 报价解析；行情链每次请求重读启用档案；Agent 注入证据/持仓/第二轮意见。
  - 缺估值/仓位与 Risk 失败时禁止 BUY；TEST_DEFAULT 不允许新暴露；列表无 portfolio 时返回最近全部。
  - RUNNING→终态状态流转；ACTIVE 政策标签从库读取；Tushare 连接测试 + 复合数据测试器。
  - 验证：`tests.unit 338`、`mypy`、`ruff`、OpenAPI、前端构建通过。
- 2026-10-14（真实模型全链路与浏览器验收）：
  - **提示词根因修复**：system 指令原只提 “AgentOpinion schema 1.0” 名称不含 Schema 本体，
    deepseek-chat 自创包裹结构致 8/8 `INVALID_OUTPUT`；补内嵌主规范 §6.2 完整契约 +
    `INSUFFICIENT_DATA ⇔ 空 observations 且 confidence=0` 互斥规则；prompt bundle `p6-v1`→`p6-v3`；
    具名回归测试 `test_agent_prompt_embeds_full_agentopinion_contract`。
  - **真实 DeepSeek 全链路（隔离栈 18102）**：连接测试 734ms；真实运行 8/8 角色零修复通过
    （7 POSITIVE + DA NEUTRAL，带证据引用 claims）；Risk 2 个 HARD 旗 → VETO → CIO RISK 门 FAIL；
    TEST_DEFAULT 政策门 FAIL；缺行情 `MISSING_REFERENCE_QUOTES` → 禁 BUY → 最终 WATCH；
    估值显式 `PARTIAL/missing_quotes`，sizing=None。定价 e2e-v1（USD 0.27/1.10 每百万 Token），
    预算任务 10 万 Token/$0.5、每日 100 万 Token/$3；单次运行约 1.5 万 Token / $0.0066。
  - **浏览器 E2E**：新增 `web/e2e/analysis.spec.ts` 2 项（真实全链路报告 + 无证据失败关闭），
    全套 E2E **8/8 串行通过**（Chrome channel，E2E_BASE_URL=18102）。
  - 验证：`pytest 全量 405 passed / 覆盖率 82.47%`、`ruff format/check`、`mypy src`、
    OpenAPI 与政策 Schema check、`docker compose config`、前端 Vitest 7/7、`npm run build`。
  - **NOT VERIFIED**：`detect-secrets`/`pip-audit` 本机未安装；Tushare Token 未配置，
    带真实 A 股行情与确定性仓位输出的估值验收待所有者录入 Token 后补跑。
  - 验收栈：`docker-compose -p investment-os-p6-browser-test`（API 18102 / PG 15433，迁移到 0015）。
