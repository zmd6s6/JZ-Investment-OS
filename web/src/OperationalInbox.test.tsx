import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationalInbox } from "./OperationalInbox";

const empty = (state: string, message: string, items: unknown[] = []) =>
  ({ state, message, items, limited: false });
const inbox = (overrides: Record<string, unknown> = {}) => ({
  schema_version: "1.0", as_of: "2026-11-11T00:00:00Z", auto_trade: false,
  pending_approvals: empty("EMPTY", "没有符合条件的持久化记录。"),
  degraded_runs: empty("EMPTY", "没有符合条件的持久化记录。"),
  action_required: empty("NOT_PROVIDED", "尚无独立来源"),
  hold_watch: empty("NOT_PROVIDED", "尚无独立来源"),
  new_opportunity: empty("NOT_PROVIDED", "尚无独立来源"),
  risk_veto: empty("NOT_PROVIDED", "尚无独立来源"),
  ...overrides,
});
afterEach(() => vi.unstubAllGlobals());
describe("MVP-405 operational inbox", () => {
  it("reads persisted pending and failed sections and refreshes without writes", async () => {
    const mock = vi.fn().mockResolvedValue({ ok: true, json: async () => inbox({
      pending_approvals: empty("AVAILABLE", "来自持久化记录", [{
        source_id: "id-1", source: "DECISION", status: "PENDING_APPROVAL",
        observed_at: "2026-11-11T00:00:00Z", detail_url: "/decisions", description: "TEST · BUY",
      }]),
    }) });
    vi.stubGlobal("fetch", mock);
    render(<OperationalInbox />);
    expect(await screen.findByRole("link", { name: "TEST · BUY" })).toHaveAttribute("href", "/decisions");
    fireEvent.click(screen.getByRole("button", { name: "刷新运营状态" }));
    await waitFor(() => expect(mock).toHaveBeenCalledTimes(2));
    expect(mock.mock.calls.every(([url, options]) => url === "/api/v1/operational-inbox" && !options?.method)).toBe(true);
  });

  it("distinguishes empty, unsupported, and failed sections", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => inbox({
      degraded_runs: empty("ERROR", "月度来源不可用"),
    }) }));
    render(<OperationalInbox />);
    expect(await screen.findByText("月度来源不可用")).toBeInTheDocument();
    expect(screen.getAllByText("未提供")).toHaveLength(4);
    expect(screen.getAllByText("暂无记录")).toHaveLength(1);
  });

  it("rejects malformed or failed responses instead of showing fabricated zero", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
    render(<OperationalInbox />);
    expect(await screen.findByRole("alert")).toHaveTextContent("无法确认当前运营状态");
    expect(screen.queryByText("暂无记录")).not.toBeInTheDocument();
  });
});
