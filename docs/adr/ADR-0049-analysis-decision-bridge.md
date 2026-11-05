# ADR-0049 — 显式资格与完整链的Analysis Decision桥接

- 状态：Accepted（既有主规范/ADR0003/0006/0007/0011/0043下工程实现；不选择真实投资参数或激活Strategy）
- 日期：2026-11-04
- Work Item：MVP-206；扩展205以后新增路径，不改写任何旧Shadow历史。

## 决策与安全边界

205数字PASS不能替代投资质量、时点、组合适配及授权。新增严格版本化StrategyDecisionRules读取已有具体StrategyVersion的显式范围、有效期、各闸门完整规则与复核间隔，不带默认真实阈值，不按positive角色或一个总分自动推导通过。规则和gate数值来源通过typed application端口读取，不从模型正文解析数字，不接受客户端verified布尔；缺失/不合格/漂移/未来/到期/未批准Strategy或Policy均具名BLOCKED。

真实合格来源尚未接入时，完整正常路径仅用明确SYNTHETIC_FIXTURE、固定合成已批准Policy/Strategy、真正Evidence/Thesis/角色/Risk/Sizing证明；REFERENCE_ONLY、TEST_DEFAULT及未授权真实配置不升级。资格和规则只读，无UI/API自动批准Policy/Strategy或授予来源资格的入口。当前Strategy规则版本与source port仅支持明确simulation-only完整链，真实资格扩展须另行审查；合成值不是实际投资建议。

合格路径通过同一事务构建标准不可变InvestmentDecision、Evidence正规化关联、Analysis关联、Audit/Event/Outbox；不得调用自建UOW的旧JournalWriter后另事务补链接。Decision进入PENDING_APPROVAL，只有既有301明确具名人工approve/reject/revoke生效，无自动批准/订单。标准Sizer输出重建、固定Policy/Strategy/Thesis/委员会与全引用、账本hash、TTL及最后时点重新核验，Risk Veto不可覆盖；REDUCE/EXIT保留独立降风险例外。

SCHEDULED_SHADOW/daily runtime marker只授权影子分析与费用，不授予生成可审批Decision的权限。桥接依据持久Run实际来源与intent失败关闭，不能让客户端传false/遗漏marker绕过；此边界须真实PG/UI回归。

## 固定来源与显式动作实现

采用后置显式准备：原Analysis终态之后，用户从该Run原冻结Evidence选择原时点已存在的资格/具体已HUMAN批准Strategy，单独确认生成待审阅Decision。原Shadow不可变；零额外模型调用，准备不代表人工批准。固定Strategy Prompt bundle与实际七角色Prompt身份一致；Risk模型高/严重风险不由数字PASS覆盖。Worker在原Opinion事务写全部引用的正规FK关联，不追补旧历史。

prepare保存只追加request/revision尝试，成功Run最多一个Decision；失败候选以savepoint回滚标准记录后保存BLOCKED。人工批准桥接Decision还必须在同事务重核当前pending容量，账本与Position phantom及批准/执行并发写均锁定；授权读取完成后使用同一最终时间写不可变批准。REDUCE/EXIT的Risk Veto例外只在明确确认后追加新的标准Sizer副本记录，原Sizer不变。

## 兼容、迁移与恢复

新typed字段仅明确使用时参与canonical请求身份，旧请求/旧Shadow照常读取。旧Strategy rules_json未满足新严格协议时显示缺项，不填默认、猜规则或原地改版本。新关联/资格快照只追加，保留FK/唯一/Hash与规范化Evidence；已有历史时拒绝破坏性降级，使用保留表的应用回退/前向修复。

ADR0049/迁移0023已与403预约；0022尚未实际合入时不引用虚假父、不造空迁移，最终单head按真实集成顺序再接线。无新生产依赖、真实付费调用、Owner部署、Policy/Strategy激活或券商执行，auto_trade=false。

## 验证

正常完整合成生产端口/UOW/Worker/UI到301人工动作，缺/未批准/过期/漂移/损坏引用、Role失败、Veto、分仓、规则临界、精确TTL、重复/冲突、取消、事务故障、只追加及迁移恢复具名覆盖。Engineering/Integrated/User Visible与Owner接受分别记录，实现者不自签独立Gate。
