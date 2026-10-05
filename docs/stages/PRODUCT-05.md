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
