import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test } from "@playwright/test";

const store = process.env.E2E_LOCAL_ACCESS_STORE_PATH;
const origin = process.env.E2E_BASE_URL ?? "http://127.0.0.1:18104";
// Test grants must not enter traces, even though all data is synthetic.
test.use({ trace: "off" });
test.skip(!store, "仅在明确指定隔离本机会话库时运行，禁止对用户库签发测试授权");

function pairingURL() {
  const python = path.resolve("..", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const code = execFileSync(python, ["-c", "import sys; from pathlib import Path; from investment_os.infrastructure.local_access import LocalAccessStore; print(LocalAccessStore(Path(sys.argv[1])).issue_pairing(sys.argv[2]))", store!, origin], { encoding: "utf8", cwd: path.resolve("..") }).trim();
  return `${origin}/#local-pair=${code}`;
}

test("first pairing needs no manual token, clears the link, survives refresh and a new tab", async ({ page, context, request }) => {
  expect((await request.get(`${origin}/api/v1/analysis-model-options`)).status()).toBe(401);
  expect((await request.get(`${origin}/api/v1/analysis-market-options`)).status()).toBe(401);
  expect((await request.get(`${origin}/api/v1/policy/review`)).status()).toBe(401);
  const ledgerPath = "/api/v1/analysis-runs/00000000-0000-4000-8000-000000000001/market-attempts";
  expect((await request.get(`${origin}${ledgerPath}`)).status()).toBe(401);
  const thesisPath = "/api/v1/theses/00000000-0000-4000-8000-000000000001";
  expect((await request.get(`${origin}${thesisPath}/workspace`)).status()).toBe(401);
  expect((await request.post(`${origin}${thesisPath}/versions`, { headers: { Origin: origin, "X-Investment-OS": "local-ui" }, data: {} })).status()).toBe(401);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "从本地入口打开，即可开始" })).toBeVisible();
  await expect(page.getByLabel("写入令牌")).not.toBeVisible();
  await page.goto(pairingURL());
  await expect(page.getByRole("button", { name: "本机已连接", exact: true })).toBeVisible();
  expect((await context.request.get(`${origin}/api/v1/analysis-model-options`)).status()).toBe(200);
  expect((await context.request.get(`${origin}/api/v1/analysis-market-options`)).status()).toBe(200);
  const policy = await context.request.get(`${origin}/api/v1/policy/review`);
  expect(policy.status()).toBe(200);
  const review = await policy.json();
  expect(review.policy_status).toBe("TEST_DEFAULT");
  expect(review.snapshot.mode).toBe("TEST_DEFAULT");
  expect(review.snapshot.content_hash).toMatch(/^[a-f0-9]{64}$/);
  expect((await context.request.get(`${origin}${ledgerPath}`)).status()).toBe(404);
  expect((await context.request.get(`${origin}${thesisPath}/workspace`)).status()).toBe(404);
  expect((await context.request.post(`${origin}${thesisPath}/versions`, { headers: { Origin: origin, "X-Investment-OS": "local-ui" }, data: {} })).status()).toBe(422);
  expect(new URL(page.url()).hash).toBe("");
  await page.reload();
  await expect(page.getByRole("button", { name: "本机已连接", exact: true })).toBeVisible();
  const next = await context.newPage();
  await next.goto(`${origin}/portfolio`);
  await expect(next.getByRole("heading", { name: "我的持仓" })).toBeVisible();
  await expect(next.getByRole("button", { name: "配置写令牌" })).not.toBeVisible();
  const name = `本机会话合成组合-${Date.now()}`;
  await next.getByLabel("组合名称", { exact: true }).fill(name);
  await next.getByRole("button", { name: "创建组合", exact: true }).click();
  await expect(next.getByText("组合已创建", { exact: true })).toBeVisible();
});

test("cookie session cannot be used by a foreign origin and logout revokes it", async ({ page, context }) => {
  await page.goto(pairingURL());
  await expect(page.getByRole("button", { name: "本机已连接", exact: true })).toBeVisible();
  const rejected = await context.request.post(`${origin}/api/v1/auth/check`, { headers: { Origin: "https://evil.example", "X-Investment-OS": "local-ui" } });
  expect(rejected.status()).toBe(403);
  const cookies = await context.cookies();
  const session = cookies.find((cookie) => cookie.name.startsWith("investment_os_local_"))!;
  expect(session.httpOnly).toBe(true);
  expect(session.sameSite).toBe("Strict");
  await page.getByRole("button", { name: "本机已连接", exact: true }).click();
  await page.getByRole("button", { name: "断开本机访问" }).click();
  await expect(page.getByRole("heading", { name: "从本地入口打开，即可开始" })).toBeVisible();
  const replay = await context.request.get(`${origin}/api/v1/product-capabilities`, { headers: { Cookie: `${session.name}=${session.value}` } });
  expect(replay.status()).toBe(401);
});

test("a used pairing link cannot authorize another browser context", async ({ page, browser }) => {
  const link = pairingURL();
  await page.goto(link);
  await expect(page.getByRole("button", { name: "本机已连接", exact: true })).toBeVisible();
  const other = await browser.newContext();
  const next = await other.newPage();
  await next.goto(link);
  await expect(next.getByRole("alert")).toContainText("链接已失效或已使用");
  await expect(next.getByRole("heading", { name: "把持仓变成有据可查的研究" })).not.toBeVisible();
  await other.close();
});
