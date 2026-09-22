import { expect, test } from "@playwright/test";

test("settings keeps a configured credential write-only without contacting the configured endpoint", async ({
  page,
  request,
}) => {
  const profileName = "e2e-model-" + Date.now();
  const created = await request.post("/api/v1/settings/model-providers", {
    data: {
      name: profileName,
      provider_type: "OPENAI_COMPATIBLE",
      base_url: "https://models.example.invalid/v1",
      model_name: "e2e-synthetic-model",
      timeout_seconds: 30,
      max_tokens: 1024,
      enabled: true,
      credential: "e2e-synthetic-credential",
    },
  });
  expect(created.status()).toBe(201);
  const model = await created.json();
  expect(model.credential_configured).toBe(true);
  expect(JSON.stringify(model)).not.toContain("e2e-synthetic-credential");

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "设置与提供方" })).toBeVisible();
  await expect(page.getByText(profileName)).toBeVisible();
  await expect(page.getByText("凭据已配置")).toBeVisible();
  await expect(page.getByLabel("凭据（仅写入）").first()).toHaveValue("");
  await expect(page.getByText("e2e-synthetic-credential")).not.toBeVisible();
});
