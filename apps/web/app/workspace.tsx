"use client";
import { useEffect, useRef, useState } from "react";
import { Catalog, Navigate, Project, Route, useResource } from "./components/api";
import { ErrorBox, Loading } from "./components/ui";
import { Projects, Runs } from "./components/projects";
import { ContractWizard } from "./components/contract";
import { Configure } from "./components/configure";
import { RunDetail } from "./components/run-detail";
import { FindingPage } from "./components/finding";
import { Compare, Replay } from "./components/replay";

function readRoute():Route { return Object.fromEntries(new URLSearchParams(window.location.search)) as Route; }
export default function Console() {
  const [route,setRoute]=useState<Route|null>(null);
  const wantFocus=useRef(false);
  const health=useResource<{migration:string;phase:string}>("health",15000);
  const catalog=useResource<Catalog>("console/catalog");
  const project=useResource<Project>(route?.project?`projects/${encodeURIComponent(route.project)}`:null);
  const navigate:Navigate=r=>{wantFocus.current=true;const qs=new URLSearchParams(Object.fromEntries(Object.entries(r).filter(([,v])=>!!v) as [string,string][]));window.history.pushState(null,"",qs.size?`/?${qs}`:"/");setRoute(r);window.scrollTo({top:0});};
  useEffect(()=>{setRoute(readRoute());const pop=()=>{wantFocus.current=true;setRoute(readRoute());};window.addEventListener("popstate",pop);return()=>window.removeEventListener("popstate",pop);},[]);
  useEffect(()=>{document.title=`${project.data?.name?`${project.data.name} · `:""}Shadow 仿真测试工作台`;},[project.data]);
  useEffect(()=>{if(wantFocus.current){const heading=document.getElementById("page-title");if(heading){heading.focus({preventScroll:true});wantFocus.current=false;}}},[route,project.loading,catalog.loading]);
  const p=route?.project, v=route?.view||"runs";
  const tabs=[["runs","运行记录","◷"],["contract","接入契约","◇"],["configure","运行配置","⊞"]];
  return <><a className="skip" href="#main">跳到主要内容</a><div className="app-shell"><aside className="sidebar"><a className="brand" href="/" onClick={e=>{e.preventDefault();navigate({});}}><span className="mark" aria-hidden="true">S</span><span>SHADOW<small>仿真测试工作台</small></span></a><span className="sidebar-label">工作空间</span><nav aria-label="主导航"><a href="/" aria-current={!p?"page":undefined} onClick={e=>{e.preventDefault();navigate({});}}><span aria-hidden="true">▦</span> 所有项目</a>{p&&<><span className="sidebar-label project-label">当前项目</span>{tabs.map(([id,name,icon])=><a key={id} href={`/?project=${p}&view=${id}`} aria-current={v===id||id==="runs"&&["run","finding","replay","compare"].includes(v)?"page":undefined} onClick={e=>{e.preventDefault();navigate({project:p,view:id});}}><span aria-hidden="true">{icon}</span>{name}</a>)}</>}</nav><div className="sidebar-bottom"><span>本地单团队 · V2</span><small>规则角色 · 模型默认关闭<br/>示例服务不执行真实付款</small></div></aside>
    <div className="content-shell"><header className="topbar"><div><span className="breadcrumb">工作空间</span>{p&&<> <span aria-hidden="true">/</span> <strong>{project.data?.name||"正在读取项目"}</strong></>}</div><div className="service-state" role="status">{health.loading?"○ 连接中":health.error?"! 服务连接异常":"● API / PostgreSQL 就绪"}<span className="tag">仅本机</span></div></header>
      <main id="main" tabIndex={-1}><ErrorBox error={health.error} retry={health.refresh}/>{!route?<Loading text="正在恢复当前页面…"/>:p&&project.loading?<Loading text="正在恢复项目与运行上下文…"/>:p&&project.error?<ErrorBox error={project.error} retry={project.refresh}/>:!p?<Projects navigate={navigate}/>:v==="runs"?<Runs project={p} navigate={navigate}/>:v==="run"&&route.run?<RunDetail key={route.run} project={p} run={route.run} navigate={navigate}/>:v==="finding"&&route.run&&route.finding?<FindingPage key={route.finding} project={p} run={route.run} finding={route.finding} navigate={navigate}/>:v==="compare"&&route.run&&route.source?<Compare key={`${route.source}/${route.run}`} project={p} run={route.run} source={route.source} navigate={navigate}/>:catalog.loading?<Loading text="正在读取能力与配置 schema…"/>:catalog.error?<ErrorBox error={catalog.error} retry={catalog.refresh}/>:catalog.data&&v==="contract"?<ContractWizard key={p} project={p} navigate={navigate} catalog={catalog.data}/>:catalog.data&&v==="configure"?<Configure key={`${p}/${route.contract||""}`} project={p} selected={route.contract} navigate={navigate} catalog={catalog.data}/>:catalog.data&&v==="replay"&&route.run?<Replay key={route.run} project={p} run={route.run} catalog={catalog.data} navigate={navigate}/>:<ErrorBox error={new Error("页面地址不完整，请从项目列表重新打开。")}/>}
      <footer><span>所有判定来自后端规则与独立证据</span><span>真实模型与客户验证未执行 · 未部署生产</span><a href="/api/backend/contracts/schema" target="_blank" rel="noreferrer">配置 Schema ↗</a></footer></main>
    </div></div></>;
}
