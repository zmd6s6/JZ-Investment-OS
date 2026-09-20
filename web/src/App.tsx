import { useEffect, useState } from "react";

type Page = "Portfolio" | "Opportunities" | "Watchlist" | "Decision Journal";

const pages: readonly Page[] = ["Portfolio", "Opportunities", "Watchlist", "Decision Journal"];

const pageCopy: Record<Page, { heading: string; detail: string }> = {
  Portfolio: {
    heading: "Portfolio",
    detail: "Core/Tactical positions, risk status, and pending human approvals appear here.",
  },
  Opportunities: {
    heading: "Opportunities",
    detail: "Synthetic DISCOVER, WATCH, SETUP, and BUYABLE funnel changes appear here.",
  },
  Watchlist: {
    heading: "Watchlist",
    detail: "Thesis status, missing conditions, and triggers appear here.",
  },
  "Decision Journal": {
    heading: "Decision Journal",
    detail: "Evidence, versions, approvals, executions, and later reviews remain traceable here.",
  },
};

type TaskRun = { status?: unknown };
type DailyReport = { as_of?: unknown; rendered_markdown?: unknown; simulation_only?: unknown };
type DailyReportPreview = { asOf: string; markdown: string };
const maxDailyReportCharacters = 12_000;

function operationalStatus(runs: unknown): string {
  if (!Array.isArray(runs) || runs.length === 0) {
    return "No completed scheduler run is available";
  }
  const status = (runs[0] as TaskRun).status;
  if (status === "SUCCEEDED") {
    return "Latest task run succeeded";
  }
  if (status === "FAILED") {
    return "Latest task run failed — review the sanitized TaskRun record";
  }
  return "Latest task run is incomplete or has an unknown status";
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
  const [page, setPage] = useState<Page>("Portfolio");
  const [operation, setOperation] = useState("Loading scheduler status");
  const [reportAsOf, setReportAsOf] = useState("Loading Daily report as-of");
  const [reportPreview, setReportPreview] = useState("Loading Daily report snapshot");
  const current = pageCopy[page];

  useEffect(() => {
    void fetch("/api/v1/task-runs?limit=1")
      .then(async (response) => (response.ok ? response.json() : Promise.reject(new Error("unavailable"))))
      .then((runs: unknown) => setOperation(operationalStatus(runs)))
      .catch(() => setOperation("Scheduler status is unavailable — no action was submitted"));
    void fetch("/api/v1/reports/daily/latest")
      .then(async (response) => (response.ok ? response.json() : Promise.reject(new Error("unavailable"))))
      .then((report: unknown) => {
        const preview = dailyReportPreview(report);
        if (preview === null) {
          setReportAsOf("Daily report is invalid — retain stale-data safeguards");
          setReportPreview("Daily report preview is unavailable — no action was submitted");
          return;
        }
        setReportAsOf(`Synthetic Daily report as-of: ${preview.asOf}`);
        setReportPreview(preview.markdown);
      })
      .catch(() => {
        setReportAsOf("Daily report is unavailable — retain stale-data safeguards");
        setReportPreview("Daily report preview is unavailable — no action was submitted");
      });
  }, []);

  return (
    <main>
      <header>
        <p className="safety-banner">SIMULATION / NO AUTO TRADE</p>
        <h1>Personal AI Investment OS</h1>
        <p>Read-only personal operating view. Recommendations are never executed by this interface.</p>
      </header>
      <section aria-label="Safety and data status" className="status-grid">
        <Status label="Data as-of" value={reportAsOf} warning />
        <Status label="Evidence freshness" value="STALE — refresh required" warning />
        <Status label="Risk Veto" value="ACTIVE — increased exposure blocked" warning />
        <Status label="Human approvals" value="1 pending; no order submitted" />
        <Status label="Operational exception" value={operation} warning />
      </section>
      <nav aria-label="Primary">
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
        <section aria-label="Daily report snapshot">
          <h3>Daily report snapshot</h3>
          <pre>{reportPreview}</pre>
        </section>
        <p className="placeholder">No production portfolio, brokerage credential, or live order is used.</p>
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
