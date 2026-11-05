import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AnalysisRiskSizingPanel, type RiskSizingSummary } from "./AnalysisRiskSizingPanel";
afterEach(cleanup);
const view:RiskSizingSummary={risk_gate:"PASS",sizing_status:"COMPUTED",risk_assessment_id:"risk-205",sizing_run_id:"sizing-205",numeric_snapshot_id:"source-205",policy_version_id:"policy-205",bucket:"CORE",target_quantity:"500",delta_quantity:"400",blockers:["INVESTMENT_DECISION_BRIDGE_NOT_IMPLEMENTED"],numbers:{nav:"100000",metrics:{VOLATILITY:"0.2"}},risk_flags:[{code:"NUMERIC_LIMITS_EVALUATED",kind:"SOFT",severity:"INFO",evidence_ids:["numeric-evidence"],release_condition:"重新测算"}],sizing_output:{formula_version:"synthetic-v1",input_hash:"immutable-hash",pre_rounding_delta_quantity:"400",capacity:{requested_increase:{value:"0.04"},allowed_increase:{value:"0.04"},limits:[{code:"SINGLE_INSTRUMENT_CAP",available:{value:"0.12"}}]}},evaluated_at:"2026-10-30T00:00:00Z",expires_at:"2026-10-31T00:00:00Z",simulation_only:true,execution_allowed:false,auto_trade:false};
it("shows saved numeric result, evidence and readable cap with shadow boundary",()=>{
 render(<AnalysisRiskSizingPanel data={view}/>);
 expect(screen.getByText("100000")).toBeVisible();
 expect(screen.getByText("标的波动率：0.2")).toBeVisible();
 expect(screen.getByText(/目标数量（影子测算）500；数量变化 400/)).toBeVisible();
 expect(screen.getByText("单标的上限余量：0.12")).toBeVisible();
 expect(screen.getByText(/证据 numeric-evidence/)).toBeVisible();
 expect(screen.queryByRole("button",{name:/批准|执行/})).not.toBeInTheDocument();
});
it("does not turn missing quantities into zero",()=>{
 render(<AnalysisRiskSizingPanel data={{...view,risk_gate:"UNKNOWN",sizing_status:"BLOCKED",risk_flags:[],target_quantity:null,delta_quantity:null,sizing_output:null,blockers:["FX_REQUIRED"]}}/>);
 expect(screen.getByText("建议数量未提供，不能把缺项显示成0股。")).toBeVisible();
 expect(screen.getByText(/跨币种缺少已授权FX输入/)).toBeVisible();
 expect(screen.queryByText(/目标数量（影子测算）/)).not.toBeInTheDocument();
});
it("does not infer pass from an unstarted stage",()=>{
 render(<AnalysisRiskSizingPanel data={null}/>);
 expect(screen.getByText(/尚无已保存的风险/)).toBeVisible();
});
