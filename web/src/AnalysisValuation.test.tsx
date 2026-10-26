import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AnalysisValuation } from "./AnalysisValuation";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("historical observations are read-only, nonannualized and keep failed queries explicit", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const historical = { calculation_version: "observed-daily-20-v1", source: "合成历史源", currency: "CNY", sample_count: 20, daily_return_sample_stddev: "0.125", compounded_daily_return: "-0.25", mean_volume_shares: "109.5", mean_turnover: "1009.5", history: { bars: [{ as_of: "2026-10-01" }, { as_of: "2026-10-23" }] }, missing_fields: [], input_hash: "c".repeat(64) };
  const { rerender } = render(<AnalysisValuation valuation={{ ...valuation, target_historical_features: historical }} sizing={sizing} />);
  expect(screen.getByRole("region", { name: "历史行情统计" })).toBeVisible();
  expect(screen.getByText("12.5%")).toBeVisible(); expect(screen.getByText("-25%")).toBeVisible();
  expect(screen.getByText(/不能用于回测或交易级仓位/)).toBeVisible();
  rerender(<AnalysisValuation valuation={{ ...valuation, target_historical_features: { ...historical, history: { bars: [], reason: "REQUEST_FAILED" }, daily_return_sample_stddev: null, mean_volume_shares: null, sample_count: 0, missing_fields: ["INSUFFICIENT_20_OBSERVATIONS"] } }} sizing={sizing} />);
  expect(screen.getByText(/历史请求失败；未换源补齐/)).toBeVisible();
  expect(screen.getByText(/不足20条观测/)).toBeVisible(); expect(fetcher).not.toHaveBeenCalled();
});
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

it("shows exact signed single-day observations with source and no false volatility or capacity", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<AnalysisValuation valuation={{ ...valuation, target_market_features: {
    calculation_version: "daily-observations-v1", currency: "CNY", source: "合成日线", degraded: true,
    daily_return: "-0.123456789123456", intraday_range: "0.4", volume_shares: "9007199254740993", turnover: "12345.5",
    bar: { open: "10", high: "12", low: "8", close: "8.76543210876544", previous_close: "10", previous_close_basis: "EX_RIGHTS", as_of: "2026-10-23T07:00:00Z" },
    missing_fields: [], input_hash: "a".repeat(64), sizing_ready: false,
  } }} sizing={sizing} />);
  expect(screen.getByText("-12.34567891…%")).toBeVisible();
  expect(screen.getByText("40%")).toBeVisible();
  expect(screen.getByText("9007199254740993")).toBeVisible();
  expect(screen.getByText(/来源：合成日线（降级源）/)).toBeVisible();
  expect(screen.getByText(/日内振幅不等于历史/)).toBeVisible();
  expect(screen.getByText("暂不生成建议数量")).toBeVisible();
  expect(fetcher).not.toHaveBeenCalled();
});

it("does not backfill historical daily data and keeps missing data different from genuine zero", () => {
  const { rerender } = render(<AnalysisValuation valuation={valuation} sizing={sizing} />);
  expect(screen.getByText(/未记录单日行情观察/)).toBeVisible();
  rerender(<AnalysisValuation valuation={{ ...valuation, target_market_features: {
    calculation_version: "daily-observations-v1", currency: "CNY", daily_return: null, intraday_range: null,
    volume_shares: "0", turnover: null, missing_fields: ["previous_close", "turnover"], bar: {},
  } }} sizing={sizing} />);
  expect(screen.getByText("0")).toBeVisible();
  expect(screen.getAllByText("未知").length).toBeGreaterThan(2);
  expect(screen.getByText(/单日数据不完整，未补零：昨收价、成交额/)).toBeVisible();
});
