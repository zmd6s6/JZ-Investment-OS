import { describe, expect, it } from "vitest";

import {
  actionLabel,
  explainFailure,
  gateLabel,
  runStatusLabel,
  stanceLabel,
  tokenPriceLabel,
} from "./analysisLabels";

describe("analysisLabels", () => {
  it("displays exact token prices without database padding or floating point rounding", () => {
    expect(tokenPriceLabel("0.000001000000000000")).toBe("0.000001");
    expect(tokenPriceLabel("0.000000000000000001")).toBe("0.000000000000000001");
    expect(tokenPriceLabel("12345678901234567890.1200")).toBe("12345678901234567890.12");
    expect(tokenPriceLabel("10.000")).toBe("10");
    expect(tokenPriceLabel("0.000")).toBe("0");
    expect(tokenPriceLabel("1.0E-20")).toBe("1.0E-20");
    expect(tokenPriceLabel(null)).toBe("未配置");
  });
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
