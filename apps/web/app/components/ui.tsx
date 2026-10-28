"use client";
import { useEffect, useRef, useState } from "react";
import { ApiError, Gates, Verdict } from "./api";

export const verdicts: Record<Verdict, { icon: string; label: string }> = { fail: { icon: "×", label: "失败" }, inconclusive: { icon: "?", label: "证据不足" }, pass: { icon: "✓", label: "通过" }, not_applicable: { icon: "—", label: "不适用" } };
export const lifecycle: Record<string,string> = { queued: "排队中", running: "运行中", completed: "已完成", failed: "运行终止", cancelled: "已取消" };
export const attribution: Record<string,string> = { product_defect: "产品缺陷", expected_rejection: "正常拒绝", actor_error: "角色错误", adapter_error: "适配器错误", environment_error: "环境错误", dependency_failure: "依赖故障", undetermined: "归因未定" };
export const severity: Record<string,string> = { critical: "关键", high: "高", medium: "中", low: "低" };
export function Badge({ value }: { value: Verdict }) { const v = verdicts[value]; return <span className={`verdict ${value}`}><span aria-hidden="true">{v.icon}</span>{v.label}<small>{value}</small></span>; }
export function Status({ status }: {status:string}) { return <span className={`lifecycle ${status}`}><span aria-hidden="true">{status === "running" ? "◉" : status === "cancelled" ? "⊘" : "○"}</span> {lifecycle[status] || status}</span>; }
export function ErrorBox({ error, retry }: { error: Error | null; retry?: () => void }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : new ApiError(error.message);
  const title = e.status === 401 || e.status === 403 ? "无权限执行此操作" : e.status === 404 ? "未找到记录" : e.status === 409 ? "状态或版本冲突" : e.status === 422 ? "配置需要修正" : e.status === 0 || e.status === 503 ? "连接异常" : "服务请求失败";
  return <div className="notice danger" role="alert"><strong>! {title}</strong><p className="preserve">{e.message}</p>{e.requestId && <small>请求 ID：<code>{e.requestId}</code></small>}{retry && <button type="button" className="secondary" onClick={retry}>重试读取</button>}</div>;
}
export function Loading({ text = "正在读取后端数据…" }: {text?:string}) { return <div className="loading" role="status"><span className="spinner" aria-hidden="true" />{text}</div>; }
export function Empty({ title, children }: {title:string; children?:React.ReactNode}) { return <div className="empty"><span aria-hidden="true">◇</span><h3>{title}</h3>{children}</div>; }
export function Json({ value }: {value:unknown}) { return <pre tabIndex={0} className="json" aria-label="结构化证据内容">{JSON.stringify(value, null, 2)}</pre>; }
export function Details({ title, value, open = false }: {title:string; value:unknown; open?:boolean}) { return <details open={open}><summary>{title}</summary><Json value={value} /></details>; }
export function GatePanel({ gates, title = "严格 CI gate", prefix = "ci" }: {gates:Gates | undefined; title?:string; prefix?:string}) {
  const labels = { pass: "✓ 通过", fail: "× 业务失败", error: "! 执行错误", inconclusive: "? 证据不足" };
  return <section className="panel" aria-label={title}><h2>{title}</h2><p>退出码与原因直接来自后端，与 CLI 使用同一结果。业务通过或声明范围修复仍需满足严格 gate 的必需检查。</p>{gates?<div className="split">{(["selected","suite"] as const).map(selection=>{const gate=gates[selection];return <div key={selection} data-testid={`${prefix}-${selection}`} className={`notice ${gate.exit_code===0?"success":gate.exit_code===1||gate.exit_code===2?"danger":"warning"}`}><h3>{selection==="selected"?"所选场景":"完整套件"} · 退出码 {gate.exit_code}</h3><p><strong>{labels[gate.verdict]}</strong> <code>{gate.verdict}</code></p>{gate.reasons.length>0&&<ul>{gate.reasons.map((reason,index)=><li key={index}>{reason}</li>)}</ul>}<small>策略版本：{gate.schema_version}</small></div>;})}</div>:<p role="status">尚无后端严格 gate 结果，不能判定通过。</p>}</section>;
}
const pendingPageFocus = new Map<string, number>();
export function Pager({ total, offset, limit, onChange, name = "列表" }: {total:number; offset:number; limit:number; onChange:(n:number)=>void; name?:string}) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => { const key = `${window.location.href}|${name}`; if ((pendingPageFocus.get(key) || 0) > Date.now()) { ref.current?.focus(); pendingPageFocus.delete(key); } }, [name, offset]);
  const change = (n:number) => { pendingPageFocus.set(`${window.location.href}|${name}`, Date.now() + 15000); onChange(n); };
  return <nav className="pager" aria-label={`${name}分页`} ref={ref} tabIndex={-1}><span>共 {total} 条 · 第 {Math.floor(offset/limit)+1} / {Math.max(1, Math.ceil(total/limit))} 页</span><div><button type="button" className="secondary" aria-label={`${name}上一页`} disabled={offset === 0} onClick={() => change(Math.max(0,offset-limit))}>← 上一页</button><button type="button" className="secondary" aria-label={`${name}下一页`} disabled={offset+limit >= total} onClick={() => change(offset+limit)}>下一页 →</button></div></nav>;
}
export function LocalPage<T>({ items, children, name, size = 10 }: {items:T[]; children:(v:T)=>React.ReactNode; name:string; size?:number}) {
  const [offset,setOffset] = useState(0);
  useEffect(() => { if(offset >= items.length && offset) setOffset(0); },[items.length,offset]);
  return <>{items.slice(offset,offset+size).map(children)}{items.length > size && <Pager name={name} total={items.length} offset={offset} limit={size} onChange={setOffset} />}</>;
}
export function Time({ value }: {value:string | null | undefined}) { return <time dateTime={value || undefined}>{value ? new Date(value).toLocaleString("zh-CN", { hour12:false }) : "尚未记录"}</time>; }
export function Heading({ eyebrow, title, children }: {eyebrow:string; title:string; children?:React.ReactNode}) { return <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1 id="page-title" tabIndex={-1}>{title}</h1></div>{children}</div>; }
