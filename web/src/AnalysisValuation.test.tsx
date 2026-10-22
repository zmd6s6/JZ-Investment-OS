import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AnalysisValuation } from "./AnalysisValuation";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const valuation = {
  calculation_version: "portfolio-valuation-v1", status: "OK", base_currency: "CNY",
  cash_balance: "10000.0000", holdings_value: "2500", nav: "12500", cash_weight: "0.8",
  gross_exposure: "0.2", target_core_weight: "0.16", target_tactical_weight: "0.04",
  as_of: "2026-10-22T07:00:00Z", input_hash: "a".repeat(64), unclassified_value: "0",
  position_values: [{ instrument_id: "one", symbol: "600082", name: "合成持仓", currency: "CNY", sector: "合成行业", core_quantity: "200", tactical_quantity: "50", price: "10", core_value: "2000", tactical_value: "500", core_weight: "0.16", tactical_weight: "0.04", source: "合成次源", degraded: true, quote_as_of: "2026-10-22T06:59:00Z" }],
  sector_values: [{ sector: "合成行业", market_value: "2500", weight: "0.2" }],
};
const sizing = { status: "BLOCKED", reason_codes: ["VOLATILITY_INPUT_MISSING", "LIQUIDITY_CAPACITY_MISSING", "PENDING_EXPOSURE_UNAVAILABLE"] };

it("shows cash reconciliation, separate buckets, provenance and actionable missing inputs without writes", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<AnalysisValuation valuation={valuation} sizing={sizing} />);
  expect(screen.getByText("12500")).toBeVisible();
  expect(screen.getByText("200 / 50")).toBeVisible();
  expect(screen.getByText("2000 / 500")).toBeVisible();
  expect(screen.getAllByText("16% / 4%")).toHaveLength(2);
  expect(screen.getByText("合成次源（降级源）")).toBeVisible();
  expect(screen.getByText(/缺少可追溯的波动率/)).toBeVisible();
  expect(screen.getByText(/缺少流动性容量/)).toBeVisible();
  expect(screen.getByText("暂不生成建议数量")).toBeVisible();
  expect(fetcher).not.toHaveBeenCalled();
});

it("does not label missing valuation or cross-currency amounts as zero", () => {
  render(<AnalysisValuation valuation={{ ...valuation, status: "FAILED", nav: null, holdings_value: null, cash_weight: null, gross_exposure: null, target_core_weight: null, target_tactical_weight: null, unclassified_value: null, position_values: [] }} sizing={sizing} />);
  expect(screen.getByText(/估值校验未通过/)).toBeVisible();
  expect(screen.getAllByText("未知").length).toBeGreaterThan(2);
  expect(screen.queryByText("0%")).not.toBeInTheDocument();
});

it("keeps historical reports honest instead of revaluing from current data", () => {
  render(<AnalysisValuation valuation={{ nav: "999", status: "OK" }} sizing={{ target_quantity: "100" }} />);
  expect(screen.getByText(/历史报告未记录本版估值对账/)).toBeVisible();
  expect(screen.queryByText("999")).not.toBeInTheDocument();
  expect(screen.queryByText("100")).not.toBeInTheDocument();
});

it("truncates long display fractions without converting financial strings to float", () => {
  render(<AnalysisValuation valuation={{ ...valuation, nav: "9007199254740993.123456789", cash_weight: "0.123456789123456" }} sizing={sizing} />);
  expect(screen.getByText("9007199254740993.12345678…")).toBeVisible();
  expect(screen.getByText("12.34567891…%")).toBeVisible();
});
