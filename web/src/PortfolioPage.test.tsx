import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PortfolioPage } from "./PortfolioPage";

type Portfolio = {
  portfolio_id: string;
  name: string;
  base_currency: string;
  cash_balance: string;
  status: string;
  as_of: string;
  missing_pricing: boolean;
  positions: unknown[];
};

const portfolio = (id: string, name: string, cash = "0"): Portfolio => ({
  portfolio_id: id,
  name,
  base_currency: "CNY",
  cash_balance: cash,
  status: "ACTIVE",
  as_of: "2026-10-09T00:00:00Z",
  missing_pricing: true,
  positions: [],
});

const jsonBody = (body: unknown, ok = true, status = ok ? 200 : 500) => ({
  ok,
  status,
  json: () => Promise.resolve(body),
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  try {
    sessionStorage.clear();
  } catch {
    /* ignore */
  }
});

function currentPortfolioName(): string {
  // First stat-card strong is 当前组合 value.
  const card = document.querySelector(".stat-card strong");
  return card?.textContent?.trim() ?? "";
}

describe("PortfolioPage stale response protection", () => {
  it("keeps the newly created portfolio when an older list response arrives later", async () => {
    const oldList = [portfolio("old-id", "旧组合")];
    const created = portfolio("new-id", "新组合", "1000");
    const newList = [created, ...oldList];
    const pendingLists: ((value: unknown) => void)[] = [];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "POST" && url === "/api/v1/portfolios") {
          return Promise.resolve(jsonBody(created, true, 201));
        }
        if (typeof url === "string" && url.includes("import-audits")) {
          return Promise.resolve(jsonBody([]));
        }
        if (url === "/api/v1/portfolios") {
          const p = deferred<unknown>();
          pendingLists.push(p.resolve);
          return p.promise as Promise<Response>;
        }
        if (typeof url === "string" && url.includes("/policy/review")) {
          return Promise.resolve(
            jsonBody({
              active_policy_version: "none",
              policy_status: "TEST_DEFAULT",
              is_test_default: true,
              limits: [],
              warning: "TEST_DEFAULT",
            }),
          );
        }
        return Promise.resolve(jsonBody({}, false, 404));
      }),
    );

    render(<PortfolioPage />);
    await waitFor(() => expect(pendingLists.length).toBeGreaterThanOrEqual(1));
    for (const resolve of [...pendingLists]) resolve(jsonBody(oldList));
    await waitFor(() => expect(currentPortfolioName()).toBe("旧组合"));

    fireEvent.change(screen.getByLabelText("组合名称"), { target: { value: "新组合" } });
    fireEvent.click(screen.getByRole("button", { name: "创建组合" }));
    await waitFor(() => expect(screen.getByText("组合已创建")).toBeInTheDocument());

    await waitFor(() => expect(pendingLists.length).toBeGreaterThanOrEqual(2));
    pendingLists[pendingLists.length - 1](jsonBody(newList));
    await waitFor(() => expect(currentPortfolioName()).toBe("新组合"));

    // Late stale list responses with only 旧组合 must not steal selection.
    const staleCount = pendingLists.length;
    for (const resolve of [...pendingLists]) resolve(jsonBody(oldList));
    await new Promise((r) => setTimeout(r, 40));
    expect(pendingLists.length).toBeGreaterThanOrEqual(staleCount);
    expect(currentPortfolioName()).toBe("新组合");
  });

  it("keeps B when a real pending list refresh started for A finishes after user selects B", async () => {
    const portfolioA = portfolio("aaa", "合成组合A", "100");
    const portfolioB = portfolio("bbb", "合成组合B", "200");
    let listCalls = 0;
    let finishRefresh!: (value: unknown) => void;
    const lateRefresh = new Promise((resolve) => {
      finishRefresh = resolve;
    });

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url === "/api/v1/portfolios" && !url.includes("import-audits")) {
          listCalls += 1;
          if (listCalls === 1) {
            return Promise.resolve(jsonBody([portfolioA, portfolioB]));
          }
          return lateRefresh as unknown as Response;
        }
        if (init?.method === "PUT" && url === "/api/v1/portfolios/aaa/cash") {
          return Promise.resolve(jsonBody(portfolioA));
        }
        if (typeof url === "string" && url.includes("import-audits")) {
          return Promise.resolve(jsonBody([]));
        }
        if (typeof url === "string" && url.includes("/policy/review")) {
          return Promise.resolve(
            jsonBody({
              active_policy_version: "none",
              policy_status: "TEST_DEFAULT",
              is_test_default: true,
              limits: [],
              warning: "TEST_DEFAULT",
            }),
          );
        }
        return Promise.resolve(jsonBody({}, false, 404));
      }),
    );

    render(<PortfolioPage />);
    await waitFor(() => expect(currentPortfolioName()).toBe("合成组合A"));

    // Start a real in-flight list refresh via 更新现金 → refreshList().
    fireEvent.change(screen.getByLabelText("更新现金（当前组合）"), {
      target: { value: "100" },
    });
    fireEvent.click(screen.getByRole("button", { name: "更新现金", exact: true }));
    await waitFor(() => expect(listCalls).toBe(2));

    // User switches to B while the GET is still pending.
    const chooseB = screen.getByRole("button", { name: /合成组合B/ });
    expect(chooseB).not.toBeDisabled();
    fireEvent.click(chooseB);
    await waitFor(() => expect(currentPortfolioName()).toBe("合成组合B"));

    // Deliver the still-pending GET with both portfolios (A first).
    await act(async () => {
      finishRefresh(jsonBody([portfolioA, portfolioB]));
      await lateRefresh;
    });
    expect(currentPortfolioName()).toBe("合成组合B");
  });

  it("sends csv preview only to the selected portfolio and does not loop list loads", async () => {
    const portfolioA = portfolio("aaa", "组合A");
    const portfolioB = portfolio("bbb", "组合B");
    const previewUrls: string[] = [];
    let listCount = 0;

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (typeof url === "string" && url.includes("/policy/review")) {
          return Promise.resolve(
            jsonBody({
              active_policy_version: "none",
              policy_status: "TEST_DEFAULT",
              is_test_default: true,
              limits: [],
              warning: "TEST_DEFAULT",
            }),
          );
        }
        if (typeof url === "string" && url.includes("/csv/preview")) {
          previewUrls.push(url);
          return Promise.resolve(
            jsonBody({
              total_rows: 1,
              can_commit: false,
              requires_conflict_policy: false,
              content_hash: "h",
              positions_hash: "p",
              valid: [],
              invalid: [{ line_number: 2, status: "INVALID", reason: "坏行" }],
              duplicates: [],
              conflicts: [],
            }),
          );
        }
        if (typeof url === "string" && url.includes("import-audits")) {
          return Promise.resolve(jsonBody([]));
        }
        if (init?.method === "POST" && url === "/api/v1/portfolios") {
          return Promise.resolve(jsonBody(portfolioB, true, 201));
        }
        if (url === "/api/v1/portfolios") {
          listCount += 1;
          return Promise.resolve(jsonBody([portfolioA, portfolioB]));
        }
        return Promise.resolve(jsonBody({}, false, 404));
      }),
    );

    render(<PortfolioPage />);
    await waitFor(() => expect(currentPortfolioName()).toBe("组合A"));
    const listCountAfterMount = listCount;

    fireEvent.click(screen.getByRole("button", { name: /组合B/ }));
    fireEvent.change(screen.getByLabelText("CSV 内容"), {
      target: { value: "market,symbol\nSSE,bad" },
    });
    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    await waitFor(() => expect(screen.getByText("坏行")).toBeInTheDocument());

    expect(previewUrls).toHaveLength(1);
    expect(previewUrls[0]).toContain("/api/v1/portfolios/bbb/csv/preview");
    expect(previewUrls[0]).not.toContain("/aaa/");
    expect(listCount).toBeLessThanOrEqual(listCountAfterMount + 2);
  });
});
