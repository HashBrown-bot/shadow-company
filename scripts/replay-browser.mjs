import assert from "node:assert/strict";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const input = process.env.REPORT_RUNTIME_PATH || "docs/evidence/e6/runtime.json";
const runtime = JSON.parse(await readFile(input, "utf8"));
const source = runtime.buggy_run.report;
const directory = path.join(path.dirname(input), "browser");
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], checks = [];
page.on("pageerror", error => errors.push(error.message));
async function check(name, action) { await action(); checks.push({ name, result: "passed" }); }
try {
  await page.goto("http://127.0.0.1:3000");
  await page.getByRole("heading", { name: "E6 重放与比较", exact: true }).waitFor();
  await check("三种重放模式有明确边界", async () => {
    assert.equal(await page.locator("#replay-mode option").count(), 3);
    await page.getByLabel("重放模式").selectOption("controlled");
    assert.match(await page.locator(".replay-explanation").innerText(), /不控制外部时钟/);
    await page.getByLabel("重放模式").selectOption("history");
    assert.equal(await page.locator("#replay-contract").count(), 0);
  });
  await page.getByLabel("项目 ID", { exact: true }).fill(source.project_id);
  await page.getByLabel("源 run ID").fill(source.run_id);
  const historyUrl = `http://127.0.0.1:8000/api/runs/${source.run_id}/history?project_id=${source.project_id}`;
  const before = await (await page.request.get(historyUrl)).json();
  await check("history 只读真实历史且不改变源记录", async () => {
    await page.getByRole("button", { name: "查看历史", exact: true }).click();
    await page.getByText("历史已读取；未创建运行，未调用 PUT。", { exact: true }).waitFor();
    assert.deepEqual(await (await page.request.get(historyUrl)).json(), before);
  });
  await check("input 实际调用 fixed 并展示真实比较", async () => {
    await page.getByLabel("重放模式").selectOption("input");
    await page.getByRole("button", { name: "启动重放并比较", exact: true }).click();
    await page.getByText("已在声明范围验证修复", { exact: true }).waitFor({ timeout: 60_000 });
    assert.match(await page.getByTestId("replay-comparison").innerText(), /fail → pass/);
    await page.getByText("路径偏离与合法重试变化", { exact: true }).click();
    assert.match(await page.getByTestId("replay-comparison").innerText(), /allowed_product_path_change/);
    assert.deepEqual(await (await page.request.get(historyUrl)).json(), before);
    const link = await page.getByRole("link", { name: "查看新运行证据报告 ↗" }).getAttribute("href");
    const response = await page.request.get("http://127.0.0.1:3000" + link);
    assert.equal(response.status(), 200);
    assert.match(response.headers()["content-type"], /text\/html/);
    assert.match(await response.text(), /E6 示例证据报告/);
  });
  await page.locator(".replay-panel").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${directory}/replay-desktop.png` });
  await check("390px 布局与键盘字段访问", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.getByLabel("目标 PUT 版本").focus();
    assert.equal(await page.locator(":focus").getAttribute("id"), "replay-version");
    await page.getByTestId("replay-comparison").scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${directory}/replay-mobile.png` });
  });
  await check("缺少目标契约显示真实 API 错误", async () => {
    await page.getByLabel("目标契约版本（须已预检）").fill("not-existing");
    await page.getByRole("button", { name: "启动重放并比较", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "契约不存在" }).waitFor();
    assert.equal(await page.getByTestId("replay-comparison").count(), 0);
  });
  await check("比较 HTML 显示不可比较项与路径差异", async () => {
    const url = `http://127.0.0.1:8000/api/runs/${source.run_id}/compare?project_id=${source.project_id}&other_run_id=${runtime.first_run.report.run_id}&format=html`;
    await page.setViewportSize({ width: 1440, height: 1000 });
    assert.equal((await page.goto(url)).status(), 200);
    await page.getByText("不可比较范围", { exact: true }).click();
    await page.getByText("路径偏离与合法重试变化", { exact: true }).click();
    assert.match(await page.locator("body").innerText(), /network_latency/);
    assert.match(await page.locator("body").innerText(), /allowed_product_path_change/);
    await page.screenshot({ path: `${directory}/compare-desktop.png` });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: `${directory}/compare-mobile.png` });
  });
  assert.deepEqual(errors, []);
  checks.push({ name: "无浏览器运行时异常", result: "passed" });
  await writeFile(`${directory}/replay-browser-results.json`, JSON.stringify({ browser: await browser.version(), checks }, null, 2));
  console.log(`${checks.length} 项 E6 重放浏览器检查通过`);
} finally { await browser.close(); }
