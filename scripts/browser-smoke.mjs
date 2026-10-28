import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const directory = process.env.EVIDENCE_DIR || "docs/evidence/e3/browser";
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const results = [];

async function check(name, task) {
  await task();
  results.push({ name, result: "passed" });
  console.log(`PASS ${name}`);
}

try {
  await page.goto("http://127.0.0.1:3000");
  await check("真实 API 与 PostgreSQL 健康", async () => {
    await page.getByText("✓ API 与数据库就绪").waitFor();
    assert.match(await page.locator(".service-status").innerText(), /0006_e7/);
  });
  await check("键盘跳过链接与项目字段", async () => {
    await page.keyboard.press("Tab");
    assert.equal(await page.locator(":focus").innerText(), "跳到主要内容");
    await page.getByLabel("项目名称").focus();
    assert.equal(await page.locator(":focus").getAttribute("id"), "project-name");
  });
  await check("项目空状态（真实数据库）", async () => {
    const response = await page.request.get("http://127.0.0.1:8000/api/projects");
    const data = await response.json();
    if (data.total !== 0) throw new Error("空状态验收需要空开发库；请使用独立验收数据库运行此脚本");
    await page.getByText("还没有项目", { exact: true }).waitFor();
    await page.screenshot({ path: `${directory}/e2-empty.png`, fullPage: true });
  });
  await check("真实项目创建且刷新后持久化", async () => {
    const name = `示例 E5 基础界面回归 ${new Date().toISOString()}`;
    await page.getByLabel("项目名称").fill(name);
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    await page.getByText(name, { exact: true }).waitFor();
    await page.reload();
    await page.getByText(name, { exact: true }).waitFor();
    const response = await page.request.get("http://127.0.0.1:8000/api/projects");
    const data = await response.json();
    assert.ok(data.items.some(p => p.name === name));
  });
  const example = await readFile("environments/refund_approval/example.v0.2.yaml", "utf8");
  await check("附录 B 真实后端校验与哈希", async () => {
    await page.getByRole("button", { name: "载入附录 B 示例" }).click();
    assert.equal(await page.getByLabel("配置内容").inputValue(), example);
    await page.getByRole("button", { name: "校验契约", exact: true }).click();
    await page.getByText("✓ 配置校验通过").waitFor();
    assert.match(await page.locator(".result code").innerText(), /^[0-9a-f]{64}$/);
    await page.screenshot({ path: `${directory}/e2-desktop.png`, fullPage: true });
  });
  await check("缺少 provider_ledger 显示字段错误", async () => {
    await page.getByLabel("配置内容").fill(example.replace("    provider_ledger: required\n", ""));
    await page.getByRole("button", { name: "校验契约", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "product.observations.provider_ledger" }).waitFor();
    await page.screenshot({ path: `${directory}/e2-validation-error.png`, fullPage: true });
  });
  await check("窄屏无水平溢出", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: `${directory}/e2-mobile.png`, fullPage: true });
  });
  await check("断网错误反馈（浏览器网络故障注入）", async () => {
    await page.route("**/api/backend/**", route => route.abort("connectionrefused"));
    await page.getByRole("button", { name: "刷新状态" }).click();
    await page.getByText("连接异常", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "创建项目", exact: true }).isDisabled(), true);
    await page.screenshot({ path: `${directory}/e2-offline.png`, fullPage: true });
    await page.unroute("**/api/backend/**");
    await page.getByRole("button", { name: "刷新状态" }).click();
    await page.getByText("✓ API 与数据库就绪").waitFor();
  });
  await check("跨来源写入被拒绝", async () => {
    const response = await page.request.post("http://127.0.0.1:3000/api/backend/projects", {
      headers: { Origin: "http://untrusted.example" }, data: { name: "不应创建" },
    });
    assert.equal(response.status(), 403);
  });
  assert.deepEqual(errors, []);
  results.push({ name: "无浏览器运行时异常", result: "passed" });
  await writeFile(`${directory}/browser-results.json`, JSON.stringify({ time: new Date().toISOString(), browser: await browser.version(), results }, null, 2) + "\n");
} finally {
  await browser.close();
}
