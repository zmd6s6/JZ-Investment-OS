import { describe, expect, it } from "vitest";

import {
  actionLabel,
  explainFailure,
  gateLabel,
  runStatusLabel,
  stanceLabel,
} from "./analysisLabels";

describe("analysisLabels", () => {
  it("explains known failure codes with Chinese text while keeping the raw code", () => {
    const explained = explainFailure("MISSING_REFERENCE_QUOTES");
    expect(explained).toBe("缺少行情报价（MISSING_REFERENCE_QUOTES）");
    expect(explainFailure("INVALID_OUTPUT")).toContain("INVALID_OUTPUT");
    expect(explainFailure("INVALID_OUTPUT")).toContain("模型输出");
    expect(explainFailure("RISK_AGENT_UNAVAILABLE")).toContain("风险评估未完成");
  });

  it("passes unknown codes through so information is never hidden", () => {
    expect(explainFailure("SOME_FUTURE_CODE")).toBe("SOME_FUTURE_CODE");
  });

  it("maps run status, actions, gates and stances to Chinese labels", () => {
    expect(runStatusLabel("SUCCEEDED")).toBe("成功");
    expect(runStatusLabel("RUNNING")).toBe("运行中");
    expect(runStatusLabel("FAILED")).toBe("失败");
    expect(actionLabel("WATCH")).toBe("观望");
    expect(actionLabel("BUY")).toBe("买入");
    expect(gateLabel("VETO")).toBe("否决");
    expect(stanceLabel("INSUFFICIENT_DATA")).toBe("数据不足");
    // Unknown values fall through unchanged.
    expect(actionLabel("FUTURE_ACTION")).toBe("FUTURE_ACTION");
  });
});
