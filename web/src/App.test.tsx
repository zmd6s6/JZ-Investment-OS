import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("App", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps safety signals visible across pages and reports a failed task run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify([{ status: "FAILED" }]))),
    );
    render(<App />);

    expect(screen.getByText("SIMULATION / NO AUTO TRADE")).toBeVisible();
    expect(screen.getByText("ACTIVE — increased exposure blocked")).toBeVisible();
    expect(screen.getByText("1 pending; no order submitted")).toBeVisible();
    await waitFor(() =>
      expect(screen.getByText("Latest task run failed — review the sanitized TaskRun record")).toBeVisible(),
    );

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
});
