import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AnalysisDecisionBridgePanel, type BridgeRun } from "./AnalysisDecisionBridgePanel";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const run: BridgeRun = { run_id: "run-206", portfolio_id: "book-206", instrument_id: "instrument-206", status: "SUCCEEDED", input_hash: "a".repeat(64) };
const source = { qualification_id: "source-206", portfolio_id: run.portfolio_id, instrument_id: run.instrument_id, strategy_version_id: "strategy-206", source_name: "明确合成资格", source_kind: "SYNTHETIC_FIXTURE", created_at: "2026-11-04T00:00:00Z", expires_at: "2026-11-05T00:00:00Z" };
const record = { status: "PENDING_APPROVAL", decision_id: "decision-206", request_id: "request-206", revision: 1, qualification_id: source.qualification_id, blockers: [], gates: { INVESTMENT_QUALITY: "PASS" }, simulation_only: true, execution_allowed: false, auto_trade: false };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function mock(post: (init?: RequestInit) => Promise<Response> = async init => response({ ...record, request_id: JSON.parse(String(init?.body)).request_id }), sources = [source]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => init?.method === "POST" ? post(init) : response(String(input).includes("decision-qualifications") ? sources : []));
}
async function consent() {
  await screen.findByRole("option", { name: /明确合成资格/ });
  fireEvent.change(screen.getByLabelText("原时点固定资格"), { target: { value: source.qualification_id } });
  fireEvent.change(screen.getByLabelText("准备决策操作者"), { target: { value: "明确操作者" } });
  fireEvent.click(screen.getByLabelText(/我确认只准备待审阅记录/));
}
it("requires explicit fixed source and human confirmation then links to pending review without approving", async () => {
  const fetch = mock(); render(<AnalysisDecisionBridgePanel run={run} />);
  expect(screen.getByRole("button", { name: "确认准备待审阅决策" })).toBeDisabled();
  await consent(); fireEvent.click(screen.getByRole("button", { name: "确认准备待审阅决策" }));
  expect(await screen.findByRole("link", { name: "前往决策中心审阅" })).toHaveAttribute("href", "/decisions?decision_id=decision-206");
  const writes = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({ run_id: run.run_id, qualification_id: source.qualification_id, actor_id: "明确操作者", confirm_preparation: true, expected_revision: 0 });
  expect(screen.queryByRole("button", { name: /批准|执行/ })).toBeNull();
});
it("shows missing qualification instead of interpreting numeric pass as authorization", async () => {
  mock(undefined, []); render(<AnalysisDecisionBridgePanel run={run} />);
  expect(await screen.findByText(/没有可用的完整资格快照/)).toBeVisible();
  expect(screen.getByRole("button", { name: "确认准备待审阅决策" })).toBeDisabled();
});
it("preserves explicit input and request identity after unknown response without automatic retries", async () => {
  const fetch = mock(async () => { throw new Error("请求超时，结果未知"); }); render(<AnalysisDecisionBridgePanel run={run} />);
  await consent(); fireEvent.click(screen.getByRole("button", { name: "确认准备待审阅决策" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("结果未知");
  expect(screen.getByLabelText("准备决策操作者")).toHaveValue("明确操作者");
  fireEvent.click(screen.getByRole("button", { name: "确认准备待审阅决策" }));
  await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(2));
  const writes = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(JSON.parse(String(writes[0][1]?.body)).request_id).toBe(JSON.parse(String(writes[1][1]?.body)).request_id);
});
it("does not display an old run's late mutation in a different run", async () => {
  let release!: (value: Response) => void;
  mock(async () => new Promise(resolve => { release = resolve; }));
  const view = render(<AnalysisDecisionBridgePanel run={run} />);
  await consent(); fireEvent.click(screen.getByRole("button", { name: "确认准备待审阅决策" }));
  await waitFor(() => expect(release).toBeDefined());
  view.rerender(<AnalysisDecisionBridgePanel run={{ ...run, run_id: "different-run" }} />);
  await act(async () => release(response(record)));
  expect(screen.queryByRole("link", { name: "前往决策中心审阅" })).toBeNull();
  expect(screen.getByLabelText("准备决策操作者")).toHaveValue("");
});
