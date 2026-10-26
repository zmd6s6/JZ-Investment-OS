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
| Acceptance Center | `/acceptance` | NOT_IMPLEMENTED — MVP-000 | PENDING |
| Analysis | `/analysis` | NOT_IMPLEMENTED — MVP-203/204 | PENDING |
| Decision Center | `/decisions` | NOT_IMPLEMENTED — MVP-301 | PENDING |
| Daily Runtime | product UI | ENGINEERING baseline only; product calendar/runtime pending MVP-401 | PENDING |
| Opportunities | `/opportunities` | NOT_IMPLEMENTED — MVP-402 | PENDING |

## Checkpoint A 验收步骤

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
