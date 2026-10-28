import assert from "node:assert/strict";
import {readFile,writeFile} from "node:fs/promises";
import {chromium} from "playwright";

const browser=await chromium.launch({channel:"chrome",headless:true});
const page=await browser.newPage({viewport:{width:390,height:844}});
const origin="http://127.0.0.1:3000", directory=process.env.EVIDENCE_DIR;
const results=[];
try {
  await page.goto(origin);
  await page.getByRole("heading",{name:"本地工作台访问"}).waitFor();
  assert.equal((await page.request.get(origin+"/api/backend/projects")).status(),401);
  await page.screenshot({path:`${directory}/e9-login.png`,fullPage:true});
  results.push({name:"anonymous API and UI require token",passed:true});
  await page.getByLabel("访问令牌").fill("invalid");
  const [rejected]=await Promise.all([
    page.waitForResponse(r=>r.url()===origin+"/api/session"&&r.request().method()==="POST"),
    page.getByRole("button",{name:"进入工作台"}).click()
  ]);
  assert.equal(rejected.status(),422);
  await page.getByText("令牌无效、权限不足、过期或服务不可用。",{exact:true}).waitFor();
  assert.equal(await page.getByLabel("访问令牌").inputValue(),"");
  results.push({name:"invalid token rejected and field cleared",passed:true});
  const token=(await readFile(process.env.SIM_TOKEN_FILE,"utf8")).trim();
  await page.getByLabel("访问令牌").fill(token);
  await page.getByRole("button",{name:"进入工作台"}).click();
  await page.getByRole("button",{name:"刷新项目",exact:true}).waitFor();
  const cookie=(await page.context().cookies()).find(c=>c.name==="sim_session");
  assert.ok(cookie?.httpOnly&&cookie.sameSite==="Strict");
  assert.ok(!(await page.evaluate(()=>document.cookie)).includes(token));
  assert.ok(!(await page.content()).includes(token));
  await page.screenshot({path:`${directory}/e9-authenticated.png`,fullPage:true});
  results.push({name:"real login; HttpOnly same-site cookie; no token in DOM",passed:true});
  assert.equal((await page.request.post(origin+"/api/session",{data:{token},headers:{origin:"http://untrusted.example"}})).status(),403);
  results.push({name:"cross-origin session write denied",passed:true});
  await page.getByRole("button",{name:"退出本地会话"}).click();
  await page.getByRole("heading",{name:"本地工作台访问"}).waitFor();
  assert.equal((await page.request.get(origin+"/api/backend/projects")).status(),401);
  results.push({name:"logout revokes browser session",passed:true});
} finally {
  await writeFile(`${directory}/e9-access-results.json`,JSON.stringify({results},null,2));
  await browser.close();
}
console.log(JSON.stringify({checks:results.length,passed:results.every(r=>r.passed)}));
