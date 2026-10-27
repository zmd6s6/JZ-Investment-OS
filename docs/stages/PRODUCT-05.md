# PRODUCT-05 — Portfolio 与 Watchlist 产品

- 状态：`IN_PROGRESS`
- 前置条件：`PRODUCT-04` 已接受；既有 Portfolio 领域模型、确定性仓位规模计算、Evidence 边界与受支持的 Web UI 基线可用
- 治理规范：`INVESTMENT_OS_MASTER_SPEC.md` §5、§8、§10、§11、§12、§16 至 §19
- 相关 ADR：`ADR-0003`、`ADR-0006`、`ADR-0007`、`ADR-0010`
- 安全基线：`auto_trade=false`；不接入经纪商，不创建 Decision，不执行交易

## 目标

使所有者可以完全通过受支持的 Web UI 创建和维护个人 Portfolio 与 Watchlist：手工录入持仓、预览并确认 CSV
导入、查看对账结果、搜索并规范化标的，以及新增/移除 Watchlist 标的。所有者不需要使用 SQL、原始 JSON、curl
或修改代码。

## 范围

1. 真实应用 API 支撑的 Portfolio 页面与 Watchlist 页面，而非静态或合成卡片。
2. **最小 InstrumentIdentity/Catalog/Search 端口与适配器**（本阶段交付，不隐式依赖 P6）：至少覆盖
   market、symbol、name、asset_type、currency、sector 等身份/分类元数据的搜索、规范化与稳定标识；
   手工录入与 CSV 导入必须引用该目录中的规范标的。P6 只扩展 quote/valuation/features，不回头补目录能力。
3. 手工持仓录入；每笔必须明确 market、symbol、名称、资产类型、币种、数量、平均成本及 Core/Tactical bucket。
4. Portfolio 级基础记账边界：base currency、现金余额（可选手工维护）以及持仓/现金快照边界；为后续估值与
   Sizing 提供可对账原始输入。价格、市值、NAV、波动率与行业暴露仍不在本阶段计算。
5. CSV 导入的格式说明、逐行校验、规范化预览、错误报告和显式确认；预览绝不写入业务历史。
6. 确认后的可审计导入快照、幂等/重复处理、持仓对账结果及失败可见性。
7. Watchlist CRUD；搜索/规范化直接使用本阶段 Instrument catalog 端口（见上），保证 P5 可独立 Product Done。
8. Watchlist 每行在数据可得时必须展示：`lifecycle state`、`Thesis state`、`data freshness`、
   `next monitoring condition`；缺失项显式标注“未提供/未评估”，不得伪造。
9. **只读 Investment Policy 审阅面**：展示当前 active policy version、各限额摘要、`TEST_DEFAULT` 状态与
   显著警告；允许所有者“已阅读/确认查看”，但不修改真实限额、不选择投资政策参数（真实参数仍属所有者治理决定）。
10. 页面显式显示数据的 as-of、可用性和缺失状态；不得伪造市值、收益、机会、Risk Veto 或审批信息。

## 不变量与范围外事项

- Portfolio 写入只能经类型化 application port；历史、导入快照、审计记录和 Outbox 与业务写入同一事务。
- 数量、成本与金额使用 `Decimal`/数据库 `numeric`；Core 与 Tactical 的数量、成本、操作和理由分别保存。
- CSV 预览、无效行、部分失败、重复记录和并发冲突必须显式呈现，不能静默丢弃或覆盖历史。
- 个人持仓及 CSV 不得进入仓库、测试夹具、日志、截图、错误响应或分析上下文；测试仅用合成或明确授权且去标识化数据。
- 本阶段不增加市值/NAV 估值引擎、FX 换算、收益计算、自动分析、机会推荐、Policy 参数选择/修改、风险限额变更、
  Decision、Approval、Execution 或任何经纪商调用；估值、FX 与 Sizing 输入构建归属 P6。
- Instrument 目录/搜索/规范化**必须在本阶段可运行**；若只能手工录入而无目录/搜索，则 P5 不能标为 Product Done
  （或必须经所有者明确把搜索验收改划到 P6 并收缩本阶段范围）。
- 本地单用户写鉴权若已在部署中可用则保持有效；完整认证/授权、CSRF 与外网加固不是本阶段功能阻塞项，归后续
  hardening/PR-09。

## 人工边界

所有者在实际使用时自行决定录入方式和个人持仓内容；系统不替所有者选择 Investment Policy 或投资动作。若实现需要
新增真实数据源、处理未获授权的个人数据存储边界或改变真实投资规则，必须先停止并请求明确决定。

## 验收标准

1. 所有者可仅通过 UI 创建/选择 Portfolio，手工录入持仓（含 base currency / 现金边界），并在刷新后查看可追溯结果。
2. CSV 可先预览；规范化、无效行和冲突均可见；只有明确确认后才写入，且确认后可对账。
3. Instrument 搜索/规范化端口在本阶段可用；Watchlist 添加与持仓录入均经该目录规范化，UI/API/E2E 有证据。
4. Watchlist 页面在数据可得时展示 lifecycle state、Thesis state、data freshness、next monitoring condition，
   并通过 UI/API/E2E 验证；缺失时显示显式空状态而非占位假数据。
5. 所有者可在 UI 查看 active policy version、限额摘要与 `TEST_DEFAULT` 警告并完成“已审阅”确认；系统不改限额。
6. 正常、失败和边界路径都有具名单元、集成、API 契约和浏览器 E2E 测试；无数据时页面如实显示缺失状态。
7. 历史不可变、Core/Tactical 分离、Decimal、审计/Outbox 与 `auto_trade=false` 均保持有效。
8. 不产生真实经纪商订单，且个人 Portfolio 数据不进入任何仓库资产或测试/日志证据。

## 完成前验证

至少运行受影响的格式、lint、类型、后端单元/集成/迁移、API/OpenAPI、前端单元/生产构建、浏览器 E2E、密钥扫描和
`docker compose config`。记录实际命令、结果和仍未验证项；只有全部验收标准有证据时才能转为 `READY_FOR_REVIEW`。

## 实施记录

- 2026-10-27（MVP-101可见验收收口，工作分支REVIEW）：
  - 基于已合入PR #17的当前Release，复验手工持仓、Core / Tactical独立均价与理由、现金、CSV无效行 / 显式冲突策略 / 写前不变 / 确认对账 / 刷新历史，目录搜索 / Watchlist幂等与删除、四项缺失研究状态和实际Policy只读审阅。
  - 真实浏览器发现A组合迟到预览会在B恢复确认；修前4项前端安全回归失败，真实API / DB用例也失败。按目标组合与请求代际校验，切组合 / 改CSV / 填示例撤销旧预览，新预览须重新选冲突策略；迟到成功或错误不再污染当前编辑。
  - 聚焦复核确认：确认请求始终写原组合A，但迟到结果曾在B展示A对账或错误。新增两项修前失败测试后仅隔离过期展示；原组合实际写入与审计不变，回到A可读历史，确认期间新填写的CSV不被旧结果清空。不是修复“写错B”。
  - 组合 / 持仓 / 现金的已知输入错误提供中文修正提示并保留输入；未改API / Schema / 数据库 / 鉴权 / 并发锁 / CAS / 领域规则。
  - 本轮实际：完整后端394 passed / 85.15%（67.32秒），独立集成31 passed，domain行98.06% / 分支88.04%；前端最终28/28、生产构建通过；空的独立浏览器库Chrome五文件14/14（21.1秒），只用15437 / 18109命名合成栈，无真实来源 / 模型调用。
  - Ruff格式237文件 / 检查、mypy84源文件、OpenAPI / Policy Schema、Compose config、diff、pip-audit无已知漏洞、npm audit0通过；292文件标准密钥检查无新增，仓库原基线不变。详细命令 / 失败修复 / 可见入口见 `docs/agent/work-items/MVP-101.md`。
  - 所有者部署 / 数据 / 凭据 / 会话未操作，Owner GUI与Checkpoint接受NOT VERIFIED；状态保持IN_PROGRESS，未代替Owner宣称ACCEPTED。

- 2026-09-29：首个纵切已实现 **Instrument 目录 + Portfolio 手工持仓 + Watchlist 写路径**（应用/领域/SQL/API）。
  - 领域：`InstrumentIdentity` 规范化 market/symbol/currency/name/asset_type/sector。
  - 应用：`InstrumentCatalogService`、`PortfolioBookService`（base currency/现金/Core+Tactical/平均成本）、
    `WatchlistService`（幂等加入；缺失产品字段显式 `None`，不伪造）。
  - 持久化：`InstrumentRecord`/`PortfolioRecord`/`WatchlistItemRecord` 与迁移 `20260929_0011`。
  - API：`/api/v1/instruments`、`/api/v1/portfolios`、`/api/v1/watchlist` 写读路径；组合响应 `missing_pricing=true`。
  - 定向单元测试 9 项通过（身份规范化、目录注册复用、现金/持仓、float 拒绝、Watchlist 幂等与空状态）。
  - `ruff check` 与针对新增模块的 `mypy` 通过。
  - **尚未完成**：CSV 导入预览/确认、对账、Watchlist 页面产品 UI、Policy 审阅 UI、集成/E2E、全量测试与
    OpenAPI 基线更新。不得据此标 `READY_FOR_REVIEW`。
- 2026-09-29（续）：并行交付 CSV 导入与产品 UI。
  - CSV：预览（VALID/INVALID/DUPLICATE）与确认写入；存在无效行时禁止 commit；单元测试 5 项。
  - UI：`/portfolio`（创建/手工持仓/CSV/对账表）、`/watchlist`（增删与四项空状态）、首页只读 Policy 审阅。
  - API：`POST /portfolios/{id}/csv/preview|confirm`、`GET /policy/review`。
  - 验证：定向单元测试合计 15 项通过；`ruff`/`mypy` 通过；`npm run build` 通过。
  - 仍缺：浏览器 E2E、集成/迁移全量、OpenAPI 基线。不得标 `READY_FOR_REVIEW`。
- 2026-09-29（收口）：
  - 集成：隔离库 `investment_os_p5_test` 3 项通过；修复迁移 revision、审计字段、SPA 路由与创建后选中组合。
  - E2E：`portfolio_watchlist.spec.ts` 4 项通过（Chrome channel）。
  - OpenAPI check、`tests.unit+集成 310`、`ruff`/`mypy src` 通过。
  - NOT VERIFIED：detect-secrets 本机未装；`docker compose` CLI 本机不可用。
  - 保持 `IN_PROGRESS`，待所有者验收。
- 2026-10-05（按所有者验收问题修复）：
  - P0 写鉴权：`/api/v1/` 写请求强制 Bearer；未配置令牌 503 失败关闭，错误令牌 401；UI 可配置写令牌。
  - P0 CSV 冲突：预览识别已有持仓冲突；必须显式跳过/替换/累加；写入 audit_log（before/after）。
  - P1 迁移链：补 `20260923_0009`/`0010`，`0011` 接到 `20260923_0010`，可从现有 0010 库升级。
  - P1 对账：导入返回 applied 明细与 audit_id；冲突决策可追溯。
  - P2：CSV 原因中文化、错误带 message、文档状态统一为 IN_PROGRESS。
  - 回归：单元 312 项、集成、`npm run build` 通过。
- 2026-10-05（复验修复二轮）：
  - Compose/`.env.example` 传入 `INVESTMENT_OS_API_WRITE_TOKEN`，标准栈可配置写令牌。
  - CSV 导入改为**单事务原子写入**（持仓批次 + 一条审计）；`import_hash` 幂等，重复确认拒绝。
  - 冲突策略改为**未选择不可确认**；导入后展示**逐行对账表**（before/after + audit_id）。
  - Position 补长期/机动分账成本与理由字段（迁移 `20260929_0012`）。
  - 手工持仓/现金错误信息中文化；项目状态表 P5 统一为 `IN_PROGRESS`。
  - **阶段归属待确认**：0009/0010 源自受阻 PR-09，仅作升级链修复纳入 P5 分支。
- 2026-10-05（复验修复三轮）：
  - `ruff format --check .` / `mypy src` 通过；0012 回填历史分桶均价；0013 `portfolio_import_claim`
    唯一约束保证并发幂等；目录 upsert 与持仓/审计同事务。
  - 文档 P5 状态统一为 `IN_PROGRESS`。
  - NOT VERIFIED：本机 Docker 未运行，完整集成与浏览器回归未在本提交执行。
- 2026-10-08（产品实操收口）：
  - 目录搜索 UI、持仓点击回填编辑、导入历史、现金更新、资产类型选择、选中组合保持。
  - CSV：UPDATE 在**写入链路**保留分仓均价/理由/操作（apply_import_batch 全字段）；SKIP 对账 after=实际值；预览 hash 绑定确认；切换组合清预览。
  - Watchlist 研究字段读取已有 Thesis/Evidence（无数据仍为「未提供」）。
  - 市场识别：五位代码优先 HKEX；观察清单可手动选市场。
  - 政策审阅读取库内政策/版本/配置；无数据仍显示 TEST_DEFAULT。
  - 凭据卷权限：运行手册 `docs/runbooks/secret-volume-ownership.md`；不以 root/777 规避。
  - 仍缺：观察清单研究状态（依赖 P6 分析）、完整并发压测。
- 2026-10-09（R1/R3 完整收口）：
  - **R1 并发**：所有持仓写入先锁 `portfolio` 行（含新增目标）；`Position` 更新用 version CAS
    （`WHERE version = expected`），失败抛 `POSITION_VERSION_CONFLICT` 且整批回滚；导入审计
    before/after 取自同一锁定事务内的实际读写。具名集成测试覆盖：预览后修改、空组合新增竞争、
    无关持仓+新增竞争、已有目标竞争、版本 CAS、混合批次回滚、正常导入。
  - **R3 新鲜度**：`derive_display_freshness(as_of, available_at, expires_at, ingested_status)`
    在读取时刻派生；`available_at` 含等于即为可用，`expires_at` 含等于即为 EXPIRED；
    摄取时 NOT_YET_AVAILABLE 跨过 available_at 后显示 FRESH；不改写 Evidence 历史。
    具名单元测试覆盖边界与跨时段场景。
  - 验证：单元 325、集成 9（含并发）、`ruff`/`mypy src`、`npm run build`、OpenAPI。
  - **NOT VERIFIED**：浏览器 E2E、密钥扫描、完整 374 套件、并发复现脚本在本环境重跑。
- 2026-10-09（审计逐行字段 P1 修复）：
  - 根因：`actual_applied` 改为 dict 后 `_write_import_audit` 仍用 `getattr`，字段全落 null。
  - 方案：新增 `ImportAuditRow` DTO + `from_source` 校验；缺字段/非法类型显式失败，不静默 null。
  - 调用方：批量导入 `apply_import_batch` 与 `record_import_audit` 经同一契约写入；保持组合锁/CAS/同事务回滚。
  - 具名测试 `test_import_audit_row_fields`：CREATED/REPLACED/UPDATED/SKIPPED 四路径
    确认后查库审计 + 历史 API，逐字段断言（4 passed）。
  - 回归：并发/R3/原有 CSV/组合测试通过；`tests.unit 325`、`tests.integration 49`、`ruff`/`mypy`、前端 4/4、构建通过。
  - **NOT VERIFIED**：浏览器 E2E、密钥扫描、原仓库外审计复现脚本对本 head 重跑。
- 2026-10-10（组合选择竞态修复）：
  - 根因：`load` 依赖 `selectedId` 且完成时回写选择，造成循环读取与旧响应覆盖新选择。
  - 方案：列表刷新用请求序号丢弃过期响应；用户意图 ref 不被 `data[0]` 偷走；历史加载与列表刷新分离；
    点击/创建走 `persistSelection`。不引入新状态库。
  - 回归：`PortfolioPage.test.tsx` 3 项（新建后旧响应、A→B 迟到响应、预览目标与读取次数）修复前失败、后通过。
  - 前端全量 7 passed；构建通过；隔离栈浏览器 E2E **6/6 串行通过**。
  - 保持 R1/R3/审计四项契约与既有测试不变。
- 2026-10-10（迟到刷新覆盖最新选择，复验 bede87d）：
  - 根因：`refreshList` 在**请求开始**捕获 `preferred`，响应时若用户已切走，仍把旧 preferred 写回选择。
  - 方案：完成时改读 `intentIdRef.current` 最新用户意图；序号仅丢弃更新的过期响应。
  - 回归：真实 pending GET（更新现金触发刷新 → 用户点 B → 暂停的 GET 返回）**PASS**；前端 7/7；E2E 6/6 串行。


## 2026-10-27 独立 Gate 现金竞态复修

独立复验在 `e65ecf8` 得到浏览器5/6：原完整持仓用例期待现金9000.5，实际10000.25。trace证明PUT发往正确组合、200成功，但请求体已是旧值 `10000.250000000000000000`；根因是持仓保存显示成功后，迟到的列表刷新无条件覆盖正在编辑的现金，不是后端丢写或写错组合。此前14/14只代表当时一次运行，不能证明该竞态已关闭。

修复以现金草稿dirty/revision保护未提交输入；显式切换组合载入对应现金；现金响应只在目标组合与输入版本都相同时显示成功/失败和清除dirty，迟到成功仍刷新实际列表。新增6项具名测试：旧持仓刷新后的现金成功/失败修前2 FAIL；新草稿/切组合×现金成功/失败的提示归属修前4 FAIL。修后全量前端34/34，build通过；新增真实API/DB/UI可控迟到刷新用例，确认PUT请求体9000.50、数据库9000.5及刷新后持久化；完整Chrome套件15/15（18.1秒，无跳过）。原9000.5断言未改变，没有固定延时或放宽断言。输出 `.runtime/mvp101-cash-final-browser-20261027`。

独立Gate反馈 https://github.com/zmd6s6/JZ-Investment-OS/pull/21#issuecomment-6431848403 状态为 `fixed-awaiting-review`，不是resolved或独立Gate通过。Owner Decision=NONE；Owner验收PENDING，PRODUCT-05仍IN_PROGRESS。此轮仅页面/前端测试与证据变更，后端394/集成31为前提交实测，本轮不冒称重新运行；以新HEAD远程CI补充核验。


## 集成前台账（2026-10-27）

代码提交 `308d99c867a30614d29c2bd1a1f7f1feedf04fc8` 已由主代理独立重跑现金/预览/反馈16/16、本项真实API/DB/UI浏览器7/7（18.7秒），包括原9000.5断言和可控迟到刷新；源码复核未报告新增阻塞。此为复验结果转录，不由实现者宣布独立Gate通过。该代码PR CI https://github.com/zmd6s6/JZ-Investment-OS/actions/runs/40456865749 已SUCCESS。

本次提交仅同步MVP-101集成台账；队列INTEGRATED及ACCEPTANCE_READY集成描述均随PR #21合入Release生效，不能代表已合并或Owner接受。Owner PENDING / PRODUCT-05 IN_PROGRESS保留；评论6431848403在独立方核对最终HEAD并确认前仍为fixed-awaiting-review。最终CI、Gate与合并由PR记录核对，未修改真实政策、未部署Owner实例。

恢复入口：PR https://github.com/zmd6s6/JZ-Investment-OS/pull/21 ，独占分支agent/MVP-101；先核对 `git status` / `gh pr view 21` / 当前HEAD CI。18109与15437合成栈保留，未重置或停止Owner服务。下一步仅处理当前HEAD CI或可执行Review；独立Gatekeeper决定是否合入release/mvp-beta，实现者不自行合并。
