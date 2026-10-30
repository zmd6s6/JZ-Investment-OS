# ADR-0047 — 冻结数值输入与影子分析确定性Risk/Sizing

- 状态：Accepted（既有主规范/ADR0003/0006/0007/0011约束下工程实现，不选择真实Policy参数或数据授权）
- 日期：2026-10-29
- Work Item：MVP-205；不替代已有ADR，不实现MVP-206。

## 决策

分析Worker通过typed application port读取显式选定、只追加且绑定具体Portfolio身份/PolicyVersion的数值来源快照。每一数值保留Evidence链接、source/metric、四业务时间与到期；不得解析新闻/LLM解释补数字。当前真实来源仍MANUAL/REFERENCE_ONLY，不能自报verified或升级为交易级。正常完整路径用清楚标SYNTHETIC_FIXTURE的隔离夹具通过同一SQL/Worker/UI路径，始终simulation_only=true、不可审批。

使用已有Decimal估值、RiskAssessment、SizingRequest/size_position及Core/Tactical规则；NAV/权重/集中度由冻结P5数量/现金和完整价格计算，预占容量由已保存批准/执行历史确定性计算，不默认为零。跨币种缺合法FX仍明确FX_REQUIRED，本轮不接新真实FX源。波动、流动性、相关性、风险预算及价格/全部来源任一缺失、未来、过期、异标的或固定输入不匹配则失败关闭；不存在“参考NAV可算所以Risk PASS”的路径。

Policy 1.0继续读取且无默认Sizing系数；兼容解析新增1.1文档，只有显式1.1才可携带完整typed sizing规则。所有系数来自具体已批准的PolicyVersion配置/hash，未提供就BLOCKED。原TEST_DEFAULT配置文件和值不改，不提供自动激活/批准Policy入口。新增可选协议字段保留旧调用与旧历史，输入扩展仅在明确使用时参与请求身份，不改变旧无扩展请求幂等含义。

RISK使用完整合法数值产生标准RiskAssessment（含具名flags/Evidence/expiry/解除条件），不完整时保存UNKNOWN原因及空引用而非伪造记录；CIO给出候选Action后，SIZING基于固定Risk/Policy及PortfolioIntent调用纯域公式，保存标准PositionSizingRun全部request/formula/output/hash/caps/舍入。模型意见不计算数字、不覆盖Risk Veto。运行与这些标准产物通过正规化append-only FK关联，不以一个万能JSON表替代主表。

最终仍为Shadow，不创建InvestmentDecision或批准/执行记录。即使合成输入完整且计算成功，仍明确显示206桥接未实现、execution_allowed=false、auto_trade=false；不将工程正常值宣称Owner真实投资资格。公共API只增加只读数值来源选择/固定结果，不能提交来源资格或真实Policy批准。

## 迁移 / 恢复 / 验证

0021线性基于已合入0020，新增数值来源/规范化Evidence及分析Risk/Sizing链接，标准风险/仓位主表复用；空库/上一版升级、append-only、FK/唯一/失败事务、保留历史的降级拒绝具名验证。回滚入口可停新能力，已有历史保留前向修复。无新生产依赖、真实调用、Owner部署或交易权限。

必须证明：同输入逐位一致；正常完整合成源与实际Worker/UI数字回读；缺项/人工参考/TEST_DEFAULT/未批准Policy、前视/过期、分仓、集中度/Veto/减仓/舍入、FX/预占容量、故障/取消/重复/不可变回归。最终HEAD完整必要验证与独立Gate另核，不签Owner产品接受。
