import { useState } from "react";

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

export function App() {
  const [page, setPage] = useState<Page>("Portfolio");
  const current = pageCopy[page];

  return (
    <main>
      <header>
        <p className="safety-banner">SIMULATION / NO AUTO TRADE</p>
        <h1>Personal AI Investment OS</h1>
        <p>Read-only personal operating view. Recommendations are never executed by this interface.</p>
      </header>
      <section aria-label="Safety and data status" className="status-grid">
        <Status label="Data as-of" value="Synthetic fixture — 2026-09-20T20:00:00Z" />
        <Status label="Evidence freshness" value="STALE — refresh required" warning />
        <Status label="Risk Veto" value="ACTIVE — increased exposure blocked" warning />
        <Status label="Human approvals" value="1 pending; no order submitted" />
        <Status label="Operational exception" value="Daily report job not yet completed" warning />
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
