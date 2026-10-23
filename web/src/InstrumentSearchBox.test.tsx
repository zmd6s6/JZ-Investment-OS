import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InstrumentSearchBox } from "./InstrumentSearchBox";

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
describe("标的搜索反馈", () => {
  it("shows pending, empty and manual-entry guidance", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('[]')));
    render(<InstrumentSearchBox onSelect={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("标的搜索"), { target: { value: "不存在的合成标的" } });
    expect(screen.getByRole("status")).toHaveTextContent("正在搜索");
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    expect(screen.getByRole("status")).toHaveTextContent("没有匹配项");
    expect(screen.getByRole("status")).toHaveTextContent("手动填写");
  });

  it("ignores an old response after the search is cleared", async () => {
    vi.useFakeTimers();
    let finish!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
    render(<InstrumentSearchBox onSelect={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("标的搜索"), { target: { value: "旧搜索" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    fireEvent.change(screen.getByLabelText("标的搜索"), { target: { value: "" } });
    await act(async () => finish(new Response(JSON.stringify([{ instrument_id: "synthetic-id", symbol: "000000", name: "迟到结果" }]))));
    expect(screen.queryByText(/迟到结果/)).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("explains a failed search without blocking manual entry", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("synthetic failure")));
    render(<InstrumentSearchBox onSelect={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("标的搜索"), { target: { value: "合成搜索" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    expect(screen.getByRole("alert")).toHaveTextContent("手动填写代码");
  });
});
