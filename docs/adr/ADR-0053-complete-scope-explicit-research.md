# ADR-0053 — 完整来源筛选的逐候选显式研究

- 状态：Proposed（须实际独立Gate/合入后生效）
- 日期：2026-11-09
- 补充ADR0044/0051，保持原v1协议与历史。

完整来源v2的候选只能通过明确schema_version=2.0研究请求读取原完整运行，不得将1000成员运行转换成旧200成员FunnelRun。v1研究请求仍只读v1；v2只读v2，未知版本Schema拒绝。服务核对冻结候选成员、至多20界限、原候选全部Evidence及相同行情来源，再使用原AnalysisStart及既有证据/模型/预算/出站授权最终闸门，不通过声明来源Evidence补金融资格。

UI复用逐候选组合/模型选择、独立模型与可选资料源许可及可能收费提示；没有批量入口、自动调用或隐式重试。保存v2运行本身仍零出站，其历史deep_research=NOT_PROVIDED不被改写。点击研究以新当前时点重新核验，不能把后来研究作为历史已知。固定原run、候选、全部显式命令/hash的只追加intent复用既有Event/Audit/Outbox和Analysis唯一请求编号；旧intent按v1读取，新intent按v2读取，不覆写旧hash，无新迁移或依赖。入队失败/未知响应仍先刷新，再原内容明确重试。

不新增真实数据授权、Policy、Strategy激活或交易；SOURCE_DECLARED/UNVERIFIED、market_universe=NOT_PROVIDED、auto_trade=false保持。v2周筛选没有接通。回退应用保留所有intent和分析历史，采用前向修复。验证须覆盖版本隔离、非候选/缺Evidence/异来源零intent与排队、幂等/失败恢复，以及独立合成API/PG/Worker/UI，不将合成模型当Owner真实授权。
