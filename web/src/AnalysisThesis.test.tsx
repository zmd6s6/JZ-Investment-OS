import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnalysisThesis } from "./AnalysisThesis";

describe("历史投资逻辑", () => {
  it("旧报告不追补当前版本", () => {
    render(<AnalysisThesis value={undefined} />);
    expect(screen.getByText(/不用当前记录补写/)).toBeVisible();
  });
  it("没有版本时明确未知而非有效", () => {
    render(<AnalysisThesis value={{ version: null, effective_state: "UNKNOWN" }} />);
    expect(screen.getByText("投资逻辑：未知")).toBeVisible();
    expect(screen.getByText(/不默认为有效/)).toBeVisible();
  });
  it("显示固定版本与陈旧限制，不发起获取或写入", () => {
    const fetch=vi.spyOn(globalThis,"fetch");
    render(<AnalysisThesis value={{ effective_state:"UNKNOWN",as_of:"2026-10-21",evidence:[],version:{id:"frozen-version",version:2,parent_version_id:"first-version",content_hash:"c".repeat(64),created_at:"2026-10-20",content:{state:"VALID",long_term_summary:"合成历史逻辑",pillars:[],monitoring_conditions:["核对合成公告"]}} }} />);
    fireEvent.click(screen.getByText("投资逻辑 · 固定版本 2 · 未知"));
    expect(screen.getByText("合成历史逻辑")).toBeVisible();
    expect(screen.getByText(/记录状态：有效 · 本次规则使用：未知/)).toBeVisible();
    expect(screen.getByText(/版本 ID：frozen-version/)).toBeVisible();
    expect(fetch).not.toHaveBeenCalled();
    fetch.mockRestore();
  });
});
