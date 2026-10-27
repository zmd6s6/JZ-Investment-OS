# User-visible Acceptance

> 这是所有者查看“现在到底能用什么”的产品验收台账。仓库状态不能替代浏览器实际行为。

## 状态定义

- `NOT_IMPLEMENTED`：没有可用产品路径；
- `ENGINEERING`：底层实现存在，但尚未形成完整用户路径；
- `INTEGRATED`：真实 UI/API/DB/Worker 已接通；
- `ACCEPTANCE_READY`：可由所有者直接按步骤验收；
- `ACCEPTED`：所有者已完成可见验收；
- `DEGRADED`：可用但存在明确限制/失败。

## 当前 Checkpoint

| Capability | Route | Current truth | Human acceptance |
|---|---|---|---|
| Portfolio / CSV import | `/portfolio` | INTEGRATED — PR #17 merged; browser acceptance still required | PENDING |
| Watchlist | `/watchlist` | INTEGRATED — PR #17 merged; browser acceptance still required | PENDING |
| Investment Policy review | product UI | INTEGRATED; real policy parameters remain owner-governed | PENDING |
| Acceptance Center | `/acceptance` | ACCEPTANCE_READY — MVP-000集成记录随PR合入Release生效；构建交付清单不是实时健康检测 | PENDING |
| Analysis | `/analysis` | NOT_IMPLEMENTED — MVP-203/204 | PENDING |
| Decision Center | `/decisions` | NOT_IMPLEMENTED — MVP-301 | PENDING |
| Daily Runtime | product UI | ENGINEERING baseline only; product calendar/runtime pending MVP-401 | PENDING |
| Opportunities | `/opportunities` | NOT_IMPLEMENTED — MVP-402 | PENDING |

## Checkpoint A 验收步骤

### 产品进度入口（MVP-000）

从主导航「产品进度与验收」或直接打开 `/acceptance`，分别查看工程交付、集成证据、人工验收和服务装配。
展开操作指引，进入组合 / 观察清单 / 设置 / 政策页面；分析、决策、机会等未交付产品不提供误导链接。
刷新后仍须显示待所有者验收；本页没有写入、验收通过或调用模型按钮。
读取失败显示中文错误，成功卡片清空，点「刷新产品进度」只读重试；服务未装配保留工程证据但隐藏入口。
这只描述当前构建的已记录交付及用例装配，不保证数据库 / 供应商健康，不保证已授权或已配置，也不接受Checkpoint。
工程与集成证据见 `docs/agent/work-items/MVP-000.md`，所有者部署与产品接受仍未执行。

### Portfolio / Watchlist

1. 打开 Portfolio；
2. 创建/选择 Portfolio；
3. 手工添加持仓；
4. 上传 CSV，查看 Preview/错误；
5. Confirm 后刷新，数据仍存在；
6. 查看导入对账结果；
7. 打开 Watchlist，搜索并添加/移除标的；
8. 查看生命周期/Thesis/数据新鲜度/下一监控条件的真实或显式空状态；
9. 查看当前 Policy version 与 TEST_DEFAULT 警告；
10. 至少验证一个失败路径，错误必须用户可见。

通过后才将 PRODUCT-05 标为 ACCEPTED。

## 规则

任何业务 Work Item PR 都必须更新本文件或产品 `/acceptance` 页面对应能力的真实状态。不得把 API 存在、单测通过或静态 UI 等同于用户可用。

## 人工行情与币种边界（MVP-201，Checkpoint B的输入切片）

本工作分支已完成隔离合成环境UI / API / DB接线验证，随本PR合入Release才生效；Owner部署与人工验收PENDING。
进入 `/settings` →「记录人工行情／查看单币种与FX边界」或 `/market-data`；先登记标的，再搜索、填来源 / 出处 / 精确价格及四个业务时间，明确保存后读取。
应看到Evidence、hash、UTC来源时间；刷新后再次读取仍存在。错误应保留输入，过期 / 缺价 / 未来资料不显示价格；切换USD估值应显示缺FX并阻止。
人工资料始终未经独立核实、非交易级；不自动调用模型 / 网页或产生订单。工程 / 浏览器证据与限制见 `docs/agent/work-items/MVP-201.md`。
完整分析、FX、全市场行情、波动率 / 流动性及Sizing不在本切片交付中，不能因此接受整个P6或Checkpoint。
