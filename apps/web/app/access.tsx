"use client";
import { FormEvent, useEffect, useState } from "react";
import Console from "./workspace";

export default function Access() {
  const [ready,setReady]=useState(false), [checking,setChecking]=useState(true), [error,setError]=useState("");
  useEffect(()=>{fetch("/api/backend/session",{cache:"no-store"}).then(r=>setReady(r.ok)).catch(()=>setError("无法连接本机服务")).finally(()=>setChecking(false));},[]);
  async function login(event:FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError("");
    const form=event.currentTarget, token=String(new FormData(form).get("token")||"").trim();
    try {
      const response=await fetch("/api/session",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token})});
      form.reset();
      if(response.ok) setReady(true); else setError("令牌无效、权限不足、过期或服务不可用。");
    } catch { form.reset(); setError("无法连接服务，请重试。"); }
  }
  if(checking) return <main><p role="status">正在检查访问权限…</p></main>;
  if(ready) return <><Console/><button className="button" onClick={async()=>{await fetch("/api/session",{method:"DELETE"});setReady(false);}}>退出本地会话</button></>;
  return <main style={{maxWidth:520,margin:"12vh auto",padding:24}}><h1>本地工作台访问</h1><p>使用本机生成的访问令牌。权限与项目范围由令牌决定。</p><form onSubmit={login}><label htmlFor="access-token">访问令牌</label><input id="access-token" name="token" type="password" autoComplete="off" required/><button type="submit">进入工作台</button></form>{error&&<p role="alert">{error}</p>}<p>默认令牌文件：.local/access/operator.token。页面不显示或保存明文令牌。</p></main>;
}
