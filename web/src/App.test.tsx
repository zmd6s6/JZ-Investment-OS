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

    expect(screen.getByText(/模拟运行 \/ 禁止自动交易/)).toBeVisible();
    expect(screen.getByText("已生效——禁止增加风险暴露")).toBeVisible();
    expect(screen.getByText("1 项待审批；未提交订单")).toBeVisible();
    await waitFor(() =>
      expect(screen.getByText("最近一次任务运行失败——请查看已脱敏的 TaskRun 记录")).toBeVisible(),
    );
    expect(screen.getByText("日报无效——继续保留数据陈旧保护")).toBeVisible();
    expect(screen.getByText("日报预览不可用——未提交任何操作")).toBeVisible();

    for (const page of ["机会池", "观察清单", "决策日志"]) {
      fireEvent.click(screen.getByRole("button", { name: page }));
      expect(screen.getByRole("heading", { name: page })).toBeVisible();
      expect(screen.getByRole("button", { name: page })).toHaveAttribute("aria-current", "page");
      expect(screen.getByText(/模拟运行 \/ 禁止自动交易/)).toBeVisible();
    }
  });

  it("fails closed when the task-run API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network unavailable")));
    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("调度状态不可用——未提交任何操作")).toBeVisible(),
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
          new Response(
            JSON.stringify({
              as_of: "not-a-time",
              rendered_markdown: "# Daily\nSIMULATION / NO AUTO TRADE",
              simulation_only: false,
            }),
          ),
        );
      }),
    );
    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("日报无效——继续保留数据陈旧保护")).toBeVisible(),
    );
    expect(screen.getByText("已生效——禁止增加风险暴露")).toBeVisible();
  });

  it("shows a bounded, plain-text Daily report snapshot from the read-only API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/v1/task-runs?limit=1") {
          return Promise.resolve(new Response(JSON.stringify([{ status: "SUCCEEDED" }])));
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              as_of: "2026-09-20T20:00:00Z",
              rendered_markdown: "# Daily Report\nSIMULATION / NO AUTO TRADE\n- **ASSUMPTION**: synthetic",
              simulation_only: true,
            }),
          ),
        );
      }),
    );
    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("合成日报截至：2026-09-20T20:00:00Z")).toBeVisible(),
    );
    expect(screen.getByText(/ASSUMPTION.*synthetic/)).toBeVisible();
    expect(screen.getByRole("heading", { name: "日报快照" })).toBeVisible();
  });
});
