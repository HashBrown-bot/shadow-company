"use client";

import { useState } from "react";

type Reply = {
  run_id?: string; status?: string; verdict?: string; mode?: string; calls_put?: boolean;
  repair_verified?: boolean; source_verdict?: string; target_verdict?: string;
  confounders?: string[]; non_comparable?: string[]; path_deviations?: unknown[];
  input_deviations?: unknown[]; control_boundary?: unknown; replay?: unknown;
  error?: { message?: string; details?: { path: string; message: string }[] };
};

async function request(path: string, body?: unknown): Promise<Reply> {
  const response = await fetch(`/api/backend/${path}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error([data.error?.message || `请求失败 (${response.status})`, ...(data.error?.details || []).map((d: { message: string }) => d.message)].join("\n"));
  return data;
}

export default function ReplayPanel() {
  const [project, setProject] = useState("");
  const [source, setSource] = useState("");
  const [contract, setContract] = useState("fixed");
  const [version, setVersion] = useState("fixed");
  const [mode, setMode] = useState("history");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [result, setResult] = useState<Reply | null>(null);
  const [comparison, setComparison] = useState<Reply | null>(null);
  const [reportUrl, setReportUrl] = useState("");

  return <section className="panel replay-panel" aria-labelledby="replay-title">
    <div className="section-heading"><span className="number">03</span><div><h2 id="replay-title">E6 重放与比较</h2><p>选择已有运行；新基线和目标契约通过本机 API 或 E6 演示助手创建。</p></div></div>
    <form onSubmit={async event => {
      event.preventDefault(); setBusy(true); setError(""); setResult(null); setComparison(null); setReportUrl("");
      const query = new URLSearchParams({ project_id: project });
      try {
        setStatus(mode === "history" ? "正在读取历史…" : "正在创建新的隔离运行…");
        const output = await request(`runs/${encodeURIComponent(source)}/replay`, mode === "history" ? { project_id: project, mode } : {
          project_id: project, mode, target_contract_version: contract, target_product_version: version,
          idempotency_key: crypto.randomUUID(), reuse_product_outputs: false,
        });
        if (mode === "history") {
          setResult(output); setStatus(output.calls_put === false ? "历史已读取；未创建运行，未调用 PUT。" : "历史响应已读取。");
        } else {
          const target = output.run_id;
          setStatus(`运行 ${target} 已入队；正在采集新的产品响应与独立账本…`);
          const deadline = Date.now() + 180_000;
          while (true) {
            const run = await request(`runs/${target}?${query}`);
            if (["completed", "failed", "cancelled"].includes(run.status || "")) break;
            if (Date.now() > deadline) throw new Error(`等待超时，未生成完成结论。run：${target}；可通过 API 继续查询。`);
            await new Promise(resolve => setTimeout(resolve, 500));
          }
          const report = await request(`runs/${target}/report?${query}`);
          const compareQuery = new URLSearchParams({ project_id: project, other_run_id: target || "" });
          const compared = await request(`runs/${encodeURIComponent(source)}/compare?${compareQuery}`);
          setResult(report); setComparison(compared);
          setReportUrl(`/api/backend/runs/${target}/report?${query}&format=html`);
          setStatus(`生命周期：${report.status} · 新运行结论：${report.verdict}`);
        }
      } catch (e) { setError(e instanceof Error ? e.message : "重放失败"); setStatus(""); }
      finally { setBusy(false); }
    }}>
      <div className="replay-fields"><div><label htmlFor="replay-project">项目 ID</label><input id="replay-project" value={project} onChange={e => setProject(e.target.value.trim())} required disabled={busy} /></div>
        <div><label htmlFor="replay-source">源 run ID</label><input id="replay-source" value={source} onChange={e => setSource(e.target.value.trim())} required disabled={busy} /></div></div>
      <label htmlFor="replay-mode">重放模式</label><select id="replay-mode" value={mode} onChange={e => setMode(e.target.value)} disabled={busy}>
        <option value="history">history · 只读历史</option><option value="input">input · 调用目标版本</option><option value="controlled">controlled · 本机受控边界</option>
      </select>
      <p className="replay-explanation">{mode === "history" ? "只显示已保存的 trace 和结果，不调用 PUT，也不用于验证修复。" : mode === "input" ? "使用新 run 命名空间，重放角色输入与故障，重新采集响应、Webhook 和 provider 账本。" : "控制本机示例的初始数据、语义故障、平台调度和 barrier；不控制外部时钟、网络时延或竞争胜者。"}</p>
      {mode !== "history" && <div className="replay-fields"><div><label htmlFor="replay-contract">目标契约版本（须已预检）</label><input id="replay-contract" value={contract} onChange={e => setContract(e.target.value)} required disabled={busy} /></div>
        <div><label htmlFor="replay-version">目标 PUT 版本</label><select id="replay-version" value={version} onChange={e => setVersion(e.target.value)} disabled={busy}><option value="fixed">fixed</option><option value="buggy">buggy</option></select></div></div>}
      <button disabled={busy || !project || !source}>{busy ? "处理中…" : mode === "history" ? "查看历史" : "启动重放并比较"}</button>
    </form>
    <p role="status" data-testid="replay-status">{status}</p>
    {error && <pre className="validation-error" role="alert">{error}</pre>}
    {comparison && <div className="result" data-testid="replay-comparison"><strong>{comparison.repair_verified ? "已在声明范围验证修复" : "尚未验证修复"}</strong><p>{comparison.source_verdict} → {comparison.target_verdict}</p>
      <p>条件变化：{comparison.confounders?.join("、") || "无"}</p><p>不可比较：{comparison.non_comparable?.join("、")}</p>
      <details><summary>路径偏离与合法重试变化</summary><pre>{JSON.stringify(comparison.path_deviations, null, 2)}</pre></details>
      <details><summary>角色输入偏离</summary><pre>{JSON.stringify(comparison.input_deviations, null, 2)}</pre></details>
      <details><summary>实际控制边界</summary><pre>{JSON.stringify(comparison.control_boundary, null, 2)}</pre></details>
      <a href={reportUrl} target="_blank" rel="noreferrer">查看新运行证据报告 ↗</a></div>}
    {result && <details><summary>后端原始结果与 Manifest</summary><pre className="replay-json">{JSON.stringify(result, null, 2)}</pre></details>}
    <p>不宣称任意 staging 完全确定性。示例工程验证不代表真实客户、生产或 E7—E10 已完成。</p>
  </section>;
}
