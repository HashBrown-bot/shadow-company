import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
const allowed: Record<string, string[]> = {
  GET: ["health", "session", "projects", "contracts/schema", "console/catalog"],
  POST: ["projects", "contracts/validate", "runs"],
};

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const endpoint = (await context.params).path.join("/");
  const runRoute = /^runs\/[0-9a-f-]{36}(\/(history|manifest|report|compare|console|events|timeline|checks|findings)(\/[0-9a-f-]{36})?)?$/.test(endpoint);
  const replayRoute = /^runs\/[0-9a-f-]{36}\/(replay|cancel)$/.test(endpoint);
  const projectRead = /^projects\/[0-9a-f-]{36}(\/(contracts|runs|preflight|contract\/[A-Za-z0-9_.-]{1,128}))?$/.test(endpoint);
  const projectWrite = /^projects\/[0-9a-f-]{36}\/(contract|preflight)$/.test(endpoint);
  if (!allowed[request.method]?.includes(endpoint) && !(request.method === "GET" && (runRoute || projectRead)) && !(request.method === "POST" && (replayRoute || projectWrite && endpoint.endsWith("/preflight"))) && !(request.method === "PUT" && projectWrite && endpoint.endsWith("/contract"))) {
    return NextResponse.json({ error: { message: "接口不在本阶段范围内" } }, { status: 404 });
  }
  // Next may normalize nextUrl's host; use the actual HTTP Host with a local allowlist.
  const host = request.headers.get("host");
  const origin = request.headers.get("origin");
  const localHosts = new Set(["127.0.0.1:3000", "localhost:3000", "[::1]:3000"]);
  if (!host || !localHosts.has(host) || (request.method !== "GET" && origin && origin !== `http://${host}`)) {
    return NextResponse.json({ error: { message: "不允许跨来源写入" } }, { status: 403 });
  }
  try {
    const apiOrigin = new URL("http://127.0.0.1:8000");
    const token = request.cookies.get("sim_session")?.value;
    if (endpoint !== "health" && !token) return NextResponse.json({error:{code:"unauthorized",message:"需要登录本地会话"}},{status:401});
    const body = request.method !== "GET" ? await request.text() : undefined;
    if (body && Buffer.byteLength(body) > 160 * 1024) {
      return NextResponse.json({ error: { message: "配置过大" } }, { status: 413 });
    }
    const target = new URL(`/api/${endpoint}`, apiOrigin);
    for (const [key, value] of request.nextUrl.searchParams) {
      if (!["project_id", "other_run_id", "format", "limit", "offset", "after", "contract_version", "lane"].includes(key)) return NextResponse.json({ error: { message: "查询参数不受支持" } }, { status: 422 });
      target.searchParams.set(key, value);
    }
    const response = await fetch(target, {
      method: request.method,
      headers: { "Content-Type": "application/json", ...(token ? {Authorization:`Bearer ${token}`} : {}) },
      body,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(30000),
    });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") || "application/json", "Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'" },
    });
  } catch {
    return NextResponse.json({ error: { message: "无法连接 API，请检查本地服务和 API_BASE_URL。" } }, { status: 503 });
  }
}

export { proxy as GET, proxy as POST, proxy as PUT };
