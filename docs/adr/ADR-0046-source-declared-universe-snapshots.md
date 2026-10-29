# ADR0046 — 来源声明的不可变成员快照与精确筛选关联

- 状态：Accepted（root明确批准的MVP-402受限工程续接，不改变投资治理）
- 日期：2026-10-29
- 补充ADR0003/0008/0038/0040/0044/0045；不改写已接受ADR。

## 边界与协议

新增版本化UniverseSnapshot来源集合导入，不是已授权市场全集提供方。CSV首行严格market,symbol；仅精确解析已登记身份，不自动登记、不使用目录或Watchlist定义全集。来源必须明确名称、版本、locator、市场、覆盖定义、声明数量、完整性级别和observed/effective/available时间；确认时生成ingested_at。四时间均以UTC保留，Evidence持久时间使用timestamptz；禁止未来来源时间及早于来源/本次入库的绑定查询。

完整性仅为DECLARED_COMPLETE/PARTIAL/UNKNOWN来源声明；origin=SOURCE_DECLARED、verification=UNVERIFIED、market_universe=NOT_PROVIDED始终保留。声明完整不证明真实市场覆盖、合法性由系统独立核实或任何其他时点的全集。覆盖仅按原来源定义/生效时点解释，不自动更新成员或补造有效期。目录只是身份解析，不是覆盖权威。

预览不写入；确认必须分别明确合法使用与理解来源声明边界，原UTF8提交文本hash与冻结成员hash参与预览hash，预览后来源/身份变化须重做确认。CSV不访问locator、外网或模型，上传只接受有效UTF8文本；未知、重复、混市场、非CNY、数量不符、无日期等整批失败，不静默丢弃或截断。100000字符/1000成员为独立上传资源护栏，不是投资筛选阈值或“全市场大小”。

绑定命令只接受snapshot_id/hash与用户明确查询来源/条件，不接受成员子集。所有成员精确派生为现有FunnelQuery，保留200输入与20候选上限；201及以上成员可保存并查看，但不能完整筛选，不采前200项、不分页拼候选。范围仍为有限显式集合，原筛选Scope/全市场能力标记不升级。空筛选时点明确表示首次成功时的服务器时间，回执保存实际as_of；同请求重放读取原结果。

## 持久化与故障

0020→0019增加只追加Snapshot、正规成员外键及FunnelRun/Event来源关联。文件和来源声明使用MARKET类Evidence/ResearchArtifact存证，但只证明用户提供的成员声明，不替代行情/年报事实，不加入候选金融Evidence计数或解除Risk/Sizing闸门。三源业务时间与来源工件保留，ingested由服务器确认，读回核对内容hash、成员、文件和Evidence链。

导入Snapshot/成员/Evidence/工件/Audit/Event/Outbox同UOW；请求同内容重放、异内容拒绝，证据内容锁防止并发重复Evidence。确认时共享锁重核精确目录身份，修改目录不改旧快照。绑定只读prepare后，FunnelRun与来源关联/Audit/Event/Outbox同UOW；旧手选运行不能事后graft来源。失败全部回滚，未知回执须同内容同request_id明确重试，无自动重播。

生产API与本地weekly factory共同注入类型化ScopeValidator，对保留的universe_snapshot locator核对精确id/hash/来源名称/全部成员与四时间；业务as_of早于成员导入或可用时明确失败且无周产物，不能借weekly模板绕过。旧非快照手选查询兼容。直接origin只说明本导入入口的关联；null不证明某个后续周运行是手选或全市场。

原manual/weekly/逐候选研究保持；周配置须另行保存且默认暂停，深研仍逐次同意。导入或绑定均固定零外网/模型/费用、auto_trade=false，不激活Policy/Strategy，不创建Decision或订单，不新增真实源授权。

## 验证与恢复

具名正常/失败/200与201/身份漂移/并发幂等/Evidence去重/Outbox回滚/只追加/精确来源关联与真实API/DB/UI合成证据；不能将来源声明或合成覆盖称为全市场已证明。空三表可降回0019并保留其他业务资料；有快照历史时拒绝降级，保留并前向修复。不操作Owner实例或真实数据。
