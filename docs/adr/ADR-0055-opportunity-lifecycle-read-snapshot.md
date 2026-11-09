# ADR-0055 — 机会结果中的只读生命周期来源快照

- 状态：Proposed（须独立Gate及实际合入后生效）
- 日期：2026-11-10
- 补充ADR0003/0040/0051/0054；主规范§2.3/5/8与Beta§13。

## 决定与时间边界

机会查询通过typed application port读取instrument_state，不写生命周期、Thesis或Decision。筛选入选、Watchlist成员、人工报价均不是状态转换或可交易资格。新v1/v2手动及周筛选在原as-of冻结只读LifecycleSnapshot子协议1.0，含实际状态、来源行ID/version、created_at/effective_at、已核对同标的且当时已存在的可选Thesis/Decision引用和规范hash；不是Agent事实Evidence，不加入财务/行情Evidence清单，不影响确定性过滤、候选顺序、Risk或批准。

当前instrument_state仅有当前行及创建时间，没有版本更新时间或可恢复的完整转换历史。因此仅version=1且created_at/effective_at均不晚于as-of的合法枚举/身份可显示AVAILABLE；version>1明确STATE_HISTORY_UNAVAILABLE，缺失、未来、无效引用分别UNKNOWN，不用当前状态推断历史，不将created_at冒充后续版本可用时间。已有持久化state本身不是投资建议；尤其显示BUYABLE不代表当前Risk/Policy/Approval通过。

## 兼容与历史

FunnelRow增加可缺省lifecycle_snapshot字段，子对象独立版本化；原lifecycle_state字段保留，新行与子对象一致。外层v1/v2与既有请求hash/过滤公式不变，旧run原始JSON/hash不重写，读取旧run没有子对象时页面明确“历史运行未冻结生命周期”，不现场读取回填。新run子对象含在原只追加事件hash中，重放按原冻结值且校验标的/as-of/状态/hash。新候选next_condition改为EXPLICIT_RESEARCH_CONSENT_REQUIRED；旧DEEP_RESEARCH_NOT_PROVIDED保持当时语义，页面区分历史与当前逐次研究能力。

## 替代、验证、恢复

拒绝由候选推断WATCH/BUYABLE、直接读取当前行填旧历史、把version>1的创建时间当更新可用时间、为显示而写状态或扩投资治理。无新表/依赖/外部源/模型调用。真实PG正常、缺失、前视、版本历史不可恢复、错误引用、原历史重放/兼容与v1/v2/周路径测试；真实API/UI显示来源、未知和失败。回退应用保留原事件JSON，不删除历史；旧应用不支持新增字段时用新版本前向恢复读取，不降级改写hash。Owner实例、真实源许可、Policy/Strategy/交易权限及Checkpoint接受均不由此改变。
