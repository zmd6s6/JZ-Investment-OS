# ADR-0050 — 独立月频授权与本地组合复核

- 状态：Accepted（主规范§14.3/14.5及PRODUCT08内工程实现，不改变真实投资治理）
- 日期：2026-11-05；Work Item MVP-404。补充0003/0008/0012/0037/0039/0048/0049，旧ADR不改写。

## 决策与替代

/calendar新增独立月度授权，不复用Daily config或model consent。完整自然月起止、显式市场/全部Portfolio成员、指定本地报价与Evidence来源、授权起止/期限、保留期、月频完整日历确认及暂停方式均明确版本化。默认暂停、独立启停/永久撤销；固定LOCAL_MONTHLY_REVIEW、model/data档案为空及NONE/0费用/Token，拒绝任何收费月度研究。未来收费研究需要独立完整授权/费用围栏，不从已有Daily扩大来源或频率。只读复用Daily范围捕获适配器不写Daily表、不创建Analysis/Decision/Approval/Execution，不激活Policy/Strategy。

市场时区下完整自然月结束后才到期，以当月最后显式会话标识business_as_of；声明完整但零会话时明确CLOSED_MONTH_SKIPPED，不推断工作日。已结束月仅在新独立月度明确许可下做本地当前知识捕获，current ledger read/knowledge_as_of/报告recorded_at与月末业务时间分别保存，不提供虚假历史账本。最多366日期/100显式持仓/每轮4月任务/50配置是可逆资源边界，不是投资限额；空组合目前具名拒绝，不借测试价格填0。

只追加月报固定持仓Core/Tactical数量成本/理由与读取时间、有效Evidence四时间/expiry/hash/差异、明确参考行情和确定性NAV/权重、同revision且仍可用的既往报告基线、已有Thesis/Risk/Decision历史引用。缺基线不填0变化；缺价整组NAV/权重未知，不用平均成本代行情；已有Risk/Decision只作为历史记录而非新批准或当前PASS。宏观行业全景、相关性/资本效率、锚定沉没成本判断、风格漂移/分仓再平衡与今天重新进入意愿未有合格输入/结构判断时逐持仓明确NOT_PROVIDED/unknown，不伪造AI结论或投资动作。

## 持久化、并发与恢复

0024父为真实已合入0022（链0024→0022→0023→0021），六张正规表：配置、只追加授权、成员、唯一schedule/month报告、Evidence引用、带明确类型及真实FK的Thesis/Analysis/Risk/Decision引用。JSON仅保留严格版本冻结快照。所有命令request UUID幂等、同UUID异内容拒绝、CAS；保存必须匹配预览scope/source hash，新版本暂停、REVOKE终端。范围父/子行锁防新成员与修改，配置→组合→日历固定锁序与本地有限读取期间持锁，暂停确认后旧任务不能提交。

可靠TaskRun咨询锁/幂等键绑定schedule/revision/月；报告业务唯一schedule/月阻跨版本重复效果。报告/正规引用/TaskRun成功/Audit/Event/Outbox同事务，故障全部回滚，TaskRun独立清洗失败记录，最多三次同revision本地重试；来源修复保存新的暂停授权后明确启用，可恢复未成功月而不重写成功历史。只读重放核严格Schema/hash/FK关联，不取新数、不调用外部服务。保留期是正文有效使用期，过期停止展示/使用，审计历史/hash不删除。

拒绝默认启用、Daily许可自动升级、隐式日历/未知费用、无来源估值、半产物、覆盖旧报告与前视历史月账本。无新生产依赖。空新增表可降真实0022，有任何月度历史拒绝downgrade；应用回退暂停月任务并保留表/历史，前向修复。只用独立合成API/DB/Worker/Chrome证明正常失败边界，Owner18102/15433与真实付费不操作；auto_trade=false。

## 验证要求

完整月/跨年闰月/时区截止、无会话、未来月、默认暂停/永久撤销、CAS/preview漂移/幂等、范围与日历双session、期限await临界、0预算且无任何provider依赖、Outbox故障回滚/重试上限、无基线/分仓差异/缺价/陈旧来源/受限历史引用、严格重放/expiry、空升降升与非空历史保护及真实产品UI/Worker均需具名证据。工程、集成、可见与Owner接受分别记录，实现者不自签Gate。
