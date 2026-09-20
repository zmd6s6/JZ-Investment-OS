import { useEffect, useState } from "react";

type Page = "资产组合" | "机会池" | "观察清单" | "决策日志";

const pages: readonly Page[] = ["资产组合", "机会池", "观察清单", "决策日志"];

const pageCopy: Record<Page, { heading: string; detail: string }> = {
  资产组合: {
    heading: "资产组合",
    detail: "这里展示 Core/Tactical 持仓、风险状态与待人工审批事项。",
  },
  机会池: {
    heading: "机会池",
    detail: "这里展示合成 DISCOVER、WATCH、SETUP 与 BUYABLE 漏斗变化。",
  },
  观察清单: {
    heading: "观察清单",
    detail: "这里展示 Thesis 状态、缺失条件与触发器。",
  },
  决策日志: {
    heading: "决策日志",
    detail: "这里保留 Evidence、版本、审批、执行记录与后续复盘的可追溯链路。",
  },
};

type TaskRun = { status?: unknown };
type DailyReport = { as_of?: unknown; rendered_markdown?: unknown; simulation_only?: unknown };
type DailyReportPreview = { asOf: string; markdown: string };
const maxDailyReportCharacters = 12_000;

function operationalStatus(runs: unknown): string {
  if (!Array.isArray(runs) || runs.length === 0) {
    return "暂无已完成的调度任务";
  }
  const status = (runs[0] as TaskRun).status;
  if (status === "SUCCEEDED") {
    return "最近一次任务运行成功";
  }
  if (status === "FAILED") {
    return "最近一次任务运行失败——请查看已脱敏的 TaskRun 记录";
  }
  return "最近一次任务尚未完成或状态未知";
}

function dailyReportPreview(report: unknown): DailyReportPreview | null {
  if (typeof report !== "object" || report === null) {
    return null;
  }
  const { as_of: asOf, rendered_markdown: markdown, simulation_only: simulationOnly } = report as DailyReport;
  if (
    simulationOnly !== true ||
    typeof asOf !== "string" ||
    Number.isNaN(Date.parse(asOf)) ||
    typeof markdown !== "string" ||
    !markdown.trim() ||
    markdown.length > maxDailyReportCharacters ||
    !markdown.includes("SIMULATION / NO AUTO TRADE")
  ) {
    return null;
  }
  return { asOf, markdown };
}

export function App() {
  const [page, setPage] = useState<Page>("资产组合");
  const [operation, setOperation] = useState("正在加载调度状态");
  const [reportAsOf, setReportAsOf] = useState("正在加载日报截至时间");
  const [reportPreview, setReportPreview] = useState("正在加载日报快照");
  const current = pageCopy[page];

  useEffect(() => {
    void fetch("/api/v1/task-runs?limit=1")
      .then(async (response) => (response.ok ? response.json() : Promise.reject(new Error("unavailable"))))
      .then((runs: unknown) => setOperation(operationalStatus(runs)))
      .catch(() => setOperation("调度状态不可用——未提交任何操作"));
    void fetch("/api/v1/reports/daily/latest")
      .then(async (response) => (response.ok ? response.json() : Promise.reject(new Error("unavailable"))))
      .then((report: unknown) => {
        const preview = dailyReportPreview(report);
        if (preview === null) {
          setReportAsOf("日报无效——继续保留数据陈旧保护");
          setReportPreview("日报预览不可用——未提交任何操作");
          return;
        }
        setReportAsOf(`合成日报截至：${preview.asOf}`);
        setReportPreview(preview.markdown);
      })
      .catch(() => {
        setReportAsOf("日报不可用——继续保留数据陈旧保护");
        setReportPreview("日报预览不可用——未提交任何操作");
      });
  }, []);

  return (
    <main>
      <header>
        <p className="safety-banner">模拟运行 / 禁止自动交易（SIMULATION / NO AUTO TRADE）</p>
        <h1>个人 AI 投资操作系统</h1>
        <p>只读个人运营视图；本界面中的建议绝不会被直接执行。</p>
      </header>
      <section aria-label="安全与数据状态" className="status-grid">
        <Status label="数据截至时间" value={reportAsOf} warning />
        <Status label="证据新鲜度" value="已过期——需要刷新" warning />
        <Status label="风险否决" value="已生效——禁止增加风险暴露" warning />
        <Status label="人工审批" value="1 项待审批；未提交订单" />
        <Status label="运行异常" value={operation} warning />
      </section>
      <nav aria-label="主导航">
        {pages.map((candidate) => (
          <button
            aria-current={candidate === page ? "page" : undefined}
            className={candidate === page ? "selected" : ""}
            key={candidate}
            onClick={() => setPage(candidate)}
            type="button"
          >
            {candidate}
          </button>
        ))}
      </nav>
      <article>
        <h2>{current.heading}</h2>
        <p>{current.detail}</p>
        <section aria-label="日报快照">
          <h3>日报快照</h3>
          <pre>{reportPreview}</pre>
        </section>
        <p className="placeholder">未使用真实组合、券商凭据或实盘订单。</p>
      </article>
    </main>
  );
}

function Status({ label, value, warning = false }: { label: string; value: string; warning?: boolean }) {
  return (
    <div className={warning ? "status warning" : "status"}>
      <strong>{label}</strong>
      <span>{value}</span>
    </div>
  );
}
