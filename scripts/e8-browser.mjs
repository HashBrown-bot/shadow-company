import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const directory=process.env.EVIDENCE_DIR||"docs/evidence/e8/browser";
await mkdir(directory,{recursive:true});
const browser=await chromium.launch({channel:"chrome",headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:"reduce"});
page.setDefaultTimeout(15000);
const errors=[],results=[];
page.on("pageerror",e=>errors.push(e.message));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const origin="http://127.0.0.1:3000";
const backend="http://127.0.0.1:8000/api";
async function shot(name) {
  if(page.viewportSize().width>=600)return page.screenshot({path:`${directory}/${name}.png`,fullPage:true});
  // Capture real visible viewports to avoid Chrome tall-page screenshot tiling artifacts.
  const position=await page.evaluate(()=>scrollY);
  await page.evaluate(()=>scrollTo(0,0));
  await page.screenshot({path:`${directory}/${name}.png`,fullPage:false});
  const gate=page.getByRole("region",{name:"严格比较 CI gate",exact:true});
  if(await gate.count())await gate.scrollIntoViewIfNeeded();
  else await page.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight));
  await page.screenshot({path:`${directory}/${name}-lower-viewport.png`,fullPage:false});
  await page.evaluate(y=>scrollTo(0,y),position);
}
const save=(name,value)=>writeFile(`${directory}/${name}.json`,JSON.stringify(value,null,2)+"\n");
const hash=value=>createHash("sha256").update(JSON.stringify(value)).digest("hex");
const probe=(...args)=>execFileSync(".venv/bin/python",["-m","scripts.e8_probe",...args],{stdio:"pipe"}).toString().trim();
const accessToken=(await readFile(process.env.SIM_TOKEN_FILE||".local/access/operator.token","utf8")).trim();
await page.context().addCookies([{name:"sim_session",value:accessToken,url:origin,httpOnly:true,sameSite:"Strict"}]);
async function json(path,body,method=body===undefined?"GET":"POST") {
  const response=await page.request.fetch(`${backend}/${path}`,{method,data:body,headers:{Authorization:`Bearer ${accessToken}`}});
  assert.ok(response.ok(),`${method} ${path}: ${response.status()} ${await response.text()}`);
  return response.json();
}
async function check(name,task) {
  try {await task();results.push({name,result:"passed"});console.log(`PASS ${name}`);}
  catch(e){results.push({name,result:"failed",message:e.message});await shot("failure").catch(()=>{});throw e;}
  finally{await save(process.env.E8_RESTART_ONLY?"restart-results":"browser-results",{at:new Date().toISOString(),browser:await browser.version(),results});}
}
async function openRun(p,r){await page.goto(`${origin}/?project=${p}&view=run&run=${r}`);await page.getByRole("heading",{name:"运行详情",exact:true}).waitFor();}
async function completed(p,r) {
  const deadline=Date.now()+90000;
  while(Date.now()<deadline){const v=await json(`runs/${r}?project_id=${p}`);if(["completed","failed","cancelled"].includes(v.status))return json(`runs/${r}/report?project_id=${p}`);await pause(150);}
  throw new Error(`run did not finish: ${r}`);
}
async function startedRun() {await page.waitForURL(url=>url.searchParams.get("view")==="run"&&!!url.searchParams.get("run"));return new URL(page.url()).searchParams.get("run");}
async function newRun(p,c,scenarios=["S01"]){return (await json("runs",{project_id:p,contract_version:c,suite_scope:"e7_core_20",scenarios,idempotency_key:crypto.randomUUID()})).run_id;}
async function displayedGate(testId,gate){
  const node=page.getByTestId(testId);
  await node.filter({hasText:`退出码 ${gate.exit_code}`}).waitFor();
  const text=await node.innerText();
  assert.ok(text.includes(gate.verdict),`${testId} must show the backend gate verdict`);
  for(const reason of gate.reasons)assert.ok(text.includes(reason),`${testId} must show every backend gate reason`);
  return {exit_code:gate.exit_code,verdict:gate.verdict,text};
}
function cliComparison(p,s,t){
  let stdout,exitCode=0;
  try{
    stdout=execFileSync(".venv/bin/python",["-m","packages.simctl","compare","--project",p,"--source",s,"--target",t,"--gate","selected"],{stdio:"pipe",encoding:"utf8",timeout:30000,maxBuffer:10*1024*1024});
  }catch(error){
    // A nonzero business gate is an expected result. Do not echo process output,
    // command environments or credential files when transport/execution fails.
    assert.ok(Number.isInteger(error.status)&&error.stdout,"simctl compare did not return a process result");
    exitCode=error.status;stdout=error.stdout.toString();
  }
  let envelope;
  try{envelope=JSON.parse(stdout);}catch{throw new Error("simctl compare did not return JSON");}
  assert.equal(envelope.command,"compare");
  assert.equal(envelope.exit_code,exitCode);
  return {exit_code:exitCode,envelope};
}
const consistency={schema_version:"e10-ui-cli-consistency-1",example:true};
let project,source,target,sourceReport,targetReport,sourceHistory,mainContract;
try {
 if(process.env.E8_RESTART_ONLY){
   const runtime=JSON.parse(await readFile(`${directory}/runtime.json`,"utf8"));
   await check("真实 PostgreSQL 与全部服务重启后 URL 恢复目标结论",async()=>{await openRun(runtime.project_id,runtime.target_run_id);await page.locator(".run-banner .verdict.pass").waitFor();const report=await json(`runs/${runtime.target_run_id}/report?project_id=${runtime.project_id}`);assert.equal(report.verdict,"pass");await shot("restart-restored");});
   await check("重启后真实版本比较仍确认修复",async()=>{await page.getByRole("button",{name:"查看与源运行的版本比较 →"}).click();await page.getByRole("heading",{name:"✓ 已在声明范围验证修复"}).waitFor();await page.reload();await page.getByRole("heading",{name:"✓ 已在声明范围验证修复"}).waitFor();});
 }else{
   await page.goto(origin);
   await check("空项目来自真实空数据库",async()=>{assert.equal((await json("projects")).total,0);await page.getByRole("heading",{name:"还没有项目"}).waitFor();await page.getByText("本地单团队 · V2",{exact:true}).waitFor();await page.getByText("真实模型与客户验证未执行 · 未部署生产",{exact:true}).waitFor();await shot("01-empty-projects-desktop");});
   await check("键盘跳过导航与可见焦点",async()=>{await page.keyboard.press("Tab");assert.equal(await page.locator(":focus").innerText(),"跳到主要内容");await page.keyboard.press("Enter");assert.equal(await page.locator(":focus").getAttribute("id"),"main");await page.getByLabel("项目名称",{exact:true}).focus();assert.notEqual(await page.locator(":focus").evaluate(e=>getComputedStyle(e).outlineStyle),"none");await shot("02-keyboard-focus");});
   await check("加载状态延迟真实响应而不替换数据",async()=>{let release;const gate=new Promise(r=>release=r);await page.route("**/api/backend/projects?*",async route=>{await gate;await route.continue();},{times:1});await page.getByRole("button",{name:"刷新项目",exact:true}).click();await page.getByText("正在读取后端数据…",{exact:true}).waitFor();await shot("03-loading");release();await page.getByRole("heading",{name:"还没有项目"}).waitFor();});
   await check("浏览器创建项目与无运行状态",async()=>{await page.getByLabel("项目名称",{exact:true}).fill("示例 · 退款与审批验证");await page.getByRole("button",{name:"创建项目",exact:true}).click();await page.getByRole("heading",{name:"项目尚无运行"}).waitFor();project=new URL(page.url()).searchParams.get("project");assert.ok(project);assert.equal((await json(`projects/${project}/runs`)).total,0);assert.equal(await page.locator(":focus").getAttribute("id"),"page-title");await shot("04-project-no-runs");});
   await check("接入向导真实保存 buggy 契约并预检",async()=>{await page.getByRole("button",{name:"开始接入契约"}).click();await page.getByLabel("示例产品版本").selectOption("buggy");await page.getByLabel("契约版本",{exact:true}).fill("buggy-v1");await page.getByRole("button",{name:"下一步 →",exact:true}).click();assert.equal(await page.getByLabel("客服凭据引用").inputValue(),"secret://demo/support");await page.getByRole("button",{name:"下一步 →",exact:true}).click();await page.getByRole("button",{name:"保存契约并预检",exact:true}).click();await page.getByRole("heading",{name:"✓ 接入预检通过",exact:true}).first().waitFor();const pf=await json(`projects/${project}/preflight?contract_version=buggy-v1`);assert.equal(pf.result.passed,true);await shot("05-contract-preflight");});
   await check("配置说明、未支持能力禁用及键盘复选框",async()=>{await page.getByRole("button",{name:"配置运行 →",exact:true}).click();await page.getByRole("button",{name:"启动真实运行",exact:true}).waitFor();assert.equal(await page.getByRole("radio",{name:/受控时钟/}).isDisabled(),true);assert.equal(await page.getByRole("checkbox",{name:/启用真实模型/}).isDisabled(),true);const s=page.getByRole("checkbox",{name:/S01 /});await s.focus();await page.keyboard.press("Space");assert.equal(await s.isChecked(),true);await page.keyboard.press("Space");assert.equal(await s.isChecked(),false);assert.equal(await page.getByRole("checkbox",{name:/S12 /}).isChecked(),true);await shot("06-config-desktop");await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await shot("07-config-narrow");await page.setViewportSize({width:1440,height:1000});});
   await check("浏览器启动 buggy 并得到后端失败",async()=>{await page.getByRole("button",{name:"启动真实运行",exact:true}).click();source=await startedRun();sourceReport=await completed(project,source);assert.equal(sourceReport.verdict,"fail");await page.locator(".run-banner .verdict.fail").waitFor();assert.match(await page.locator("main").innerText(),/同一指令产生多次独立成功执行/);await save("buggy-report",sourceReport);sourceHistory=await json(`runs/${source}/history?project_id=${project}`);await shot("08-buggy-failed");});
   await check("同一 buggy 运行的 API、console 与 UI 严格 gate 均为 1",async()=>{
     const consoleResult=await json(`runs/${source}/console?project_id=${project}`);
     assert.equal(consoleResult.run.run_id,source);
     assert.deepEqual(consoleResult.report.ci_gates,sourceReport.ci_gates);
     await page.getByRole("region",{name:"严格 CI gate",exact:true}).waitFor();
     const ui={};
     for(const selection of ["selected","suite"]){const gate=sourceReport.ci_gates[selection];assert.equal(gate.exit_code,1);ui[selection]=await displayedGate(`ci-${selection}`,gate);}
     consistency.project_id=project;
     consistency.source={run_id:source,business_verdict:sourceReport.verdict,api_gates:sourceReport.ci_gates,console_gates:consoleResult.report.ci_gates,ui};
     await save("e10-ui-cli-consistency",consistency);await shot("25-source-strict-gate");
   });
   await check("Finding 显示规则版本、预期实际、脱敏请求及新账本",async()=>{await page.getByRole("button",{name:"同一指令产生多次独立成功执行 →",exact:true}).click();await page.getByRole("heading",{name:"独立支付账本",exact:true}).waitFor();await page.getByRole("heading",{name:"预期结果",exact:true}).waitFor();assert.equal(sourceReport.versions.rule_version,"2");await page.getByText(`REFUND_001 · 契约规则 v1 · Evaluator v${sourceReport.versions.rule_version}`,{exact:true}).waitFor();assert.equal(await page.locator(".ledger-entry").count(),2);await page.getByText("脱敏请求 / 响应与来源",{exact:true}).first().click();assert.match(await page.locator(".evidence-card").first().innerText(),/\[REDACTED\]/);await shot("09-finding-evidence");const controls=page.getByRole("button",{name:"证据下一页"});assert.equal(await controls.isDisabled(),false);await controls.click();await page.getByRole("button",{name:"证据上一页"}).waitFor({state:"visible"});await page.getByRole("button",{name:"证据上一页"}).click();await page.setViewportSize({width:390,height:844});await page.getByRole("heading",{name:"独立支付账本",exact:true}).waitFor();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await shot("10-finding-narrow");await page.setViewportSize({width:1440,height:1000});});
   await check("选择 fixed 触发真实 input replay 并通过",async()=>{await page.getByRole("button",{name:"选择目标版本 →",exact:true}).click();await page.getByLabel("目标产品版本（示例）").selectOption("fixed");await page.getByRole("button",{name:"开始输入重放",exact:true}).click();target=await startedRun();assert.notEqual(source,target);targetReport=await completed(project,target);assert.equal(targetReport.status,"completed");assert.equal(targetReport.verdict,"pass");assert.equal(targetReport.replay.source_run_id,source);assert.deepEqual(targetReport.replay.fresh_evidence.put_versions,["fixed"]);assert.ok(targetReport.replay.fresh_evidence.put_business_calls>0);assert.ok(!targetReport.replay.fresh_evidence.ledger_entry_ids.some(id=>sourceReport.replay.fresh_evidence.ledger_entry_ids.includes(id)));mainContract=targetReport.versions.contract;await page.locator(".run-banner .verdict.pass").waitFor();await save("fixed-report",targetReport);await shot("11-fixed-pass");});
   await check("fixed 业务修复通过仍显示严格 gate 3 与缺审批覆盖",async()=>{
     const consoleResult=await json(`runs/${target}/console?project_id=${project}`);
     assert.equal(consoleResult.run.run_id,target);
     assert.deepEqual(consoleResult.report.ci_gates,targetReport.ci_gates);
     await page.getByRole("region",{name:"严格 CI gate",exact:true}).waitFor();
     const ui={};
     for(const selection of ["selected","suite"]){const gate=targetReport.ci_gates[selection];assert.equal(gate.exit_code,3);assert.equal(gate.verdict,"inconclusive");assert.ok(gate.reasons.some(reason=>reason.includes("APPROVAL_001")));ui[selection]=await displayedGate(`ci-${selection}`,gate);}
     consistency.target={run_id:target,business_verdict:targetReport.verdict,api_gates:targetReport.ci_gates,console_gates:consoleResult.report.ci_gates,ui};
     await save("e10-ui-cli-consistency",consistency);await shot("26-fixed-business-pass-ci-incomplete");
   });
   await check("后端比较确认修复、显示路径 2→1 与未验证范围",async()=>{await page.getByRole("button",{name:"查看与源运行的版本比较 →",exact:true}).click();await page.getByRole("heading",{name:"✓ 已在声明范围验证修复"}).waitFor();const c=await json(`runs/${source}/compare?project_id=${project}&other_run_id=${target}`);assert.equal(c.repair_verified,true);assert.ok(c.path_deviations.some(x=>x.expected_path_calls===2&&x.actual_path_calls===1));assert.match(await page.locator(".path-change").innerText(),/2 → 1/);assert.match(await page.locator("main").innerText(),/S01/);await save("comparison",c);await shot("12-comparison-desktop");await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await shot("13-comparison-narrow");await page.setViewportSize({width:1440,height:1000});});
   await check("同一次真实比较的 API、UI 与 simctl 子进程严格 gate 一致",async()=>{
     const comparison=await json(`runs/${source}/compare?project_id=${project}&other_run_id=${target}`);
     assert.equal(comparison.source_run_id,source);assert.equal(comparison.target_run_id,target);
     assert.equal(comparison.repair_verified,true);
     assert.deepEqual(comparison.target_ci_gates,targetReport.ci_gates);
     await page.getByRole("region",{name:"严格比较 CI gate",exact:true}).waitFor();
     const ui={};
     for(const selection of ["selected","suite"]){const gate=comparison.ci_gates[selection];assert.equal(gate.exit_code,3);assert.ok(gate.reasons.some(reason=>reason.includes("APPROVAL_001")));ui[selection]=await displayedGate(`compare-ci-${selection}`,gate);}
     const cli=cliComparison(project,source,target);
     assert.equal(cli.exit_code,3);assert.equal(cli.envelope.data.comparison.source_run_id,source);assert.equal(cli.envelope.data.comparison.target_run_id,target);
     assert.deepEqual(cli.envelope.data.comparison.ci_gates,comparison.ci_gates);
     assert.deepEqual(cli.envelope.data.target_gate,comparison.target_ci_gates.selected);
     assert.equal(cli.envelope.data.comparison.repair_verified,true);
     consistency.comparison={source_run_id:source,target_run_id:target,repair_verified:comparison.repair_verified,api_gates:comparison.ci_gates,target_ci_gates:comparison.target_ci_gates,ui,cli:{command:"simctl compare",exit_code:cli.exit_code,source_run_id:cli.envelope.data.comparison.source_run_id,target_run_id:cli.envelope.data.comparison.target_run_id,ci_gates:cli.envelope.data.comparison.ci_gates,target_gate:cli.envelope.data.target_gate}};
     await save("e10-ui-cli-consistency",consistency);await shot("27-compare-ui-api-cli-consistent");
   });
   await check("刷新 URL 恢复目标与比较，源历史完全不变",async()=>{const url=page.url();await page.reload();await page.getByRole("heading",{name:"✓ 已在声明范围验证修复"}).waitFor();assert.equal(page.url(),url);const after=await json(`runs/${source}/history?project_id=${project}`);assert.equal(hash(sourceHistory),hash(after));await save("source-history-hashes",{before:hash(sourceHistory),after:hash(after)});await openRun(project,target);await page.locator(".run-banner .verdict.pass").waitFor();await page.reload();await page.locator(".run-banner .verdict.pass").waitFor();});
   await check("因果时间线四来源与服务端分页",async()=>{await page.getByRole("button",{name:"因果时间线",exact:true}).click();for(const lane of ["actor","product","provider","evaluator"]){await page.getByLabel("证据泳道").selectOption(lane);await page.locator(".timeline li").first().waitFor();const apiResult=await json(`runs/${target}/timeline?project_id=${project}&lane=${lane}&limit=10`);assert.ok(apiResult.items.length>0);assert.ok(apiResult.items.every(t=>t.lane===lane));}await page.getByLabel("证据泳道").selectOption("all");await page.getByRole("button",{name:"时间线下一页"}).click();await page.locator(".pager").getByText(/第 2 /).waitFor();assert.equal(await page.locator(":focus").getAttribute("aria-label"),"时间线分页");await shot("14-timeline");});
   await check("四态文字和符号、检查分页与键盘展开",async()=>{await page.getByRole("button",{name:"四态检查",exact:true}).click();await page.getByRole("heading",{name:/四态检查 ·/}).waitFor();await page.locator(".verdict.not_applicable").first().waitFor();assert.match(await page.locator(".verdict.not_applicable").first().innerText(),/—.*不适用/s);await page.getByRole("button",{name:"预算与清单",exact:true}).click();const summary=page.getByText("清单版本与内容哈希",{exact:true});await summary.focus();await page.keyboard.press("Enter");assert.equal(await summary.evaluate(el=>el.parentElement.open),true);await shot("15-keyboard-details");});
   await check("真实排队及取消状态，不可显示通过",async()=>{probe("pause");try{const run=await newRun(project,mainContract);await openRun(project,run);await page.getByText("○ 等待 Worker 领取",{exact:true}).waitFor();await page.getByRole("button",{name:"取消运行",exact:true}).click();await page.getByText("⊘ 运行已取消",{exact:true}).waitFor();const r=await completed(project,run);assert.equal(r.status,"cancelled");assert.equal(r.verdict,"inconclusive");await save("cancelled-report",r);await shot("16-cancelled");}finally{probe("resume");}});
   await check("实际暂停 Worker 导致租约失联，恢复后可取消",async()=>{const run=await newRun(project,mainContract,["S18"]);let running=false;for(let i=0;i<100;i++){const s=await json(`runs/${run}?project_id=${project}`);if(s.status==="running"){running=true;break;}await pause(30);}assert.equal(running,true);probe("pause");try{await openRun(project,run);await page.getByText("! Worker 失联",{exact:true}).waitFor();const d=await json(`runs/${run}/console?project_id=${project}`);assert.equal(d.worker.state,"lost");assert.equal(d.run.status,"running");assert.equal(d.run.verdict,"inconclusive");await shot("17-worker-lost");await page.getByRole("button",{name:"取消运行",exact:true}).click();}finally{probe("resume");}const r=await completed(project,run);assert.notEqual(r.verdict,"pass");await save("worker-resumed-report",r);});
   await check("真实支付观测丢失后刷新撤回通过结论",async()=>{const run=await newRun(project,mainContract);const before=await completed(project,run);assert.equal(before.verdict,"pass");probe("lose-ledger",project,run);await openRun(project,run);await page.getByText("? 证据不足或运行范围未完成",{exact:true}).waitFor();const after=await json(`runs/${run}/report?project_id=${project}`);assert.equal(after.verdict,"inconclusive");await page.locator(".run-banner .verdict.inconclusive").waitFor();await page.reload();await page.locator(".run-banner .verdict.inconclusive").waitFor();await save("evidence-loss-report",after);await shot("18-insufficient-evidence");});
   await check("真实预算耗尽的终止状态",async()=>{const c=await json(`projects/${project}/contract/${mainContract}`);const name="budget-one";await json(`projects/${project}/contract`,{version:name,config:{...c.config,runtime:{...c.config.runtime,max_events:1}}},"PUT");assert.equal((await json(`projects/${project}/preflight`,{contract_version:name})).passed,true);const run=await newRun(project,name);const report=await completed(project,run);assert.equal(report.status,"failed");assert.equal(report.verdict,"inconclusive");await openRun(project,run);await page.getByText("! 运行终止",{exact:true}).waitFor();await shot("19-budget-exhausted");await save("budget-report",report);});
   await check("真实 404 资源错误独立展示",async()=>{await openRun(project,crypto.randomUUID());await page.getByText("! 未找到记录",{exact:true}).waitFor();await shot("20-not-found");});
   await page.goto(origin);
   await check("真实跨来源防护返回 403，界面无权限且没有写入",async()=>{const before=(await json("projects")).total;await page.getByLabel("项目名称",{exact:true}).fill("不应创建的项目");await page.route("**/api/backend/projects",async route=>{const response=await route.fetch({headers:{...route.request().headers(),origin:"http://untrusted.example"}});assert.equal(response.status(),403);await route.fulfill({response});});await page.getByRole("button",{name:"创建项目",exact:true}).click();await page.getByText("! 无权限执行此操作",{exact:true}).waitFor();assert.equal((await json("projects")).total,before);await shot("21-permission-denied");await page.unroute("**/api/backend/projects");});
   await check("连接失败显示错误、不回退假数据，恢复后重试",async()=>{await page.route("**/api/backend/projects?*",route=>route.abort("connectionrefused"));await page.getByRole("button",{name:"刷新项目",exact:true}).click();await page.getByText("! 连接异常",{exact:true}).waitFor();assert.equal(await page.locator("table tbody tr").count(),0);await shot("22-connection-error");await page.unroute("**/api/backend/projects?*");await page.getByRole("button",{name:"重试读取",exact:true}).click();await page.getByText("示例 · 退款与审批验证",{exact:true}).waitFor();});
   await check("长项目列表服务端分页与窄屏表格容器",async()=>{for(let i=1;i<=11;i++)await json("projects",{name:`示例 · 分页验收 ${i}`});await page.getByRole("button",{name:"刷新项目",exact:true}).click();await page.getByText("示例 · 分页验收 11",{exact:true}).waitFor();assert.equal(await page.locator("tbody tr").count(),10);const first=await page.locator("tbody").innerText();await page.getByRole("button",{name:"项目下一页"}).click();await page.getByText("示例 · 退款与审批验证",{exact:true}).waitFor();assert.equal(await page.locator("tbody tr").count(),2);assert.notEqual(await page.locator("tbody").innerText(),first);await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.locator(".table-scroll").focus();await page.keyboard.press("ArrowRight");await shot("23-projects-narrow-pagination");await page.setViewportSize({width:1440,height:1000});});
   await check("表单字段有标签，语义 landmark 与页面语言完整",async()=>{await page.goto(`${origin}/?project=${project}&view=configure&contract=${mainContract}`);await page.getByRole("button",{name:"启动真实运行",exact:true}).waitFor();assert.equal(await page.locator("html").getAttribute("lang"),"zh-CN");assert.equal(await page.getByRole("main").count(),1);const unlabelled=await page.locator("input, select, textarea").evaluateAll(els=>els.filter(e=>!e.labels?.length&&!e.getAttribute("aria-label")&&!e.getAttribute("aria-labelledby")).map(e=>e.id));assert.deepEqual(unlabelled,[]);});
   await check("YAML 缺少独立账本在界面显示后端字段错误",async()=>{await page.locator(`a[href="/?project=${project}&view=contract"]`).click();await page.getByText("高级：导入已有 YAML 契约",{exact:true}).click();const catalog=await json("console/catalog");await page.getByLabel("配置内容",{exact:true}).fill(catalog.template_yaml.replace("    provider_ledger: required\n",""));await page.getByRole("button",{name:"校验并导入",exact:true}).click();await page.getByRole("alert").filter({hasText:"product.observations.provider_ledger"}).waitFor();await shot("24-schema-error");});
   await check("无浏览器运行时错误",async()=>assert.deepEqual(errors,[]));
   await save("runtime",{project_id:project,source_run_id:source,target_run_id:target,main_contract:mainContract,example:true,source_verdict:sourceReport.verdict,target_verdict:targetReport.verdict});
 }
} finally {
 await save(process.env.E8_RESTART_ONLY?"restart-results":"browser-results",{at:new Date().toISOString(),browser:await browser.version(),results,errors});
 await browser.close();
}
