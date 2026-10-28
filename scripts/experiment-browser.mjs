import assert from "node:assert/strict";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const input = process.env.E7_RUNTIME_PATH || "docs/evidence/e7/experiments.json";
const result = JSON.parse(await readFile(input, "utf8"));
const directory = path.join(path.dirname(input), "browser");
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], checks = [];
page.on("pageerror", error => errors.push(error.message));
try {
  for (const name of ["fixed", "buggy"]) {
    const report = result[name].experiment;
    const url = `http://127.0.0.1:8000/api/experiments/${report.experiment_id}?project_id=${report.project_id}&format=html`;
    const response = await page.goto(url);
    assert.equal(response.status(), 200);
    await page.getByRole("heading", { name: "E7 规则与混合角色对照", exact: true }).waitFor();
    const content = await page.locator("body").innerText();
    assert.ok(content.includes("未证明 AI 增量") && content.includes("未测"));
    assert.equal(await page.locator("table tr").count(), 3);
    assert.ok(content.includes(String(report.metrics.rule.observed_product_findings)));
    assert.ok(content.includes("no_model_calls_no_model_fee"));
    await page.screenshot({ path: `${directory}/experiment-${name}-desktop.png` });
    checks.push({ name: `${name}: 后端实际配对指标、未测与费用来源`, result: "passed" });
    await page.locator("summary").focus();
    await page.keyboard.press("Enter");
    assert.ok((await page.locator("details pre").innerText()).includes(report.experiment_id));
    checks.push({ name: `${name}: 键盘展开完整证据`, result: "passed" });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(url);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: `${directory}/experiment-${name}-mobile.png` });
    checks.push({ name: `${name}: 390px 无页面溢出`, result: "passed" });
    await page.setViewportSize({ width: 1440, height: 1000 });
  }
  assert.deepEqual(errors, []);
  checks.push({ name: "实验报告无浏览器运行时异常", result: "passed" });
  await writeFile(`${directory}/experiment-browser-results.json`, JSON.stringify({ browser: await browser.version(), checks }, null, 2));
  console.log(`${checks.length} 项 E7 对照报告浏览器检查通过`);
} finally {
  await browser.close();
}
