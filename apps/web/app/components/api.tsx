"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type Verdict = "pass" | "fail" | "inconclusive" | "not_applicable";
export type Route = { project?: string; view?: string; run?: string; finding?: string; source?: string; contract?: string };
export type Navigate = (route: Route) => void;
export type PageData<T> = { items: T[]; total: number; limit: number; offset: number };
export type Run = { run_id: string; project_id: string; status: string; verdict: Verdict; put_version: string; contract_version: string; created_at: string; stop_reason: string | null; seed: number; time_mode: string };
export type Project = { id: string; name: string; product_versions: string[]; latest_run: Run | null };
export type Runtime = { seed: number; time_mode: string; max_events: number; max_wall_seconds: number; max_concurrency: number; max_action_retries: number };
export type Config = {
  schema_version: string; product: { id: string; version: string; base_url: string; adapter: string; clock_support: string[]; credentials: { support: string; approver: string }; actions: Record<string, unknown>; observations: Record<string, string>; reset: Record<string, string> };
  environment: { id: string; version: string }; provider: { base_url: string }; runtime: Runtime;
  faults: { id: string; behavior: string; match: { scenario_id: string } }[]; rules: { id: string; version: string }[];
};
export type Preflight = { passed: boolean; checks: Record<string, boolean>; error: string | null; limits: string[]; contract_hash: string; business_verdict: Verdict };
export type Contract = { version: string; content_hash: string; config: Config; preflight?: Preflight | null };
export type Catalog = { example: boolean; template_yaml: string; config: Config; product_versions: string[]; suite_scope: string; scenarios: { id: string; name: string }[]; time_modes: { id: string; name: string; supported: boolean; description: string }[]; control_boundary: unknown; model: { supported: boolean; reason: string } };
export type Finding = { finding_id: string; severity: string; attribution: string; confirmation: string; rule_id: string; object_id: string; reason: string; expected: unknown; actual: unknown; evidence_refs: string[]; failure_chain: unknown };
export type Check = { check_id: string; verdict: Verdict; rule_id: string; rule_version: string; object_id: string; reason: string; evidence_refs: string[] };
export type Gate = { schema_version: string; exit_code: 0 | 1 | 2 | 3; verdict: "pass" | "fail" | "error" | "inconclusive"; reasons: string[] };
export type Gates = { selected: Gate; suite: Gate };
export type Report = {
  example: boolean; verdict: Verdict; status: string; distribution: Partial<Record<Verdict, number>>; evidence_issues: unknown[]; execution_issues: unknown[]; unverified: string[]; limits: string[]; ci_gates: Gates;
  versions: { contract: string; contract_hash: string; rules_hash: string; product: string };
  budget: { limits: Runtime; used: Record<string, unknown>; cost: unknown };
  coverage: { scenario_id: string; selected: boolean; status: string; verdict: Verdict; actions_required: number; actions_observed: number }[];
  replay: { source_run_id?: string; capability: string[] | string; issues?: string[]; input_deviations?: unknown[]; control_boundary?: unknown; manifest_hash?: string; fresh_evidence?: unknown };
};
export type RunView = { run: Run; example: boolean; worker: { state: string; heartbeat: string | null; expires_at: string | null; cancel_requested: boolean }; progress: { total: number; states: Record<string, number> }; selected_scenarios: string[]; budget_used: Record<string, unknown>; report: Report | null; finding_count: number | null; runtime_summary: unknown };
export type Observation = { observation_id: string; source: string; external_id: string; evidence_kind: string; digest: string; captured_at: string; payload: { request?: unknown; response?: { body?: unknown; status?: number }; [key: string]: unknown } };
export type FindingDetail = { finding: Finding; run_verdict: Verdict; rule: { id: string; version: string; params: unknown }; evaluation_rule_version: string; rules_hash: string; missing_evidence_refs: string[]; evidence: PageData<Observation> };
export type Timeline = { id: string; lane: string; wall_time: string; simulation_time: string | null; title: string; object_id: string; event_id: string | null; causation_id: string | null; detail: unknown };
export type Comparison = { repair_verified: boolean; source_verdict: Verdict; target_verdict: Verdict; source_run_id: string; target_run_id: string; source_manifest_hash: string; target_manifest_hash: string; changes: { dimension: string; changed: boolean; source: unknown; target: unknown }[]; confounders: string[]; path_deviations: { object_id: string; expected_path_calls: number; actual_path_calls: number; explanation: string }[]; input_deviations: unknown[]; non_comparable: string[]; fresh_target_calls_and_evidence: boolean; evidence: unknown; integrity_issues: unknown; replay_issues: string[]; ci_gates: Gates; target_ci_gates: Gates };

export class ApiError extends Error {
  constructor(message: string, public status = 0, public requestId = "") { super(message); }
}
export async function api<T>(path: string, body?: unknown, method = body === undefined ? "GET" : "POST", signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/backend/${path}`, { method, cache: "no-store", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), signal: signal || AbortSignal.timeout(35000) });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw new ApiError("无法连接服务。请检查网络与本机 API 后重试；未读取到新的结果。");
  }
  const data = await response.json().catch(() => { throw new ApiError("服务返回了无法解析的响应，请检查本地服务日志。", response.status); });
  if (!response.ok) throw new ApiError([data.error?.message || `请求失败 (${response.status})`, ...(data.error?.details || []).map((d: {path: string; message: string}) => `${d.path}：${d.message}`)].join("\n"), response.status, data.error?.request_id || "");
  return data as T;
}
export const query = (project: string, params: Record<string, string | number> = {}) => new URLSearchParams({ project_id: project, ...Object.fromEntries(Object.entries(params).map(([k,v]) => [k,String(v)])) }).toString();
export const runPath = (project: string, run: string, suffix = "", params: Record<string, string | number> = {}) => `runs/${encodeURIComponent(run)}${suffix}?${query(project, params)}`;
export const terminal = (status: string) => ["completed", "failed", "cancelled"].includes(status);

export function useResource<T>(path: string | null, poll = 0) {
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean }>({ data: null, error: null, loading: true });
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision(n => n + 1), []);
  const current = useRef(path);
  // Never expose a previous project's data while the next request is being dispatched.
  const matches = current.current === path;
  useEffect(() => {
    current.current = path;
    if (!path) { setState({ data: null, error: null, loading: false }); return; }
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    setState({ data: null, error: null, loading: true });
    async function load() {
      try {
        const data = await api<T>(path!, undefined, "GET", AbortSignal.any([controller.signal, AbortSignal.timeout(35000)]));
        if (!controller.signal.aborted) setState({ data, error: null, loading: false });
      } catch (e) {
        if (!controller.signal.aborted) setState({ data: null, error: e instanceof ApiError ? e : new ApiError("读取超时，请重试。"), loading: false });
      } finally { if (poll && !controller.signal.aborted) timer = setTimeout(load, poll); }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [path, revision, poll]);
  return { ...(matches ? state : { data: null, error: null, loading: true }), refresh };
}
