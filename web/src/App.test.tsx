import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("keeps simulation and safety signals visible across all personal pages", () => {
    render(<App />);

    expect(screen.getByText("SIMULATION / NO AUTO TRADE")).toBeVisible();
    expect(screen.getByText("ACTIVE — increased exposure blocked")).toBeVisible();
    expect(screen.getByText("1 pending; no order submitted")).toBeVisible();
    expect(screen.getByText("Daily report job not yet completed")).toBeVisible();

    for (const page of ["Opportunities", "Watchlist", "Decision Journal"]) {
      fireEvent.click(screen.getByRole("button", { name: page }));
      expect(screen.getByRole("heading", { name: page })).toBeVisible();
      expect(screen.getByRole("button", { name: page })).toHaveAttribute("aria-current", "page");
      expect(screen.getByText("SIMULATION / NO AUTO TRADE")).toBeVisible();
    }
  });
});
