import { expect, test } from "@playwright/test";

const WRITE_TOKEN = process.env.INVESTMENT_OS_API_WRITE_TOKEN ?? "e2e-write-token";

test("home onboarding can start and persists non-sensitive state", async ({ page, request }) => {
  await page.addInitScript((token: string) => {
    sessionStorage.setItem("investment_os_write_token", token);
  }, WRITE_TOKEN);
  const initialResponse = await request.get("/api/v1/onboarding");
  expect(initialResponse.ok()).toBeTruthy();
  const initial = await initialResponse.json();
  expect(Object.keys(initial).sort()).toEqual(["schema_version", "started_at", "status"]);
  expect(["NOT_STARTED", "IN_PROGRESS"]).toContain(initial.status);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "先搭好底座，再开始研究" })).toBeVisible();
  await expect(page.getByText("模拟净值")).not.toBeVisible();

  if (initial.status === "NOT_STARTED") {
    await expect(page.getByRole("button", { name: "开始设置" })).toBeVisible();
    await page.getByRole("button", { name: "开始设置" }).click();
    await expect(page.getByRole("status")).toContainText("设置已开始");
    await page.reload();
    await expect(page.getByRole("status")).toContainText("设置已开始");
  } else {
    await expect(page.getByText("设置已开始")).toBeVisible();
  }

  const persistedResponse = await request.get("/api/v1/onboarding");
  expect(persistedResponse.ok()).toBeTruthy();
  const persisted = await persistedResponse.json();
  expect(Object.keys(persisted).sort()).toEqual(["schema_version", "started_at", "status"]);
  expect(persisted.status).toBe("IN_PROGRESS");
  expect(persisted.started_at).toMatch(/Z$/);
});
