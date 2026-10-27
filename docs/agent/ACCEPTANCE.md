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
| Portfolio / CSV import | `/portfolio` | ACCEPTANCE_READY — MVP-101已由PR #21合入Release；手工 / 分仓 / 现金 / CSV预览及冲突 / 对账 / 刷新已有隔离可见验证 | PENDING |
| Watchlist | `/watchlist` | ACCEPTANCE_READY — MVP-101已由PR #21合入Release；目录搜索 / 幂等添加 / 刷新 / 删除 / 四项缺失状态已有验证 | PENDING |
| Investment Policy review | `/#policy` | ACCEPTANCE_READY — MVP-101已核对实际API版本与无写入审阅；真实参数仍由Owner治理 | PENDING |
| Acceptance Center | `/acceptance` | ACCEPTANCE_READY — MVP-000已由PR #20合入Release；构建交付清单不是实时健康检测 | PENDING |
| 人工行情与币种边界 | `/market-data` | INTEGRATED — MVP-201已由PR #22合入Release；人工未核实、CNY限定，非完整分析 | PENDING |
| Analysis | `/analysis` | NOT_IMPLEMENTED — MVP-203/204 | PENDING |
| Decision Center | `/decisions` | NOT_IMPLEMENTED — MVP-301 | PENDING |
| Daily Runtime（团队分析 / 周月复核） | product UI | ENGINEERING baseline only；MVP-401仅交付下列日历状态报告，完整团队运行仍未接通 | PENDING |
| 日历状态报告（MVP-401独立切片） | `/calendar`，设置页提供入口 | MVP-401=INTEGRATED / ACCEPTANCE_READY，此记录随PR #23通过最终独立Gate合入Release生效。91801d0已获独立28项SQL / 1项恢复浏览器复验；仅STATUS_ONLY，不含团队分析或完整Daily Runtime | PENDING |
| Opportunities | `/opportunities` | PARTIAL — 本地范围 / 人工年报 / 确定性漏斗随本PR集成；全市场 / 深研 / 周定时未提供 | PENDING |

## Checkpoint A 验收步骤

### 产品进度入口（MVP-000）

从主导航「产品进度与验收」或直接打开 `/acceptance`，分别查看工程交付、集成证据、人工验收和服务装配。
展开操作指引，进入组合 / 观察清单 / 设置 / 政策页面；分析、决策、机会等未交付产品不提供误导链接。
刷新后仍须显示待所有者验收；本页没有写入、验收通过或调用模型按钮。
读取失败显示中文错误，成功卡片清空，点「刷新产品进度」只读重试；服务未装配保留工程证据但隐藏入口。
这只描述当前构建的已记录交付及用例装配，不保证数据库 / 供应商健康，不保证已授权或已配置，也不接受Checkpoint。
工程与集成证据见 `docs/agent/work-items/MVP-000.md`，所有者部署与产品接受仍未执行。

### Portfolio / Watchlist

MVP-101于2026-10-27在独立合成API / DB完成可见路径复验，修复CSV迟到预览、旧冲突选择以及确认结果的跨组合展示；现金竞态复修后前端34/34、Chrome15/15通过；主代理独立复验现金/预览/反馈16/16、本项真实浏览器7/7。PR #21已通过独立Gate并合入Release。
这不是所有者本人接受，不改变PRODUCT-05 IN_PROGRESS或Checkpoint A PENDING。证据、输入与明确限制见 `docs/agent/work-items/MVP-101.md`。
CSV请求处理中切换组合或改动内容后，迟到预览不能恢复确认；内容变化后须重新预览并选择冲突方式。
已发出的确认仍写入原组合；切换后的页面不会把原组合对账当成本组合结果，回到原组合可查导入历史。

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

### 日历状态报告验收路径（MVP-401）

设置 → 配置市场日历与查看运行记录 → 选择市场 / 填来源与版本 → 上传或粘贴CSV → 确认来源 → 预览UTC时段 → 明确导入。
新版本显示暂停；勾选「仅状态报告」后启用，在到期时段观察真实Worker记录与来源摘要，刷新仍保留，再暂停。
失败路径：重复日期 / 部分错误整批拒绝且保留输入；读取失败禁止保存 / 启停并显示未知，可只读刷新恢复。
无Worker或无到期会话时没有报告不表示健康；本路径不含团队研究、费用授权、投资建议或交易。
详细命令、独立栈与迁移恢复证据见 `docs/agent/work-items/MVP-401.md`。尚未操作所有者实例，所有者验收PENDING。
证据归属：c0ad765旧头独立日历四文件25/25、普通浏览器2/2仅限旧实现；恢复与双交错修复后的91801d0由root独立复跑四文件28/28（8.75秒）及原样真实API / DB / Worker恢复浏览器1/1（15.7秒），源码无新增blocker。
91801d0的Linux六CI全绿，完整454 / 85.50%、集成51；这是该精确提交的工程证据，不代替后续提交的最终合入门禁。MVP-401集成记录随PR #23合入Release生效，Owner=PENDING、完整PRODUCT-08=PLANNED。

任何业务 Work Item PR 都必须更新本文件或产品 `/acceptance` 页面对应能力的真实状态。不得把 API 存在、单测通过或静态 UI 等同于用户可用。

## 人工行情与币种边界（MVP-201，Checkpoint B的输入切片）

MVP-201已完成隔离合成环境UI / API / DB接线验证，并由PR #22合入Release；Owner部署与人工验收PENDING。
进入 `/settings` →「记录人工行情／查看单币种与FX边界」或 `/market-data`；先登记标的，再搜索、填来源 / 出处 / 精确价格及四个业务时间，明确保存后读取。
应看到Evidence、hash、UTC来源时间；刷新后再次读取仍存在。错误应保留输入，过期 / 缺价 / 未来资料不显示价格；切换USD估值应显示缺FX并阻止。
人工资料始终未经独立核实、非交易级；不自动调用模型 / 网页或产生订单。工程 / 浏览器证据与限制见 `docs/agent/work-items/MVP-201.md`。
完整分析、FX、全市场行情、波动率 / 流动性及Sizing不在本切片交付中，不能因此接受整个P6或Checkpoint。


## 有限范围机会漏斗（MVP-402，PARTIAL）

本PR只接通本地明确手选范围、人工自然年年报事实、确定性四指标 / 分层查询、有界研究候选和不可变历史；工程清单明确PARTIAL。全市场 / 深研 / 周定时尚未提供，不表示完整402、P8或Checkpoint接受。
入口 `/opportunities`，也可从导航 / 设置 / 产品进度进入。先登记标的并保存人工报价，选择有限范围；绑定报价Evidence，录入有来源的年度利润 / 营收 / 年报稀释EPS和时间，填本次研究查询条件后筛选。
应看到候选与排除理由、缺项、来源 / UTC业务时间 / Evidence / hash；刷新保持旧结果。跨币种缺FX、过期 / 未来 / 损坏 / 口径不符必须停止，不借旧价、不心算EPS、不调用模型或产生交易。
本项21个合成浏览器场景总回归通过，不代替Owner个人数据或产品接受；细节与限制见 `docs/agent/work-items/MVP-402.md`，记录随PR合入Release生效。
