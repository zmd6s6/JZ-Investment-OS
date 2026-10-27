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
| Portfolio / CSV import | `/portfolio` | ACCEPTANCE_READY — MVP-101已验证手工 / 分仓 / 现金 / CSV预览及冲突 / 对账 / 刷新；集成记录随PR #21合入Release生效 | PENDING |
| Watchlist | `/watchlist` | ACCEPTANCE_READY — MVP-101已验证目录搜索 / 幂等添加 / 刷新 / 删除 / 四项缺失状态；集成记录随PR #21合入Release生效 | PENDING |
| Investment Policy review | `/#policy` | ACCEPTANCE_READY — MVP-101已核对实际API版本与无写入审阅；真实参数仍由Owner治理 | PENDING |
| Acceptance Center | `/acceptance` | ACCEPTANCE_READY — MVP-000集成记录随PR合入Release生效；构建交付清单不是实时健康检测 | PENDING |
| Analysis | `/analysis` | NOT_IMPLEMENTED — MVP-203/204 | PENDING |
| Decision Center | `/decisions` | NOT_IMPLEMENTED — MVP-301 | PENDING |
| Daily Runtime | product UI | ENGINEERING baseline only; product calendar/runtime pending MVP-401 | PENDING |
| 日历状态报告（MVP-401独立切片） | `/calendar`，设置页提供入口 | 分支隔离集成与浏览器路径已验证；待独立Gate / Release集成；不含团队分析，不代表完整Daily Runtime | PENDING |
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

MVP-101于2026-10-27在独立合成API / DB完成可见路径复验，修复CSV迟到预览、旧冲突选择以及确认结果的跨组合展示；现金竞态复修后前端34/34、Chrome15/15通过；主代理独立复验现金/预览/反馈16/16、本项真实浏览器7/7。此集成记录随PR #21合入Release生效，最终Gate仍由独立复验方判定。
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

任何业务 Work Item PR 都必须更新本文件或产品 `/acceptance` 页面对应能力的真实状态。不得把 API 存在、单测通过或静态 UI 等同于用户可用。
