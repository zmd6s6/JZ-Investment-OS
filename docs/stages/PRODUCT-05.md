# PRODUCT-05 — Portfolio 与 Watchlist 产品

- 状态：`PLANNED`
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
2. 手工持仓录入；每笔必须明确 market、symbol、名称、资产类型、币种、数量、平均成本及 Core/Tactical bucket。
3. CSV 导入的格式说明、逐行校验、规范化预览、错误报告和显式确认；预览绝不写入业务历史。
4. 确认后的可审计导入快照、幂等/重复处理、持仓对账结果及失败可见性。
5. Watchlist CRUD 与受类型化端口支撑的标的搜索/规范化。
6. 页面显式显示数据的 as-of、可用性和缺失状态；不得伪造市值、收益、机会、Risk Veto 或审批信息。

## 不变量与范围外事项

- Portfolio 写入只能经类型化 application port；历史、导入快照、审计记录和 Outbox 与业务写入同一事务。
- 数量、成本与金额使用 `Decimal`/数据库 `numeric`；Core 与 Tactical 的数量、成本、操作和理由分别保存。
- CSV 预览、无效行、部分失败、重复记录和并发冲突必须显式呈现，不能静默丢弃或覆盖历史。
- 个人持仓及 CSV 不得进入仓库、测试夹具、日志、截图、错误响应或分析上下文；测试仅用合成或明确授权且去标识化数据。
- 本阶段不增加价格、估值、收益计算、自动分析、机会推荐、Policy 选择、风险限额变更、Decision、Approval、Execution
  或任何经纪商调用。

## 人工边界

所有者在实际使用时自行决定录入方式和个人持仓内容；系统不替所有者选择 Investment Policy 或投资动作。若实现需要
新增真实数据源、处理未获授权的个人数据存储边界或改变真实投资规则，必须先停止并请求明确决定。

## 验收标准

1. 所有者可仅通过 UI 创建/选择 Portfolio，手工录入持仓，并在刷新后查看可追溯结果。
2. CSV 可先预览；规范化、无效行和冲突均可见；只有明确确认后才写入，且确认后可对账。
3. Watchlist 可通过 UI 创建、查看、添加和移除；标的搜索/规范化使用受支持的真实应用 API。
4. 正常、失败和边界路径都有具名单元、集成、API 契约和浏览器 E2E 测试；无数据时页面如实显示缺失状态。
5. 历史不可变、Core/Tactical 分离、Decimal、审计/Outbox 与 `auto_trade=false` 均保持有效。
6. 不产生真实经纪商订单，且个人 Portfolio 数据不进入任何仓库资产或测试/日志证据。

## 完成前验证

至少运行受影响的格式、lint、类型、后端单元/集成/迁移、API/OpenAPI、前端单元/生产构建、浏览器 E2E、密钥扫描和
`docker compose config`。记录实际命令、结果和仍未验证项；只有全部验收标准有证据时才能转为 `READY_FOR_REVIEW`。
