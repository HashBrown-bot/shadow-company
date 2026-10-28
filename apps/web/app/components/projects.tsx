"use client";
import { useState } from "react";
import { api, Navigate, PageData, Project, Run, useResource } from "./api";
import { Badge, Empty, ErrorBox, Heading, Loading, Pager, Status, Time } from "./ui";

export function Projects({ navigate }: {navigate:Navigate}) {
  const [offset,setOffset] = useState(0), [name,setName] = useState("");
  const [busy,setBusy] = useState(false), [error,setError] = useState<Error|null>(null);
  const data = useResource<PageData<Project>>(`projects?limit=10&offset=${offset}`);
  return <><Heading eyebrow="WORKSPACE / 本地团队" title="项目"><span className="tag">退款与审批 · 本地测试</span></Heading>
    <p className="lede">从接入契约到独立证据，追踪每一次业务验证。</p>
    <section className="panel"><div className="section-head"><div><h2>创建项目</h2><p>接入前没有测试结论。示例服务使用独立的项目与运行命名空间。</p></div><span className="section-num">01</span></div>
      <form className="create-row" onSubmit={async e => { e.preventDefault(); setBusy(true); setError(null); try { const p = await api<Project>("projects",{ name }); navigate({project:p.id,view:"runs"}); } catch(e) {setError(e as Error);} finally {setBusy(false);} }}>
        <div className="field"><label htmlFor="project-name">项目名称</label><input id="project-name" value={name} onChange={e=>setName(e.target.value)} placeholder="例如：示例退款验证" maxLength={120} required /></div><button disabled={busy || !name.trim()}>{busy ? "正在创建…" : "创建项目"}</button>
      </form><ErrorBox error={error} />
    </section>
    <section className="panel"><div className="section-head"><h2>所有项目</h2><button className="secondary" onClick={data.refresh} disabled={data.loading}>刷新项目</button></div>
      {data.loading ? <Loading /> : data.error ? <ErrorBox error={data.error} retry={data.refresh}/> : data.data?.total === 0 ? <Empty title="还没有项目"><p>创建第一个项目，再接入示例退款产品。</p></Empty> : data.data && <><div className="table-scroll" tabIndex={0} role="region" aria-label="项目列表"><table><thead><tr><th>项目</th><th>产品版本</th><th>最近运行</th><th>业务结论</th><th>操作</th></tr></thead><tbody>{data.data.items.map(p=><tr key={p.id}><td><strong>{p.name}</strong><code className="sub-id">{p.id}</code></td><td>{p.product_versions.length ? p.product_versions.join(" / ") : "尚未接入"}</td><td>{p.latest_run ? <><Status status={p.latest_run.status}/><small className="block"><Time value={p.latest_run.created_at}/></small></> : "暂无运行"}</td><td>{p.latest_run ? <Badge value={p.latest_run.verdict}/> : "—"}</td><td><button className="text-button" onClick={()=>navigate({project:p.id,view:"runs"})} aria-label={`打开项目 ${p.name}`}>打开 →</button></td></tr>)}</tbody></table></div><Pager name="项目" {...data.data} onChange={setOffset}/></>}
    </section></>;
}

export function Runs({ project, navigate }: {project:string; navigate:Navigate}) {
  const [offset,setOffset] = useState(0);
  const runs = useResource<PageData<Run>>(`projects/${project}/runs?limit=10&offset=${offset}`, 3000);
  return <><Heading eyebrow="RUNS / 运行记录" title="运行与验证"><button onClick={()=>navigate({project,view:"configure"})}>＋ 配置新运行</button></Heading><p className="lede">先关注失败和证据缺失，再核对覆盖范围。运行结束与业务通过分别记录。</p>
    <section className="panel">{runs.loading ? <Loading/> : runs.error ? <ErrorBox error={runs.error} retry={runs.refresh}/> : runs.data?.total === 0 ? <Empty title="项目尚无运行"><p>先保存接入契约并完成预检，再选择场景与预算。</p><button onClick={()=>navigate({project,view:"contract"})}>开始接入契约</button></Empty> : runs.data && <><div className="table-scroll" tabIndex={0} role="region" aria-label="运行列表"><table><thead><tr><th>业务结论</th><th>生命周期</th><th>版本 / 运行</th><th>创建时间</th><th>操作</th></tr></thead><tbody>{runs.data.items.map(r=><tr key={r.run_id}><td><Badge value={r.verdict}/></td><td><Status status={r.status}/>{r.stop_reason&&<small className="block">{r.stop_reason}</small>}</td><td><strong>{r.put_version}</strong><span className="tag small-tag">示例</span><code className="sub-id">{r.run_id}</code></td><td><Time value={r.created_at}/></td><td><button className="text-button" onClick={()=>navigate({project,run:r.run_id,view:"run"})}>查看运行 →</button></td></tr>)}</tbody></table></div><Pager name="运行" {...runs.data} onChange={setOffset}/></>}</section>
  </>;
}
