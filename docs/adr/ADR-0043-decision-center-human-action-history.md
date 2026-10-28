# ADR-0043 — Decision Center 的具名人工动作与手工成交事实

- 状态：Accepted（主规范及ADR0006/0007/0011已经限定的工程实现，不选择真实投资参数）
- 日期：2026-10-28

## 背景与决策

PR07有不可变Decision/批准/执行模型及只读Journal，但没有产品列表/动作UI，也没有完整fees/实际成交时间/note。新增application typed port、独立SQL adapter与router/page；原Decision内容/hash不更新，人工动作在独立append-only receipt按revision保存状态。每个具名确认有request UUID及canonical command hash；同请求同内容重放不重复动作，不同内容冲突。锁定Decision串行检查expected_revision并追加Approval/Execution/receipt/Audit/Event/Outbox，同一事务提交，不能读改写快照冒充不可变历史。

人工批准只接受当前PENDING_APPROVAL且有效完整Policy/Strategy/Thesis/Evidence/Risk/Sizing链；Policy必须有归属的人类批准且当前生效，TEST_DEFAULT不可批准。缺历史字段、空JSON或不完整引用失败关闭。现203 ShadowDecision不是InvestmentDecision，不存在转换或批准接口。

批准TTL来自固定Policy Schema，不由UI输入任意时长；拒绝/撤销保留明确具名动作。状态从不可变动作派生，过期按服务端UTC判定，撤销仅未成交批准允许。手工登记要求当前批准、实际成交时间在有效批准内、累计数量不超过确定性Sizing输出；从冻结Sizing读取approved quantity/reference price，不接受客户端目标数量/风险状态。没有经批准的价格容差时只接受准确参考价，价格不同须新的Decision/批准；这是一项安全边界，不选择真实容差。

Sizing必须携带当时P5现金/分仓版本fingerprint，批准及记录时重新核对，缺失或漂移失败；本页面不补造该输入。实际Sizing生产连接未完整的历史Decision仍可读且展示缺项。完整合成fixture通过真实已有领域Sizing/Decision端口建立数据，不能将测试fixture注入Owner实例或称为当前分析可审批。

手工执行只记事实、无经纪商调用。新增正规化manual_execution_detail附表保存Decimal fees、executed_at（与recorded_at分开）和清洗note；链接既有不可变Execution/Approval。每次局部成交保存自身数量/费用，累计推导完成状态；既有旧记录无新增字段明确缺失，不默认补零或今天日期。

## 替代方案与后果

拒绝覆盖Decision状态/快照、单个万能JSON代替关系、客户端批准TTL/数量/风险布尔、把Shadow转换成可交易Decision，以及为演示绕过真实Policy。采用已存在的本地写Token及明确具名确认，外网部署/完整身份硬化仍按阶段边界留后续；读写错误不泄露SQL或凭据。

## 安全与恢复

迁移0018只新增两表/FK/唯一与append-only守卫；204无0017迁移，直接线性接0016，无空迁移。空表可降级；存在人工历史时拒绝删除，回滚应用保留表并前向修复。没有新依赖、真实Policy激活、真实来源/付费模型、Owner迁移重启或实盘订单。auto_trade=false、Risk Veto不可覆盖。

## 验证契约

正常批准/分次手工登记、拒绝/撤销/到期、无完整链/Veto/超量/价格及输入漂移/乱序、重复请求/并发版本、未鉴权、迁移不可变与保留历史，以及真实浏览器回读fees/时间/引用/失败反馈均须有合成证据。实现者不自签独立Gate。
