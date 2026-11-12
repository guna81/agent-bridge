import { useCallback, useEffect, useState } from "react";
import { admin, AdminSettings, ago, compact, DayUsage, fullTime, KeyRow, LedgerRow, LimitWindow, money, num, Provider, Status, StatusBarData, UserRow } from "../api";
import type { Tab } from "../App";
import UsageChart from "../components/UsageChart";
import { Empty, ErrorNote, Pill, Stat } from "../components/ui";

const RANGES = [7, 14, 30];
const AGENTS = [["codex", "Codex"], ["claude", "Claude Code"], ["antigravity", "Antigravity"]] as const;

function UsageWindow({ label, window }: { label: string; window: LimitWindow | null | undefined }) {
  const remaining = window && Number.isFinite(window.left_percent) ? Math.max(0, Math.min(100, window.left_percent)) : null;
  const tone = remaining !== null && (window?.is_exhausted || remaining <= 10) ? "tone-red" : remaining !== null && remaining <= 35 ? "tone-amber" : "tone-green";
  return <div className="overview-usage-window">
    <div className="gauge-header"><span>{label}</span><span className={remaining === null ? "muted" : `gauge-value ${tone}`}>{remaining === null ? "Unavailable" : `${Math.round(remaining)}% left`}</span></div>
    {remaining !== null && <div className="gauge-track" role="progressbar" aria-label={`${label} remaining`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={remaining}><div className={`gauge-fill ${tone}`} style={{ width: `${remaining}%` }} /></div>}
    {window?.reset_str && <span className="muted xsmall">Resets {window.reset_str}</span>}
  </div>;
}

export default function Overview({ settings, go }: { settings: AdminSettings; go: (t: Tab) => void }) {
  const [range, setRange] = useState(14);
  const [days, setDays] = useState<DayUsage[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [alertsLoaded, setAlertsLoaded] = useState(false);
  const [keys, setKeys] = useState<KeyRow[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [status, setStatus] = useState<Record<string, Status>>({});
  const [ledger, setLedger] = useState<LedgerRow[]>([]);
  const [statusBarData, setStatusBarData] = useState<StatusBarData | null>(null);
  const [usageError, setUsageError] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [notificationPermission, setNotificationPermission] = useState(() => typeof Notification === "undefined" ? "unsupported" : Notification.permission);

  const load = useCallback(async () => {
    try {
      const [d, u, p, l, k] = await Promise.all([
        admin<DayUsage[]>("GET", `/usage/daily?days=${range}`),
        admin<UserRow[]>("GET", "/users"),
        admin<Provider[]>("GET", "/providers"),
        admin<LedgerRow[]>("GET", "/ledger?limit=100"),
        admin<KeyRow[]>("GET", "/keys"),
      ]);
      setLoaded(true);
      setDays(d);
      setUsers(u);
      setKeys(k);
      setAlertsLoaded(true);
      setProviders(p);
      setLedger(l);
      setError("");
      for (const x of p.filter((x) => x.enabled))
        admin<Status>("GET", `/providers/${x.name}/status`)
          .then((s) => setStatus((m) => ({ ...m, [x.name]: s })))
          .catch((e) => setStatus((m) => ({ ...m, [x.name]: { installed: false, version: null, authenticated: null, detail: `Unable to check: ${(e as Error).message}` } })));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [range]);
  useEffect(() => void load(), [load]);

  const refreshUsage = useCallback(() => {
    admin<StatusBarData>("GET", "/status-bar")
      .then((data) => { setStatusBarData(data); setUsageError(""); })
      .catch((e) => setUsageError((e as Error).message));
  }, []);

  // Keep subscription usage independent of the gateway overview requests.
  useEffect(() => {
    refreshUsage();
    const t = setInterval(refreshUsage, 4000);
    return () => clearInterval(t);
  }, [refreshUsage]);

  useEffect(() => {
    const t = setInterval(() => void load(), 60000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    if (notificationPermission !== "granted" || !alertsLoaded) return;
    const alerts = [
      ...users.filter((u) => u.credits_usd < 1).map((u) => ({ id: `user-${u.id}`, message: `${u.name} has ${money(u.credits_usd)} in available credits.` })),
      ...keys.filter((k) => !k.revoked && [[k.budget_usd, k.spent_usd], [k.daily_budget_usd, k.daily_spent_usd], [k.monthly_budget_usd, k.monthly_spent_usd]].some(([cap, spent]) => cap !== null && cap > 0 && spent !== null && spent / cap >= 0.8)).map((k) => ({ id: `key-${k.id}`, message: `${k.user}'s key ${k.prefix} has used at least 80% of a budget.` })),
    ];
    try {
      const previous: string[] = JSON.parse(sessionStorage.getItem("proxy.alerts") || "[]");
      for (const alert of alerts) if (!previous.includes(alert.id)) new Notification("Gateway budget alert", { body: alert.message });
      sessionStorage.setItem("proxy.alerts", JSON.stringify(alerts.map((a) => a.id)));
    } catch { /* browser notifications or storage unavailable */ }
  }, [users, keys, notificationPermission, alertsLoaded]);

  const today = days[days.length - 1];
  const period = days.reduce((a, d) => ({ cost: a.cost + d.cost_usd, req: a.req + d.requests, tok: a.tok + d.input_tokens + d.output_tokens }), { cost: 0, req: 0, tok: 0 });
  const credits = users.reduce((a, u) => a + u.credits_usd, 0);
  const enabled = providers.filter((p) => p.enabled);
  const lowCredits = users.filter((u) => u.credits_usd < 1);
  const nearLimit = keys.filter((k) => !k.revoked && [[k.budget_usd, k.spent_usd], [k.daily_budget_usd, k.daily_spent_usd], [k.monthly_budget_usd, k.monthly_spent_usd]].some(([cap, spent]) => cap !== null && cap > 0 && spent !== null && spent / cap >= 0.8));
  const userName = (id: number | null) => (id === null ? "admin test" : users.find((u) => u.id === id)?.name ?? `#${id}`);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="muted">Subscription limits, gateway spend, traffic and provider health at a glance.</p>
        </div>
        <div className="row"><button className="ghost" onClick={() => { void load(); refreshUsage(); }}>Refresh</button>{notificationPermission === "default" && <button className="ghost" onClick={() => void Notification.requestPermission().then(setNotificationPermission)}>Enable browser budget alerts</button>}</div>
      </div>
      <ErrorNote message={error} />

      <div className="stats">
        <Stat label="Gateway spend today" value={loaded ? money(today?.cost_usd ?? 0) : "—"} sub={loaded ? `${num(today?.requests ?? 0)} request${today?.requests === 1 ? "" : "s"}` : "Loading…"} />
        <Stat label={`Gateway spend, last ${range} days`} value={loaded ? money(period.cost) : "—"} sub={loaded ? `${num(period.req)} requests · ${compact(period.tok)} tokens` : "Loading…"} />
        <Stat label="Gateway credits remaining" value={loaded ? money(credits) : "—"} sub={loaded ? `across ${users.length} user${users.length === 1 ? "" : "s"}` : "Loading…"} />
        <Stat label="Running now" value={`${statusBarData?.queue.running ?? settings.queue.running} / ${statusBarData?.queue.max_concurrency ?? settings.queue.max_concurrency}`} sub={`${statusBarData?.queue.waiting ?? settings.queue.waiting} queued`} />
      </div>

      {(lowCredits.length > 0 || nearLimit.length > 0) && <div className="note warn"><strong>Budget attention:</strong> {lowCredits.length > 0 && `${lowCredits.length} user(s) have under $1 in available credits. `}{nearLimit.length > 0 && `${nearLimit.length} key(s) have used at least 80% of a budget.`} <button className="link" onClick={() => go("keys")}>Review API keys and users →</button></div>}

      <section className="card">
        <div className="card-head"><div><h2>Subscription usage</h2><p className="muted small">Remaining capacity for tracked agents. Separate from gateway credits.</p></div><button className="link" onClick={() => go("subscription")}>View all usage →</button></div>
        {usageError && <p className="muted small">Unable to refresh subscription usage{statusBarData ? "; showing the last result" : ""}.</p>}
        {!statusBarData && !usageError && <p className="muted small">Loading subscription usage…</p>}
        {statusBarData && (() => {
          const tracked = AGENTS.filter(([id]) => statusBarData.config.enabled_providers[id]);
          return tracked.length ? <div className="overview-usage-grid">{tracked.map(([id, name]) => {
            const limits = statusBarData.rate_limits?.[id];
            return <div className="overview-usage-agent" key={id}><strong>{name}</strong><UsageWindow label="5-hour" window={limits?.five_hour} /><UsageWindow label="Weekly" window={limits?.weekly} /></div>;
          })}</div> : <p className="muted small">No agents are being tracked. <button className="link" onClick={() => go("statusbar")}>Choose agents in indicator settings →</button></p>;
        })()}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Daily spend by provider</h2>
          <div className="seg" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button key={r} className={r === range ? "active" : ""} onClick={() => setRange(r)}>
                {r} days
              </button>
            ))}
          </div>
        </div>
        {days.length > 0 && <UsageChart days={days} />}
        <p className="muted small">Days are in UTC. Admin test runs are not counted. Where a CLI reports only tokens, cost is estimated from a price table.</p>
      </section>

      <div className="two-col">
        <section className="card">
          <div className="card-head">
            <h2>Providers</h2>
            <button className="link" onClick={() => go("providers")}>
              Manage →
            </button>
          </div>
          <p className="muted small">Recent results use the latest 100 requests, including unbilled tests.</p>
          {enabled.length === 0 ? (
            <Empty>
              No provider is enabled yet. <button className="link" onClick={() => go("providers")}>Enable one</button> to start serving requests.
            </Empty>
          ) : (
            <ul className="plain">
              {enabled.map((p) => {
                const s = status[p.name];
                const ok = s?.installed && s.authenticated;
                const lastOk = ledger.find((r) => r.provider === p.name && r.status === "ok");
                const lastFailure = ledger.find((r) => r.provider === p.name && r.status === "error");
                return (
                  <li key={p.name} className="row spread">
                    <span>
                      <strong>{p.name}</strong> <span className="muted small">{p.backend === "direct" ? "direct API" : p.mode} · {p.default_model}</span><br /><span className="muted small">Last success: {lastOk ? `${ago(lastOk.created_at)}${lastOk.duration_ms !== null ? ` · ${(lastOk.duration_ms / 1000).toFixed(2)}s` : ""}` : "none in recent history"}{lastFailure ? ` · last failure: ${ago(lastFailure.created_at)}${lastFailure.error_code ? ` (${lastFailure.error_code})` : ""}` : ""}</span>
                    </span>
                    {!s ? <Pill>checking…</Pill> : s.detail.startsWith("Unable to check:") ? <Pill tone="warn" title={s.detail}>unable to check</Pill> : ok ? <Pill tone="ok">ready</Pill> : <Pill tone="bad" title={s.detail}>{!s.installed ? "not installed" : "not signed in"}</Pill>}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Recent requests</h2>
            <button className="link" onClick={() => go("requests")}>
              All request usage →
            </button>
          </div>
          {ledger.length === 0 ? (
            <Empty>Nothing yet. Try the Playground.</Empty>
          ) : (
            <ul className="plain">
              {ledger.slice(0, 8).map((r) => (
                <li key={r.id} className="row spread">
                  <span className="clip">
                    <strong>{r.provider}/{r.model}</strong> <span className="muted small">{userName(r.user_id)}</span>
                  </span>
                  <span className="row nowrap">
                    {r.status !== "ok" && <Pill tone="bad">{r.status}</Pill>}
                    <span className="mono">{money(r.cost_usd)}</span>
                    <span className="muted small w-time" title={fullTime(r.created_at)}>{ago(r.created_at)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
