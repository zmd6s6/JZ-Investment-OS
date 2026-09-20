import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("keeps safety signals visible across pages and reports a failed task run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/v1/task-runs?limit=1") {
          return Promise.resolve(new Response(JSON.stringify([{ status: "FAILED" }])));
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({ as_of: "2026-09-20T20:00:00Z", simulation_only: true }),
          ),
        );
      }),
    );
    render(<App />);

    expect(screen.getByText("SIMULATION / NO AUTO TRADE")).toBeVisible();
    expect(screen.getByText("ACTIVE — increased exposure blocked")).toBeVisible();
    expect(screen.getByText("1 pending; no order submitted")).toBeVisible();
    await waitFor(() =>
      expect(screen.getByText("Latest task run failed — review the sanitized TaskRun record")).toBeVisible(),
    );
    expect(screen.getByText("Synthetic Daily report as-of: 2026-09-20T20:00:00Z")).toBeVisible();

    for (const page of ["Opportunities", "Watchlist", "Decision Journal"]) {
      fireEvent.click(screen.getByRole("button", { name: page }));
      expect(screen.getByRole("heading", { name: page })).toBeVisible();
      expect(screen.getByRole("button", { name: page })).toHaveAttribute("aria-current", "page");
      expect(screen.getByText("SIMULATION / NO AUTO TRADE")).toBeVisible();
    }
  });

  it("fails closed when the task-run API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network unavailable")));
    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("Scheduler status is unavailable — no action was submitted")).toBeVisible(),
    );
  });

  it("keeps stale-data safeguards when the Daily report is malformed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/v1/task-runs?limit=1") {
          return Promise.resolve(new Response(JSON.stringify([{ status: "SUCCEEDED" }])));
        }
        return Promise.resolve(
          new Response(JSON.stringify({ as_of: "not-a-time", simulation_only: false })),
        );
      }),
    );
    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("Daily report is invalid — retain stale-data safeguards")).toBeVisible(),
    );
    expect(screen.getByText("ACTIVE — increased exposure blocked")).toBeVisible();
  });
});
