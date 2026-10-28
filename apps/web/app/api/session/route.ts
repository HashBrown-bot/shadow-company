import { NextRequest, NextResponse } from "next/server";

const hosts = new Set(["127.0.0.1:3000", "localhost:3000", "[::1]:3000"]);
function sameOrigin(request: NextRequest) {
  const host = request.headers.get("host");
  return !!host && hosts.has(host) && request.headers.get("origin") === `http://${host}`;
}
export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return NextResponse.json({error:"不允许跨来源登录"},{status:403});
  try {
    const raw = await request.text();
    if (raw.length > 512) return NextResponse.json({error:"令牌格式无效"},{status:422});
    const {token} = JSON.parse(raw);
    if (typeof token !== "string" || !/^sim_[A-Za-z0-9_-]{43}$/.test(token)) return NextResponse.json({error:"令牌格式无效"},{status:422});
    const response = await fetch("http://127.0.0.1:8000/api/session",{headers:{Authorization:`Bearer ${token}`},cache:"no-store",redirect:"error",signal:AbortSignal.timeout(5000)});
    if (!response.ok) return NextResponse.json({error:"令牌无效、过期或 API 不可用"},{status:response.status});
    const result = NextResponse.json({authenticated:true});
    result.cookies.set("sim_session",token,{httpOnly:true,sameSite:"strict",path:"/",maxAge:3600,secure:false});
    result.headers.set("Cache-Control","no-store");
    return result;
  } catch { return NextResponse.json({error:"无法验证令牌，请检查本机 API"},{status:503}); }
}
export async function DELETE(request: NextRequest) {
  if (!sameOrigin(request)) return NextResponse.json({error:"不允许跨来源退出"},{status:403});
  const result = NextResponse.json({authenticated:false});
  result.cookies.delete("sim_session");
  return result;
}
