import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DecisionCenterPage } from "./DecisionCenterPage";

const card = { decision_id: "decision-a", portfolio_id: "portfolio-a", instrument_id: "instrument-a", symbol: "SYNTH301", action: "BUY", state: "PENDING_APPROVAL", revision: 1, created_at: "2026-10-28T10:00:00Z", blockers: [] as string[] };
const view = { schema_version: "1.0", decision: card, as_of: "2026-10-28T10:01:00Z", auto_trade: false, mode: "RECORD_ONLY_NO_BROKER", journal: { content_hash: "a", input_snapshot_hash: "b", reasons: [{ text: "合成理由", evidence_ids: ["evidence-a"] }], risks: [], core_action: "BUY", tactical_action: "NONE", position_before: { total: "0", core: "0", tactical: "0" }, position_after_proposed: { total: "0.05", core: "0.05", tactical: "0" }, unknowns: [], dissent: ["合成反方"], watch_conditions: [], invalidation_conditions: [], prompt_bundle_version: "test", formula_version: "test" }, lineage: { thesis_version_id: "thesis", policy_version_id: "policy", strategy_version_id: "strategy", risk_assessment_id: "risk", risk_veto: false, risk_codes: [], risk_expires_at: "2026-10-28T20:00:00Z", sizing_run_id: "sizing", sizing_input: { reference_price: "10" }, evidence: [] }, history: [], approval_id: null, approval_expires_at: null, approved_quantity: "50", filled_quantity: "0", remaining_quantity: "50", allowed_actions: ["REJECT", "APPROVE"] };
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function mock(detail = view, post?: (init: RequestInit) => Promise<Response>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const path = String(input);
    if (init?.method === "POST") return post ? post(init) : Promise.resolve(response({ ...view, decision: { ...card, revision: 2, state: "APPROVED" }, allowed_actions: ["REVOKE", "RECORD_EXECUTION"], approval_id: "approval-a" }));
    return Promise.resolve(response(path === "/api/v1/decision-center" ? [card] : detail));
  });
}
async function open() {
  render(<DecisionCenterPage />);
  fireEvent.click(await screen.findByRole("button", { name: /SYNTH301 · BUY/ }));
  await screen.findByText("合成理由");
}
function confirm() {
  fireEvent.change(screen.getByLabelText("人工归属名称"), { target: { value: "synthetic-human" } });
  fireEvent.change(screen.getByLabelText("本次人工理由"), { target: { value: "明确审阅" } });
  fireEvent.click(screen.getByLabelText(/我已审阅当前版本与风险/));
}
it("requires explicit human confirmation, uses revision and records no implicit trade", async () => {
  const fetch = mock(); await open();
  expect(screen.getByRole("button", { name: "批准" })).toBeDisabled();
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  confirm(); fireEvent.click(screen.getByRole("button", { name: "批准" }));
  await screen.findByText(/批准已保存，版本 2/);
  const post = fetch.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(post[0]).toBe("/api/v1/decision-center/decision-a/approve");
  expect(JSON.parse(String(post[1]?.body))).toMatchObject({ expected_revision: 1, actor_id: "synthetic-human", confirmed: true });
  expect(screen.getByText(/没有提交任何订单/)).toBeVisible();
});
it("unknown network outcome keeps the same idempotency request on explicit retry", async () => {
  const ids: string[] = []; let count = 0;
  mock(view, init => { ids.push(JSON.parse(String(init.body)).request_id); return ++count === 1 ? Promise.reject(new Error("network")) : Promise.resolve(response({ ...view, decision: { ...card, revision: 2, state: "APPROVED" }, allowed_actions: [] })); });
  await open(); confirm(); fireEvent.click(screen.getByRole("button", { name: "批准" }));
  await screen.findByText(/操作未确认/);
  fireEvent.click(screen.getByLabelText(/我已审阅当前版本与风险/)); fireEvent.click(screen.getByRole("button", { name: "批准" }));
  await screen.findByText(/批准已保存/); expect(ids).toHaveLength(2); expect(ids[0]).toBe(ids[1]);
});
it("pending writes prevent double clicks and decision changes", async () => {
  let release!: (value: Response) => void;
  mock(view, () => new Promise(resolve => { release = resolve; })); await open(); confirm();
  fireEvent.click(screen.getByRole("button", { name: "批准" }));
  expect(screen.getByRole("button", { name: /SYNTH301 · BUY/ })).toBeDisabled();
  expect(screen.getByLabelText("人工归属名称")).toBeDisabled();
  await act(async () => release(response({ ...view, allowed_actions: [] })));
});
it("Veto and missing inputs remain visible and cannot reveal an approval button", async () => {
  mock({ ...view, decision: { ...card, blockers: ["RISK_VETO"] }, allowed_actions: ["REJECT"] }); await open();
  expect(screen.getByText(/风险否决不可覆盖/)).toBeVisible(); expect(screen.queryByRole("button", { name: "批准" })).toBeNull();
});
it("rejects malformed or mismatched detail and leaves human controls unavailable", async () => {
  mock({ ...view, auto_trade: true } as unknown as typeof view); render(<DecisionCenterPage />);
  fireEvent.click(await screen.findByRole("button", { name: /SYNTH301 · BUY/ }));
  await screen.findByText(/决策协议或编号不符/); expect(screen.queryByLabelText("人工归属名称")).toBeNull();
});
it("late first decision details cannot overwrite a second selection", async () => {
  let release!: (value: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementation(input => String(input).endsWith("decision-a") ? new Promise(resolve => { release = resolve; }) : Promise.resolve(response(String(input).endsWith("decision-b") ? { ...view, decision: { ...card, decision_id: "decision-b", symbol: "SYNTH-B" } } : [card, { ...card, decision_id: "decision-b", symbol: "SYNTH-B" }])));
  render(<DecisionCenterPage />); fireEvent.click(await screen.findByRole("button", { name: /SYNTH301 · BUY/ })); fireEvent.click(screen.getByRole("button", { name: /SYNTH-B · BUY/ }));
  await screen.findByText(/Decision decision-b/); await act(async () => release(response(view)));
  expect(screen.queryByText(/Decision decision-a/)).toBeNull();
});

it("legacy human receipts show missing facts explicitly without reopening approval", async () => {
  mock({ ...view, decision: { ...card, state: "LEGACY_REVIEW_REQUIRED", blockers: ["LEGACY_ACTION_HISTORY_REQUIRES_REVIEW"] }, allowed_actions: [], history: [{ request_id: "old-execution", revision: null, legacy: true, action: "LEGACY_EXECUTION", state: "LEGACY_REVIEW_REQUIRED", actor_id: "synthetic-old-human", comment: null, occurred_at: "2026-10-27T10:00:00Z", execution: { quantity: "1", price: "10", fees: null, executed_at: null, note: null, references: ["synthetic-old-reference"], status: "FILLED", approval_id: "old-approval" } }] } as unknown as typeof view);
  await open();
  expect(screen.getByText(/旧模拟或手工回执/)).toBeVisible();
  expect(screen.getByText(/费用 未提供/)).toBeVisible();
  expect(screen.getByText(/实际成交 旧记录未提供/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "批准" })).toBeNull();
});
