import assert from "node:assert/strict";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const input = process.env.REPORT_RUNTIME_PATH || "docs/evidence/e4/runtime.json";
const result = JSON.parse(await readFile(input, "utf8"));
const directory = path.join(path.dirname(input), "browser");
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], checks = [];
page.on("pageerror", error => errors.push(error.message));
try {
  for (const [name, data] of [["fixed", result.first_run], ["buggy", result.buggy_run]]) {
    const report = data.report;
    const url = `http://127.0.0.1:8000/api/runs/${report.run_id}/report?project_id=${report.project_id}&format=html`;
    const response = await page.goto(url);
    assert.equal(response.status(), 200);
    await page.getByRole("heading", { name: `${report.scope.phase} 示例证据报告`, exact: true }).waitFor();
    assert.match(await page.locator("body").innerText(), new RegExp(`所选范围：${name === "fixed" ? "pass" : "fail"}`));
    assert.equal(await page.locator("tbody tr").count(), report.checks.length);
    assert.equal(await page.locator("details[id^=e-]").count(), report.observations.length);
    if (["E5", "E6"].includes(report.scope.phase)) {
      const timeline = page.getByText("事件、故障、并发、恢复与分项耗时", { exact: true });
      await timeline.click();
      assert.ok((await page.locator("body").innerText()).includes("generator_preparation_ms"));
      await timeline.click();
      checks.push({ name: `${name}: E5 故障与分项耗时可查看`, result: "passed" });
    }
    await page.screenshot({ path: `${directory}/report-${name}-desktop.png` });
    const anchor = page.locator('tbody a[href^="#e-"]').first();
    const href = await anchor.getAttribute("href");
    await anchor.click();
    assert.equal(new URL(page.url()).hash, href);
    await page.locator(href).evaluate(element => element.open = true);
    assert.ok((await page.locator(href + " pre").innerText()).includes("observation_id"));
    checks.push({ name: `${name}: 真实报告、四态表、证据锚点`, result: "passed" });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(url);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: `${directory}/report-${name}-mobile.png` });
    checks.push({ name: `${name}: 390px 报告无页面溢出`, result: "passed" });
    await page.setViewportSize({ width: 1440, height: 1000 });
  }
  assert.deepEqual(errors, []);
  checks.push({ name: "报告无浏览器运行时异常", result: "passed" });
  await writeFile(`${directory}/report-browser-results.json`, JSON.stringify({ browser: await browser.version(), checks }, null, 2));
  console.log(`${checks.length} 项 HTML 报告浏览器检查通过`);
} finally {
  await browser.close();
}
