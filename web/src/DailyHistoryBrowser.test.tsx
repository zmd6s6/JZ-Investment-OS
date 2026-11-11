import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { DailyHistoryBrowser } from "./DailyHistoryBrowser";

const id = (value: number) => `00000000-0000-0000-0000-${String(value).padStart(12, "0")}`;
const config = (value: number) => ({ schedule_id: id(value), revision_id: id(500), version: 2, enabled: true, revoked: false, blocker: null, prepared: { command: { name: `合成每日${value}` }, members: [{ name: "合成标的", symbol: "SYNTH" }], calendar_source: "合成日历", calendar_version: "v1" } });
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

test("older authorization is paginated, freshly located and explicitly paused with its exact version", async () => {
  let paused = false;
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const path = String(url);
    if (init?.method === "POST") { paused = true; return response({ ...config(21), version: 3, enabled: false }); }
    if (path.includes("/configurations/")) return response({ ...config(21), version: paused ? 3 : 2, enabled: !paused });
    if (path.includes("offset=20")) return response([config(21)]);
    return response(Array.from({ length: 20 }, (_, index) => config(index + 1)));
  });
  render(<DailyHistoryBrowser />);
  await screen.findByText(/合成每日1 ·/);
  fireEvent.click(screen.getByRole("button", { name: "加载更多每日历史" }));
  await screen.findByText(/合成每日21 ·/);
  fireEvent.click(screen.getByRole("button", { name: "查看此授权" }));
  const selected = await screen.findByRole("article", { name: "所选每日授权" });
  expect(within(selected).getByRole("button", { name: "暂停所选每日授权" })).toBeDisabled();
  fireEvent.click(within(selected).getByRole("checkbox"));
  fireEvent.click(within(selected).getByRole("button", { name: "暂停所选每日授权" }));
  await screen.findByText("已暂停所选每日授权，原历史保留。");
  const calls = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(calls).toHaveLength(1);
  expect(JSON.parse(String(calls[0][1]?.body))).toMatchObject({ expected_version: 2, action: "PAUSE", confirmed: true });
  expect(within(selected).getByText(/版本3 · 已暂停/)).toBeVisible();
});

test("expired audit remains visible while its body is unavailable and a failed read clears authorization controls", async () => {
  let failed = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async url => {
    if (failed) throw new TypeError("private network payload");
    const path = String(url);
    if (path.includes("/configurations/")) return response(config(1));
    if (path.includes("/history?")) return response([{ report_id: id(300), task_run_id: id(301), schedule_id: id(1), revision_id: id(500), recorded_at: "2026-11-01", usable_until: "2026-11-02", phase: "DEGRADED", content_hash: "a".repeat(64), availability: "EXPIRED" }]);
    return response([config(1)]);
  });
  render(<DailyHistoryBrowser />);
  fireEvent.click(await screen.findByRole("button", { name: "查看此授权" }));
  await screen.findByRole("article", { name: "所选每日授权" });
  failed = true;
  fireEvent.click(screen.getByRole("button", { name: "刷新完整每日历史" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "暂停所选每日授权" })).toBeNull();
  expect(screen.queryByText(/private network payload/)).toBeNull();
  failed = false;
  fireEvent.change(screen.getByLabelText("每日历史类别"), { target: { value: "history" } });
  await screen.findByText(/正文已过期，审计保留/);
  expect(screen.getByRole("button", { name: "查看此日报" })).toBeDisabled();
  expect(screen.queryByRole("article", { name: "所选每日正文" })).toBeNull();
});

test("empty and malformed pages have different visible outcomes and never write", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(response([]));
  render(<DailyHistoryBrowser />);
  await screen.findByText("当前第1条起，本页0条");
  expect(screen.getByRole("button", { name: "加载更多每日历史" })).toBeDisabled();
  fetch.mockImplementation(async () => response([{ invalid: "private" }]));
  fireEvent.click(screen.getByRole("button", { name: "刷新完整每日历史" }));
  await screen.findByRole("alert");
  await waitFor(() => expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true));
});
