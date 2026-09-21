import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const response = (body: unknown, ok = true) =>
  Promise.resolve({ ok, json: () => Promise.resolve(body) });

afterEach(() => {
  vi.restoreAllMocks();
});

describe("product onboarding", () => {
  it("shows a fresh installation setup wizard instead of synthetic operations", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/v1/onboarding") {
          return response({ schema_version: "1.0", status: "NOT_STARTED", started_at: null });
        }
        return response([
          { key: "onboarding", label: "设置向导", status: "AVAILABLE", detail: "可开始" },
          { key: "providers", label: "提供方配置", status: "CONFIGURATION_REQUIRED", detail: "稍后开放" },
        ]);
      }),
    );

    render(<App />);

    expect(await screen.findByRole("button", { name: "开始设置" })).toBeInTheDocument();
    expect(screen.queryByText("模拟净值")).not.toBeInTheDocument();
    expect(screen.getByText("需要配置")).toBeInTheDocument();
  });

  it("persists the start action through the onboarding API", async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === "/api/v1/onboarding") {
        return response({ schema_version: "1.0", status: "NOT_STARTED", started_at: null });
      }
      if (url === "/api/v1/product-capabilities") return response([]);
      if (url === "/api/v1/onboarding/start" && options?.method === "POST") {
        return response({
          schema_version: "1.0",
          status: "IN_PROGRESS",
          started_at: "2026-09-21T00:00:00Z",
        });
      }
      return response({}, false);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "开始设置" }));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("设置已开始");
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/onboarding/start", { method: "POST" });
  });

  it("keeps the PR-08 synthetic demo at a clearly labelled separate route", () => {
    window.history.pushState({}, "", "/demo/pr-08");
    render(<App />);

    expect(screen.getByText("合成只读页面")).toBeInTheDocument();
    expect(screen.getByText("此页面只使用合成开发数据。它不代表账户、持仓、研究结论或可执行交易建议。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回设置向导" })).toHaveAttribute("href", "/");
    window.history.pushState({}, "", "/");
  });
});
