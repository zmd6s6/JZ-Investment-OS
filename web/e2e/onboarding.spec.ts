import { expect, test } from "@playwright/test";

test("fresh product opens onboarding and persists a non-sensitive start action", async ({ page, request }) => {
  const initialResponse = await request.get("/api/v1/onboarding");
  expect(initialResponse.ok()).toBeTruthy();
  expect(await initialResponse.json()).toEqual({
    schema_version: "1.0",
    started_at: null,
    status: "NOT_STARTED",
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "开始搭建你的研究工作台" })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始设置" })).toBeVisible();
  await expect(page.getByText("模拟净值")).not.toBeVisible();

  await page.getByRole("button", { name: "开始设置" }).click();
  await expect(page.getByRole("status")).toContainText("设置已开始");

  await page.reload();
  await expect(page.getByRole("status")).toContainText("设置已开始");

  const persistedResponse = await request.get("/api/v1/onboarding");
  expect(persistedResponse.ok()).toBeTruthy();
  const persisted = await persistedResponse.json();
  expect(Object.keys(persisted).sort()).toEqual(["schema_version", "started_at", "status"]);
  expect(persisted.status).toBe("IN_PROGRESS");
  expect(persisted.started_at).toMatch(/Z$/);
});
