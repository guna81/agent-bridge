export interface Provider {
  name: string;
  kind: string;
  enabled: boolean;
  backend: "cli" | "direct";
  binary_path: string;
  default_model: string;
  models: string[];
  mode: "raw" | "agent";
  auth_mode: "api_key" | "oauth_cli";
  raw_system_prompt: string;
  skip_permissions: boolean;
  use_host_home: boolean;
  max_budget_usd: number | null;
  extra: Record<string, unknown>;
  has_api_key: boolean;
}

export function discoveredModels(provider: Provider): string[] {
  const models = provider.extra?.discovered_models;
  return provider.kind === "codex" && Array.isArray(models) ? models.filter((model): model is string => typeof model === "string") : [];
}

export interface Status {
  installed: boolean;
  version: string | null;
  authenticated: boolean | null;
  detail: string;
}

export interface TestResult {
  ok: boolean;
  text: string;
  usage: { input_tokens: number; output_tokens: number; cost_usd: number | null } | null;
  error: { code: string; message: string } | null;
  duration_ms: number;
  raw_lines: string[];
}

export interface UserRow {
  id: number;
  name: string;
  credits_usd: number;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  spent_usd: number;
}

export interface KeyRow {
  id: number;
  user_id: number;
  user: string;
  label: string;
  prefix: string;
  revoked: boolean;
  created_at: string;
  last_used_at: string | null;
  budget_usd: number | null;
  spent_usd: number;
  daily_budget_usd: number | null;
  monthly_budget_usd: number | null;
  daily_spent_usd: number;
  monthly_spent_usd: number;
  expires_at: string | null;
  allowed_models: string[];
}

export interface LedgerRow {
  id: number;
  request_id: string;
  user_id: number | null; // null = admin test run (not billed)
  key_id: number | null;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  estimated: boolean;
  status: string;
  duration_ms: number | null;
  error_code: string | null;
  pricing_model: string | null;
  input_rate: number | null;
  output_rate: number | null;
  created_at: string;
}

export interface DayUsage {
  date: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  by_provider: Record<string, number>;
}

export interface LimitWindow {
  label: string;
  used_percent: number;
  left_percent: number;
  reset_at: number | null;
  reset_str: string | null;
  is_exhausted: boolean;
  description?: string | null;
}

export interface AntigravityRateLimits {
  five_hour: LimitWindow | null;
  weekly: LimitWindow | null;
  claude_gpt_5h?: LimitWindow | null;
  claude_gpt_weekly?: LimitWindow | null;
  plan_name: string | null;
  tier_id: string | null;
  updated_at?: number | null;
}

export interface CodexRateLimits {
  five_hour: LimitWindow | null;
  weekly: LimitWindow | null;
  updated_at?: number | string | null;
}

export interface ClaudeScopedLimit {
  label: string;
  model_name: string;
  used_percent: number;
  left_percent: number;
  reset_str: string | null;
  is_exhausted: boolean;
}

export interface ClaudeRateLimits {
  updated_at?: number | null;
  is_stale?: boolean;
  refreshing?: boolean;
  refresh_error?: string | null;
  five_hour: LimitWindow | null;
  weekly: LimitWindow | null;
  weekly_scoped: ClaudeScopedLimit | null;
}

export interface AllRateLimits {
  codex?: CodexRateLimits | null;
  claude?: ClaudeRateLimits | null;
  antigravity?: AntigravityRateLimits | null;
}

export interface StatusBarConfig {
  indicator_enabled: boolean;
  enabled_providers: {
    codex: boolean;
    claude: boolean;
    antigravity: boolean;
  };
  pinned_metric: string;
  selected_clis: string[];
  display_mode: "bars" | "compact";
  refresh_interval_seconds: number;
  antigravity_ls_address: string;
  antigravity_csrf_token: string;
  codex_sqlite_path: string;
  claude_json_path: string;
}

export interface StatusBarData {
  online: boolean;
  port: number;
  queue: { running: number; waiting: number; max_concurrency: number };
  providers: Array<Record<string, unknown>>;
  totals: Record<string, unknown>;
  credits_remaining_usd: number;
  rate_limits: AllRateLimits;
  config: StatusBarConfig;
}

export interface AdminSettings {
  single_user_personal_use: boolean;
  queue: { running: number; waiting: number; max_concurrency: number };
  limits: { max_concurrency: number; per_user_concurrency: number; rate_limit_per_minute: number; max_body_bytes: number };
  adapter_kinds: string[];
}

const TOKEN_KEY = "proxy.adminToken";
export const PLAYGROUND_KEY = "proxy.playgroundKey";

function read(k: string): string {
  try {
    return localStorage.getItem(k) ?? "";
  } catch {
    return "";
  }
}
function write(k: string, v: string) {
  try {
    if (v) localStorage.setItem(k, v);
    else localStorage.removeItem(k);
  } catch {
    /* private window: keep working without persistence */
  }
}

export const getToken = () => read(TOKEN_KEY);
export const setToken = (t: string) => write(TOKEN_KEY, t);
export const getPlaygroundKey = () => read(PLAYGROUND_KEY);
export const setPlaygroundKey = (k: string) => write(PLAYGROUND_KEY, k);

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function admin<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/admin${path}`, {
    method,
    headers: { Authorization: `Bearer ${getToken()}`, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, data?.error?.message ?? `HTTP ${r.status}`);
  return data as T;
}

export const money = (n: number) => `$${n.toFixed(n !== 0 && Math.abs(n) < 0.01 ? 5 : 2)}`;
export const num = (n: number) => n.toLocaleString();
export const compact = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n));

/** "3 min ago" style; falls back to a date for anything older than a week. */
export function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 0) return until(iso);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString();
}

export function until(iso: string): string {
  const s = (new Date(iso).getTime() - Date.now()) / 1000;
  if (s <= 0) return "expired";
  if (s < 3600) return `in ${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `in ${Math.round(s / 3600)} h`;
  return `in ${Math.round(s / 86400)} d`;
}

export const fullTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "");

export type ChatPart = { type: "text"; text: string } | { type: "image_url"; image_url: { url: string } };
export interface ChatMessage {
  role: string;
  content: string | ChatPart[];
}
export interface StreamStats {
  prompt_tokens: number;
  completion_tokens: number;
  model?: string;
  ignored?: string;
}

/** Streams /v1/chat/completions (SSE) and calls onDelta for every content chunk. Resolves with token usage if sent. */
export async function streamChat(
  key: string,
  model: string,
  messages: ChatMessage[],
  onDelta: (s: string) => void,
  signal: AbortSignal,
): Promise<StreamStats | null> {
  const r = await fetch("/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages, stream: true, stream_options: { include_usage: true } }),
    signal,
  });
  if (!r.ok || !r.body) {
    const data = await r.json().catch(() => ({}));
    throw new ApiError(r.status, data?.error?.message ?? `HTTP ${r.status}`);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let stats: StreamStats | null = null;
  const selectedModel = r.headers.get("X-Proxy-Model") || model;
  const ignored = r.headers.get("X-Proxy-Ignored-Params") || "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 2);
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") return { ...(stats ?? { prompt_tokens: 0, completion_tokens: 0 }), model: selectedModel, ignored };
      const obj = JSON.parse(payload);
      if (obj.error) throw new ApiError(500, obj.error.message);
      if (obj.usage) stats = obj.usage;
      const c = obj.choices?.[0]?.delta?.content;
      if (c) onDelta(c);
    }
  }
  return { ...(stats ?? { prompt_tokens: 0, completion_tokens: 0 }), model: selectedModel, ignored };
}

export type SkillLink = "linked" | "missing" | "stale" | "conflict";
export interface SkillIssue {
  level: "error" | "warn" | "info";
  message: string;
}
export interface SkillFile {
  kind: "skill";
  name: string;
  path: string;
  text: string;
  linked: Record<string, SkillLink>;
  wrappers: string[];
  files: string[];
  issues: SkillIssue[];
}
export interface WrapperFile {
  kind: "wrapper";
  name: string;
  path: string;
  text: string;
  skill: string | null;
  linked: SkillLink;
  issues: SkillIssue[];
}
export interface InstructionFile {
  kind: "instructions";
  name: "global" | "claude" | "codex" | "agy";
  label: string;
  path: string;
  text: string;
  issues: SkillIssue[];
}
/** applied: block matches the sources; outdated: sources changed; edited: block changed by hand; missing: no block. */
export type InstructionStatus = "applied" | "outdated" | "edited" | "missing";
export interface InstructionTarget {
  id: string;
  label: string;
  path: string;
  status: InstructionStatus;
  own_lines: number;
  /** Instructions folder that wrote the block now in the file, when it says. */
  source?: string | null;
}
export interface InstructionResult {
  path: string;
  status: "added" | "updated" | "unchanged" | "skipped" | "removed";
  detail?: string;
}
export interface SkillsState {
  root: string;
  skills_dir: string;
  wrappers_dir: string;
  user_home?: string;
  exists: boolean;
  instructions: { dir: string; files: InstructionFile[]; targets: InstructionTarget[] };
  targets: { id: string; label: string; dir: string }[];
  agents_dir: string;
  skills: SkillFile[];
  wrappers: WrapperFile[];
}
export interface SkillLinkResult {
  path: string;
  status: "linked" | "relinked" | "removed" | "unchanged" | "skipped";
  detail?: string;
}

export interface Project {
  id: number;
  name: string;
  slug: string;
  repo_path: string;
  base_branch: string;
  captain_provider: string;
  captain_model: string;
  approval_mode: "manual" | "auto";
  allowed_providers: string[];
  agent_roles: Record<string, string>;
  instructions: string;
  max_budget_usd: number | null;
  webhook_url: string;
  webhook_events: string[];
  active_missions: number;
  total_missions: number;
  created_at: string;
  updated_at: string;
}

export interface MissionTask {
  id: number;
  mission_id: string;
  order_index: number;
  title: string;
  description: string;
  provider_name: string;
  model: string;
  rationale: string;
  status: "pending" | "queued" | "running" | "needs_input" | "completed" | "failed" | "cancelled";
  worktree_path: string;
  branch_name: string;
  diff_stat: string;
  output_text: string;
  error: string;
  cost_usd: number;
  duration_ms: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface MissionMessage {
  id: number;
  mission_id: string;
  task_id: number | null;
  sender_type: "user" | "captain" | "agent" | "system";
  sender_name: string;
  channel: string;
  kind: "order" | "plan" | "status" | "question" | "reply" | "result" | "error";
  content: string;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface Mission {
  id: string;
  project_id: number;
  title: string;
  goal: string;
  status: "planning" | "awaiting_approval" | "running" | "needs_input" | "completed" | "failed" | "cancelled";
  captain_provider: string;
  captain_model: string;
  plan_summary: string;
  final_summary: string;
  error: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  tasks?: MissionTask[];
  messages?: MissionMessage[];
}

export interface TaskDiff {
  task_id: number;
  branch_name: string;
  diff_stat: string;
  diff: string;
  exists: boolean;
}

export interface CaptainNotification {
  id: number;
  kind: string;
  project_id: number;
  project_name: string;
  mission_id: string;
  task_id: number | null;
  title: string;
  body: string;
  created_at: string;
}

export interface CaptainSseEvent {
  event: string;
  mission_id: string | null;
  data: Record<string, unknown>;
  ts?: string;
}

/** Subscribes to an authenticated /admin SSE endpoint using fetch + ReadableStream. */
export async function streamAdminEvents(
  path: string,
  onEvent: (ev: CaptainSseEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const token = getToken();
  const r = await fetch(`/admin${path}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
    signal,
  });
  if (!r.ok || !r.body) throw new ApiError(r.status, `SSE HTTP ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 2);
      if (!chunk || chunk.startsWith(":")) continue;
      let eventName = "message";
      let dataStr = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
      }
      if (!dataStr || eventName === "ready") continue;
      try {
        const parsed = JSON.parse(dataStr);
        onEvent(parsed);
      } catch {
        /* ignore malformed SSE frame */
      }
    }
  }
}
