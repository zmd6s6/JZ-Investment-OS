# ADR-0041 — 持久AnalysisRun、冻结输入与非执行影子结论

- 状态：Accepted（主规范及既有ADR完全限定范围内工程选择，不放松投资治理）
- 日期：2026-10-28
- 补充：ADR0003/0004/0005/0006/0007/0011/0014/0015/0038/0039；不改旧AgentOpinion1.0或旧风险/仓位公式。

## 背景 / 决策

现有AgentRuntime/CommitteeRuntime、Evidence/Thesis/Feature/Risk/Sizing基础不等于用户可发起、观察、恢复的分析产品。以独立AnalysisRun聚合维护QUEUED→RUNNING→SUCCEEDED/DEGRADED/FAILED/CANCELLED；终态不可变。重试是新request/run关联原run，绝不重写原历史或静默重新执行付费调用。

新增0016正规化AnalysisRun、冻结AnalysisInput、带FK的Evidence引用、追加步骤/角色产物与独立ShadowDecision。关键查询字段与关系正规化，JSON只保留版本化结构快照；不是一个万能JSON表替代Thesis/Opinion/Committee/Risk/Feature/Decision。已有有效产物仍用现有主表及其校验，不制造哨兵Policy/Thesis/Strategy UUID填满未就绪的InvestmentDecision。影子结论与可审批Decision分离，前者当前无Sizing、不可执行且禁止BUY/ADD（DTO和数据库双约束）。

明确输入选择与调用同意：每个运行保存各角色模型档案、已保存Evidence、可选显式研究档案/查询/顺序/数量、报价来源名称、202账本估值/Policy具体版本。不开启或改写全局角色映射，不自动切源。模型/预算/研究档案身份与配置hash冻结；调用前检查未停用/未漂移。所有角色及修复共享run_id的任务预算，仍由既有LLMBudgetService预留/结算。取消无法撤销已发出调用或费用，UI明确说明有界停止边界。

实际外部研究若选择则在Worker中受限执行并摄入Evidence，冻结最终可得Evidence及其observed/effective/available/ingested/expiry与hash；保存原排队时P5快照/Policy参考时间，不能把后到资料说成排队时已知。模型只读冻结context，所有事实/风险/逻辑引用都须在本次有效Evidence集合内，过期/未来/冲突/无效结构均显式阻断或降级。外部正文当不可信数据，Prompt隔离，不给写入/交易工具。

Features由确定性代码计算；已有Thesis版本按as-of读取，缺失保持UNKNOWN，不凭空创建VALID逻辑。现有两轮协议不变：专家独立Round1，定向Round2且始终Devil's Advocate，保留每个角色成功/失败。Portfolio只通过新相邻协议portfolio-intent-1.0输出risk_intent/引用理由，拒绝任意百分比；CIO以cio-proposal-1.0提出结构化Action，再由既有确定性gates裁决。此两个协议不修改既有AgentOpinion1.0含义。

Risk缺确定性输入为UNKNOWN，不因模型乐观编PASS；202缺波动/流动性/预占容量/Policy/交易级行情时Sizing仍BLOCKED、数量未提供。先把真实缺口可见，不设波动/FX/现金容量等默认数值。不把存在NAV或成功委员会当作可交易。完整Risk/数量未来仅能在所有真实、受治理输入齐备时另行接通，不绕过本协议的失败关闭。

## 可靠性 / 架构

应用层通过typed ports编排，基础设施拥有SQL/HTTP；domain保持无框架。请求幂等键只对应规范命令，相同请求重放返回原冻结历史，不重新采样。事务内领取QUEUED行（FOR UPDATE SKIP LOCKED）授予唯一lease；每步骤写入/审计/Event/Outbox同事务，最终影子结果/Evidence链接/终态同事务。

Worker全运行和每个模型调用有技术性时限。运行过程中只在有界步骤边界处理取消，不声称可撤销已发生费用。进程中断的RUNNING在超时后记明确FAILED/INTERRUPTED_RETRY_REQUIRED，不自动重播未知完成的外部调用；所有者可显式新Run重试。已完成角色/步骤和旧失败永久可读，终态/快照/产物数据库防更新删除。

## 替代方案与后果

拒绝请求内同步长调用/仅内存状态、默认自动外部重试、静默换源、原地重试覆盖、把缺Policy/Sizing伪造成有效完整Decision、从旧PR18整包merge未验证Schema链。复用PostgreSQL/Worker，无新服务或生产依赖；公开API新增版本化端点而不破坏旧Decision协议。完整跟踪下钻204与审批301仍受203真实依赖，不借本切片宣布完成。

## 迁移 / 恢复 / 验证

0016基于当前Release0015，仅新增分析表/约束/不可变守卫；无Owner数据部署。空库和上一版本升级、幂等/并发/故障回滚/不可变历史/取消/中断/坏输出/预算/日期/缺Policy与Sizing都须具名测试。存在分析历史时拒绝降级删除，回滚应用并保留表，必要时前向修复。合成验证15442/18114/独立命名库，真实付费/Owner迁移重启需实际有效授权，本轮不调用。

## 独立审查后的最终边界收紧（2026-10-28）

本节是本ADR首次交付内的明确补充，记录预算/资料边界的工程修复，不回写或削弱已接受的上层治理。独立审查在09974bb复现了预检后策略/研究档案变化以及无效资料正文前视；原先成功测试不能抵消这些边界问题。

内部LLMGatewayRequest增加可选expected_budget_policy_hash（SHA-256，默认None），不是新增外部模型字段或破坏旧AgentOpinion协议。Analysis所有角色及修复请求强制携带排队时完整预算内容hash；LLMBudgetService会先匹配当前内容，并把期望传入最终SqlBudgetStore预留事务。事务先对Policy行FOR SHARE加锁，核完整hash，再在原有锁/限额机制内创建ledger/reservation；策略保存的FOR UPDATE不得在校验与预留提交间穿插。漂移在任何预留/出站前失败，0模型HTTP、0reservation/usage，不把失败费用伪造为已花费。未指定期望的旧调用保留原接口行为；新保护调用不能悄悄降级为不核期望。

所有模型正文只来自AnalysisContext.visible_evidence_ids；未来/过期/无效资料仍可在不可变输入审计中保留，但不得把正文、ID或节选发给任何轮次/角色。opaque输入hash不等于资料正文，不把事后信息作为当前事实。

ResearchRuntime增加可选expected_profile_hash（默认None，兼容既有显式P4调用）。Analysis传完整冻结档案hash，在Runtime读取后及凭据异步读取后的最终同步factory构造口再次核对，随后只使用同一个不可变档案对象；endpoint/type/retention/启用状态/凭据引用变化都失败，不重读后换到B。该预检不同于预算资金预留：预算比较与预留必须在同一SQL事务中锁住，不能仅加一次预检。

具名Event门回归覆盖预算预检后与最终事务前同版本不同内容策略切换；研究进入Runtime前与credential await期间的endpoint/type/retention/停用漂移；混合有效+未来/过期/无效Evidence的全部九次模型正文。没有固定等待或放宽断言，没有新增真实限额/源/付费授权。

### 模型最后出站边界补充（本ADR首次交付内，2026-10-28）

LLMGatewayRequest另有可选expected_model_profile_hash，默认None保持旧通用调用兼容。Analysis强制附加完整冻结模型档案hash；网关在credential await后及预算reserve await后最后核对同一档案完整内容/启用状态，只使用原不可变档案和已取凭据，不切换B。最后核验返回后到HTTP调用之间无其他应用异步操作；不是只在模型解析时预检。

明确尚未进入HTTP的档案漂移才允许release_before_egress：SQL事务锁预留与日/任务账本，原子释放全部预占，保留预留历史为RELEASED_BEFORE_EGRESS；重复释放幂等，已结算预留拒绝释放，不创建伪造provider用量。Analysis步骤记录BLOCKED、egress=false、cost_unconfirmed=false。此已知未出站路径不同于ADR0014的未知调用失败：一旦进入HTTP，超时/坏响应/取消等仍保留保守预占，不伪造零费用。没有新表、迁移、依赖、真实预算或授权变化。
