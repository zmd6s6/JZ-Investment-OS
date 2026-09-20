import { useEffect, useState } from "react";

type Page = "资产组合" | "机会池" | "观察清单" | "决策日志";
type Tone = "neutral" | "warning" | "danger" | "positive";
const pages: readonly Page[] = ["资产组合", "机会池", "观察清单", "决策日志"];
const maxDailyReportCharacters = 12_000;
type TaskRun = { status?: unknown };
type DailyReport = { as_of?: unknown; rendered_markdown?: unknown; simulation_only?: unknown };
type DailyReportPreview = { asOf: string; markdown: string };

function operationalStatus(runs: unknown): string {
  if (!Array.isArray(runs) || runs.length === 0) return "暂无已完成的调度任务";
  const status = (runs[0] as TaskRun).status;
  if (status === "SUCCEEDED") return "最近一次任务运行成功";
  if (status === "FAILED") return "最近一次任务运行失败——请查看已脱敏的 TaskRun 记录";
  return "最近一次任务尚未完成或状态未知";
}

function dailyReportPreview(report: unknown): DailyReportPreview | null {
  if (typeof report !== "object" || report === null) return null;
  const { as_of: asOf, rendered_markdown: markdown, simulation_only: simulationOnly } = report as DailyReport;
  if (simulationOnly !== true || typeof asOf !== "string" || Number.isNaN(Date.parse(asOf)) || typeof markdown !== "string" || !markdown.trim() || markdown.length > maxDailyReportCharacters || !markdown.includes("SIMULATION / NO AUTO TRADE")) return null;
  return { asOf, markdown };
}

export function App() {
  const [page, setPage] = useState<Page>("资产组合");
  const [operation, setOperation] = useState("正在加载调度状态");
  const [reportAsOf, setReportAsOf] = useState("正在加载日报截至时间");
  const [reportPreview, setReportPreview] = useState("正在加载日报快照");
  useEffect(() => {
    void fetch("/api/v1/task-runs?limit=1").then(async (response) => response.ok ? response.json() : Promise.reject(new Error("unavailable"))).then((runs: unknown) => setOperation(operationalStatus(runs))).catch(() => setOperation("调度状态不可用——未提交任何操作"));
    void fetch("/api/v1/reports/daily/latest").then(async (response) => response.ok ? response.json() : Promise.reject(new Error("unavailable"))).then((report: unknown) => {
      const preview = dailyReportPreview(report);
      if (preview === null) { setReportAsOf("日报无效——继续保留数据陈旧保护"); setReportPreview("日报预览不可用——未提交任何操作"); return; }
      setReportAsOf(`合成日报截至：${preview.asOf}`); setReportPreview(preview.markdown);
    }).catch(() => { setReportAsOf("日报不可用——继续保留数据陈旧保护"); setReportPreview("日报预览不可用——未提交任何操作"); });
  }, []);
  return <main className="app-shell">
    <header className="hero"><div><p className="eyebrow">PERSONAL INVESTMENT WORKSPACE · SYNTHETIC</p><h1>个人 AI 投资操作系统</h1><p className="hero-copy">把研究、风险、决策与复盘放在同一条可追溯的工作流里。</p></div><p className="safety-banner">模拟运行 / 禁止自动交易（SIMULATION / NO AUTO TRADE）</p></header>
    <section aria-label="今日优先事项" className="priority-bar"><div><span className="priority-kicker">今日优先事项</span><strong>先处理风险否决与待审批项，再阅读研究结论。</strong></div><span className="read-only">只读模式 · 不会提交订单</span></section>
    <section aria-label="安全与数据状态" className="status-grid"><Status label="数据截至时间" value={reportAsOf} tone="warning" /><Status label="证据新鲜度" value="存在过期证据——结论仅供复核" tone="warning" /><Status label="风险否决" value="已生效——禁止增加风险暴露" tone="danger" /><Status label="人工审批" value="1 项待审批；未提交订单" tone="warning" /><Status label="运行异常" value={operation} tone={operation.includes("成功") ? "positive" : "warning"} /></section>
    <nav aria-label="主导航" className="navigation">{pages.map((candidate, index) => <button aria-current={candidate === page ? "page" : undefined} aria-label={candidate} className={candidate === page ? "selected" : ""} key={candidate} onClick={() => setPage(candidate)} type="button"><span aria-hidden="true">0{index + 1}</span>{candidate}</button>)}</nav>
    <section className="workspace" aria-live="polite">{page === "资产组合" && <PortfolioView reportAsOf={reportAsOf} reportPreview={reportPreview} />}{page === "机会池" && <OpportunitiesView />}{page === "观察清单" && <WatchlistView />}{page === "决策日志" && <DecisionJournalView />}</section>
    <footer>所有数值与标的均为合成演示数据；不使用真实组合、券商凭据或实盘订单。</footer>
  </main>;
}
function Status({ label, value, tone }: { label: string; value: string; tone: Tone }) { return <div className={`status ${tone}`}><strong>{label}</strong><span>{value}</span></div>; }
function PortfolioView({ reportAsOf, reportPreview }: { reportAsOf: string; reportPreview: string }) { return <><SectionTitle title="资产组合" eyebrow="今日概览" description="Core 与 Tactical 仓位分开呈现；当前仅为合成演示，不能用于交易。" /><div className="metric-grid"><Metric label="模拟净值" value="¥1,000,000" hint="TEST_DEFAULT · 合成" /><Metric label="风险暴露" value="42.0%" hint="低于模拟上限 · 非真实规则" /><Metric label="现金缓冲" value="58.0%" hint="等待人工策略确认" /><Metric label="待处理事项" value="2" hint="风险与审批优先" emphasis /></div><div className="two-column"><Panel title="仓位结构" subtitle="合成示例 · 非投资建议"><Allocation label="Core 长期仓" value="30%" width="30" /><Allocation label="Tactical 战术仓" value="12%" width="12" /><Allocation label="现金及待定" value="58%" width="58" muted /></Panel><Panel title="日报快照" subtitle={`快照状态：${reportAsOf}`}><pre className="report-preview">{reportPreview}</pre></Panel></div></>; }
function OpportunitiesView() { return <><SectionTitle title="机会池" eyebrow="研究漏斗" description="只呈现合成研究队列；任何建议均需证据、风险校验和人工审批。" /><div className="metric-grid"><Metric label="新发现" value="3" hint="待证据初筛" /><Metric label="观察中" value="2" hint="等待触发条件" /><Metric label="可研究" value="1" hint="仍未获批准" /><Metric label="可执行" value="0" hint="自动交易已禁用" emphasis /></div><Panel title="合成机会队列" subtitle="按研究状态排列，不代表推荐"><DataTable headers={["标的", "研究状态", "关键前提", "证据状态"]} rows={[["CN-SYN-001", "观察", "等待公告确认", "部分过期"], ["US-SYN-002", "研究中", "等待风险复核", "可用"], ["CN-SYN-003", "搁置", "缺少授权数据", "不可用"]]} /></Panel></>; }
function WatchlistView() { return <><SectionTitle title="观察清单" eyebrow="Thesis 监控" description="监控条件和证据缺口必须显式记录；缺数据不会被替换成推测。" /><div className="watch-grid"><WatchCard code="CN-SYN-001" state="需要复核" condition="下一次已授权披露可用后，重新检查核心假设。" evidence="一项证据已过期" /><WatchCard code="US-SYN-002" state="等待触发" condition="只有风险否决解除后，才可进入下一步研究。" evidence="证据链完整" /><WatchCard code="CN-SYN-003" state="数据缺失" condition="未接入真实数据提供方，维持搁置状态。" evidence="无可用证据" /></div></>; }
function DecisionJournalView() { return <><SectionTitle title="决策日志" eyebrow="可追溯记录" description="展示决策链条；审批不是成交，风险否决不能被任何页面覆盖。" /><Panel title="合成决策时间线" subtitle="不可变历史的阅读视图"><ol className="timeline"><li><b>证据快照</b><span>已记录来源、业务时间与内容哈希</span></li><li><b>风险评估</b><span>风险否决生效；禁止 BUY / ADD 与增加暴露</span></li><li><b>决策提案</b><span>状态：等待人工审批；未创建任何订单</span></li><li><b>执行记录</b><span>无执行记录；V1 自动交易始终关闭</span></li></ol></Panel></>; }
function SectionTitle({ title, eyebrow, description }: { title: string; eyebrow: string; description: string }) { return <div className="section-title"><p>{eyebrow}</p><h2>{title}</h2><span>{description}</span></div>; }
function Metric({ label, value, hint, emphasis = false }: { label: string; value: string; hint: string; emphasis?: boolean }) { return <div className={`metric ${emphasis ? "emphasis" : ""}`}><span>{label}</span><strong>{value}</strong><small>{hint}</small></div>; }
function Panel({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) { return <article className="panel"><div className="panel-heading"><div><h3>{title}</h3><p>{subtitle}</p></div><span className="verified">只读</span></div>{children}</article>; }
function Allocation({ label, value, width, muted = false }: { label: string; value: string; width: string; muted?: boolean }) { return <div className="allocation"><div><span>{label}</span><b>{value}</b></div><div className={`bar ${muted ? "muted" : ""}`}><i style={{ width: `${width}%` }} /></div></div>; }
function DataTable({ headers, rows }: { headers: string[]; rows: string[][] }) { return <div className="table-wrap"><table><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row[0]}>{row.map((value) => <td key={value}>{value}</td>)}</tr>)}</tbody></table></div>; }
function WatchCard({ code, state, condition, evidence }: { code: string; state: string; condition: string; evidence: string }) { return <article className="watch-card"><div><span className="instrument">{code}</span><span className="state-chip">{state}</span></div><h3>{condition}</h3><p>证据状态：{evidence}</p><small>合成标的 · 不构成投资建议</small></article>; }
