# ADR0048 — 每日Shadow授权、暂停围栏与只追加日报

- 状态：Accepted（已合入MVP-403契约内工程实现，不批准真实研究或新成本）
- 日期：2026-10-29
- 补充0003/0004/0005/0008/0010/0012/0014/0015/0016/0037/0041/0045，不改旧投资治理。

## 决策与范围

Daily配置与Owner授权显式分开LOCAL_STATUS_ONLY / SCHEDULED_SHADOW，保存新revision始终暂停；独立确认后启用，可暂停或永久撤销。所有命令支持request UUID幂等、异内容拒绝与乐观版本，不依赖浏览器localStorage授权。市场/Portfolio与Watchlist有限成员、显式日历与完整日期覆盖、每日会话收盘频率、精确本地报价和Evidence来源名称、model/data profiles、成本/Token预算、retention使用期限、授权起止与暂停/撤销方式均持久；每Run固定revision与当时模式版本。不从Calendar STATUS_ONLY、候选研究intent或旧一次性授权推断许可。

本轮技术资源边界为100个显式标的、最长366个覆盖日期、每轮有限due会话/入队数，不是投资阈值或默认真实范围。Portfolio/Watchlist成员精确冻结；新增/移除/跨市场/身份漂移须新暂停版本，不能自动扩大scope。每日报告保留业务会话as_of、实际本地读取和分析排队时点；不把当前账本或后到资料冒充收盘已知数据。各Evidence四时间/expiry/hash分别保留，只对明确来源和标的内的有效本地资料比较差异；首次运行显示无基线，无变化不制造Thesis空版本。

## 外部调用与成本最后闸门

LOCAL_STATUS_ONLY明确零资料/模型profile、零费用与零Token，只读已有本地事实。SCHEDULED_SHADOW须全部角色显式模型、独立出站和费用确认、当前档案完整hash与当前预算hash，现有单任务/UTC日预算不得超过授权边界；最后仍由203的预算事务预留与档案核验执行，不由Daily绕开或替代。

当前ResearchRuntime数据档案没有typed每次/每日资料费用预留；不能把未知资料费用当0。因此首纵切的data_profile_ids必须明确为空（非缺失），使用本地Evidence并可调用已明确授权模型。非空研究数据档案明确DAILY_EXTERNAL_RESEARCH_COST_BOUNDARY_UNAVAILABLE，0资料请求；未来启用须具备真实费用准入再扩展。不新增真实来源、许可或模型授权，工程仅用loopback合成验证，页面诚实展示该边界。

Daily自己的持久intent必须先于Analysis排队建立精确授权归属和命令hash，然后复用AnalysisStartService/AnalysisRun唯一request_id。它是Daily调度意图，不是候选研究intent；队列提交或响应不确定时按原request只读核对，不创建新付费运行或自动重播。Analysis准备及每个模型调用外层持有Daily授权配置共享锁，暂停/撤销更新取写锁：许可先获得时暂停等待该有限调用结束，暂停确认后后续调用无法出站；暂停先获得时调用失败关闭。这样覆盖credential/budget等await窗口，不能只在排队或调用前做一次无锁检查。原模型档案与预算最后闸门保留；旧交互分析没有Daily归属时保持其既有逐次授权。

授权缺失/过期/停用/撤销/版本变化/范围或profile/budget漂移均可见失败，零后续出站；已发出的调用可能收费且未知费用保守保留，不声称能撤回。停止后恢复只允许新到期会话，不回补暂停区间或借新授权重播历史未知费用。

## 持久化与报告

新增0022待真正0021存在后形成单head：配置指针、只追加授权revision/正规成员、TaskRun关联Daily执行、只追加报告版本/Evidence关系、Daily分析intent及正规AnalysisRun绑定。关键时间/市场/业务日期/版本/关系正规化，JSON仅保存严格版本化冻结输入和报告结构。配置/授权/报告/intent的业务写入、Audit/Event/Outbox同事务，锁与唯一日业务键防重入及跨版本重复付费；跨阶段只追加明确QUEUED/PENDING/FINAL或失败状态，不制造跨事务原子成功。

日报展示action-required、hold/watch、new-opportunity、Risk Veto、待处理approvals、data/job-degraded全部六类。只读真实关联产物，缺失明确NOT_PROVIDED；本地成员/数据异常不是投资Action，没有可靠字段不能填0或伪装成功。Dispatch TaskRun成功只表示本地检查/持久意图完成，不等于模型分析成功；等待实际Analysis终态后追加最终报告，不覆盖初始日报。REPORT保留期是有效使用期限，过期停止使用和业务正文展示，审计/hash/不可变历史保留，不承诺静默删除历史或自动激活Policy/Strategy。

## 验证、替代与回滚

拒绝默认真实启用、隐式工作日、无锁预检、未知资料费用放行、失去授权关联的孤儿队列、自动重试未知模型、半报告/Outbox和覆盖旧报告。具名测试覆盖缺授权字段/空档案/预算与profile漂移、四时间、范围漂移、到期/闭市、幂等/事务故障、暂停与出站双交错、撤销/中断、真实API/DB/Worker/UI。Owner18102/15433和旧402栈不操作；专用403合成15446/18120先核身份。

空新增表允许降回真实0021；有历史拒绝降级，撤回应用并保留表/审计，采用前向修复。无新生产依赖、不改Master/真实Policy/Risk/Sizing/Decision授权、不自动批准/执行/下单，auto_trade=false。工程实现和合成验证不等于真实Owner启用、Checkpoint或完整P8接受。


## 本次首次交付内的时间与恢复细化

business_as_of仅标显式会话收盘；knowledge as_of取实际本地读取时间，四时间/expiry相对该知识时点验证，不能把盘后入库资料说成收盘已知。账本保留自身读取时间，分析保留实际排队和冻结时点。错过原业务日的missed_run_policy固定LOCAL_REPORT_ONLY_NO_RESEARCH并须明确提交：只当前本地异常/状态，不自动补发旧日收费研究。预算reserve/credential await后、HTTP前同步重核授权有效期；配置锁不会停止时钟。已知未出站的期限阻断释放预算预占，不伪造用量；已进入HTTP仍按既有保守未知费用处理。
