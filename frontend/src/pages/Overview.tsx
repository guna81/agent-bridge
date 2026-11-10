import { useCallback, useEffect, useState } from "react";
import { admin, AdminSettings, ago, compact, DayUsage, fullTime, LedgerRow, money, num, Provider, Status, UserRow } from "../api";
import type { Tab } from "../App";
import UsageChart from "../components/UsageChart";
import { Empty, ErrorNote, Pill, Stat } from "../components/ui";

const RANGES = [7, 14, 30];

export default function Overview({ settings, go }: { settings: AdminSettings; go: (t: Tab) => void }) {
  const [range, setRange] = useState(14);
  const [days, setDays] = useState<DayUsage[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [status, setStatus] = useState<Record<string, Status>>({});
  const [ledger, setLedger] = useState<LedgerRow[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [d, u, p, l] = await Promise.all([
        admin<DayUsage[]>("GET", `/usage/daily?days=${range}`),
        admin<UserRow[]>("GET", "/users"),
        admin<Provider[]>("GET", "/providers"),
        admin<LedgerRow[]>("GET", "/ledger?limit=8"),
      ]);
      setDays(d);
      setUsers(u);
      setProviders(p);
      setLedger(l);
      setError("");
      for (const x of p.filter((x) => x.enabled))
        admin<Status>("GET", `/providers/${x.name}/status`)
          .then((s) => setStatus((m) => ({ ...m, [x.name]: s })))
          .catch(() => {});
    } catch (e) {
      setError((e as Error).message);
    }
  }, [range]);
  useEffect(() => void load(), [load]);

  const today = days[days.length - 1];
  const period = days.reduce((a, d) => ({ cost: a.cost + d.cost_usd, req: a.req + d.requests, tok: a.tok + d.input_tokens + d.output_tokens }), { cost: 0, req: 0, tok: 0 });
  const credits = users.reduce((a, u) => a + u.credits_usd, 0);
  const enabled = providers.filter((p) => p.enabled);
  const userName = (id: number | null) => (id === null ? "admin test" : users.find((u) => u.id === id)?.name ?? `#${id}`);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="muted">Spend, traffic and provider health at a glance.</p>
        </div>
        <button className="ghost" onClick={() => void load()}>
          Refresh
        </button>
      </div>
      <ErrorNote message={error} />

      <div className="stats">
        <Stat label="Spent today" value={money(today?.cost_usd ?? 0)} sub={`${num(today?.requests ?? 0)} request${today?.requests === 1 ? "" : "s"}`} />
        <Stat label={`Spent, last ${range} days`} value={money(period.cost)} sub={`${num(period.req)} requests · ${compact(period.tok)} tokens`} />
        <Stat label="Credits remaining" value={money(credits)} sub={`across ${users.length} user${users.length === 1 ? "" : "s"}`} />
        <Stat label="Running now" value={`${settings.queue.running} / ${settings.queue.max_concurrency}`} sub={`${settings.queue.waiting} queued`} />
      </div>

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
          {enabled.length === 0 ? (
            <Empty>
              No provider is enabled yet. <button className="link" onClick={() => go("providers")}>Enable one</button> to start serving requests.
            </Empty>
          ) : (
            <ul className="plain">
              {enabled.map((p) => {
                const s = status[p.name];
                const ok = s?.installed && s.authenticated;
                return (
                  <li key={p.name} className="row spread">
                    <span>
                      <strong>{p.name}</strong> <span className="muted small">{p.backend === "direct" ? "direct API" : p.mode} · {p.default_model}</span>
                    </span>
                    {!s ? <Pill>checking…</Pill> : ok ? <Pill tone="ok">ready</Pill> : <Pill tone="bad" title={s.detail}>{!s.installed ? "not installed" : "not signed in"}</Pill>}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Recent requests</h2>
            <button className="link" onClick={() => go("keys")}>
              All usage →
            </button>
          </div>
          {ledger.length === 0 ? (
            <Empty>Nothing yet. Try the Playground.</Empty>
          ) : (
            <ul className="plain">
              {ledger.map((r) => (
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
