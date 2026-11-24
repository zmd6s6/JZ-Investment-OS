# ADR-0060 — AnalysisRun 只读稳定历史分页

- 状态：Accepted（主规范与ADR0041限定范围内工程选择，不改变投资治理或读取权限）
- 日期：2026-11-24
- Work Item：MVP-411；补充ADR0003/0041，不改写已接受ADR。

## 决策

新增`GET /api/v1/analysis/runs/history`，显式portfolio_id、可选immutable instrument_id过滤，固定30项typed1.0页。排序复用原列表的queued_at DESC、UUID ASC，不按可变status/started_at分页。游标携带严格版本namespace、组合、instrument查询和固定order、原排队时间及UUID，Base64URL编码、长度有界；跨查询/错误协议明确422。不引入快照事务或伪造完整总数：新排队记录在刷新首页后可见，已加载历史以原键继续。游标仅为位置，不是授权凭据。

旧tuple JSON最新30列表、cap100内部调用和现exactGET保持原样。既有Analysis GET本来是本地安全读取，沿用原auth middleware；不借本切片改变为calendar/weekly新增的独立认证策略，也不改变POST令牌门禁、HEAD/OPTIONS。API可选过滤不是新的运行时指令。

UI新增加载更早页与完整ID输入，复用PR59 exactGET/原追溯；成功选择更新原run_id/portfolio_id URL供刷新。历史GET不恢复旧模型同意，不增加取消、重试或Bridge资格。分页失败保留已加载行；详情失败卸载旧Trace/Bridge及动作，序列和组合守卫拒绝迟到响应。失败/取消无产物保留真实缺项，不回填。

## 后果、替代与恢复

拒绝扩大原列表limit、offset与mutable状态排序；前者仍有截断，后者不能满足稳定边界。固定30保持当前页面节奏，无新生产依赖、表、索引、迁移、数据库时间语义或Agent Schema变化。回滚应用移除新入口即可，所有历史表与hash保留。

## 验证

具名PG/API覆盖30/31/101/137同queued_at不同UUID、不同started_at、跨组合/查询/namespace/order拒绝、旧tuple/exact/权限兼容和读取前后全库内容相同；真实Worker与105条明确标记seed历史分开。最终实际结果见MVP411工作项，不能将尚未执行的PG/browser或CI宣称通过。
