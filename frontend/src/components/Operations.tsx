import { useCallback, useEffect, useState } from "react";
import { admin, ago, fullTime, KeyRow, LedgerRow, money, num, UserRow } from "../api";
import { Confirm, Empty, ErrorNote, Field, Pill } from "./ui";

interface Reservation { request_id: string; user_id: number; key_id: number | null; amount_usd: number; created_at: string }

export default function Operations({ users, keys, onChanged }: { users: UserRow[]; keys: KeyRow[]; onChanged: () => void }) {
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [release, setRelease] = useState<Reservation | null>(null);
  const [error, setError] = useState("");
  const [user, setUser] = useState("");
  const [key, setKey] = useState("");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [rows, setRows] = useState<LedgerRow[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [applied, setApplied] = useState("");
  const loadReservations = useCallback(async () => {
    try { setReservations(await admin<Reservation[]>("GET", "/reservations")); }
    catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { void loadReservations(); }, [loadReservations]);
  const params = () => {
    const p = new URLSearchParams({ limit: "100" });
    if (user) p.set("user_id", user);
    if (key) p.set("key_id", key);
    if (provider.trim()) p.set("provider", provider.trim());
    if (model.trim()) p.set("model", model.trim());
    if (start) p.set("start", `${start}T00:00:00Z`);
    if (end) { const d = new Date(`${end}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + 1); p.set("end", d.toISOString()); }
    return p;
  };
  async function search(append = false) {
    setLoading(true); setError("");
    try {
      const p = append ? new URLSearchParams(applied) : params();
      if (append && rows.length) p.set("before_id", String(rows[rows.length - 1].id));
      const result = await admin<LedgerRow[]>("GET", `/ledger?${p}`);
      if (!append) setApplied(p.toString());
      setRows((old) => append ? [...old, ...result] : result);
      setMore(result.length === 100);
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }
  useEffect(() => { void search(); }, []); // Load initial unfiltered page.
  function exportCsv() {
    const columns: (keyof LedgerRow)[] = ["id", "request_id", "created_at", "user_id", "key_id", "provider", "model", "input_tokens", "output_tokens", "cost_usd", "estimated", "status", "duration_ms", "error_code", "pricing_model", "input_rate", "output_rate"];
    // Prefix formula-like cells so spreadsheet applications treat untrusted values as text.
    const cell = (value: unknown) => { const s = String(value ?? ""); return `"${(/^[\s]*[=+@\-]/.test(s) ? "'" + s : s).replace(/"/g, '""')}"`; };
    const csv = [columns.join(","), ...rows.map((r) => columns.map((c) => cell(r[c])).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a"); a.href = url; a.download = "gateway-usage.csv"; a.click(); URL.revokeObjectURL(url);
  }
  const billed = rows.filter((r) => r.user_id !== null);
  return <>
    <details className="card">
      <summary><strong>Advanced: outstanding reservations</strong></summary>
      <div className="card-head"><h2>Outstanding reservations</h2><button className="ghost small" onClick={() => void loadReservations()}>Refresh</button></div>
      <p className="muted small">Credits held by running requests and requests interrupted by a shutdown. The gateway cannot determine whether a reservation is orphaned across instances.</p>
      {reservations.length === 0 ? <Empty>No outstanding reservations.</Empty> : <div className="table-wrap"><table><thead><tr><th>Request</th><th>User / key</th><th>Held</th><th>Age</th><th /></tr></thead><tbody>{reservations.map((r) => <tr key={r.request_id}>
        <td><code>{r.request_id}</code></td><td>{users.find((u) => u.id === r.user_id)?.name ?? `#${r.user_id}`} / {keys.find((k) => k.id === r.key_id)?.prefix ?? (r.key_id ? `#${r.key_id}` : "—")}</td><td>{money(r.amount_usd)}</td><td title={fullTime(r.created_at)}>{ago(r.created_at)}</td><td><button className="ghost small" onClick={() => setRelease(r)}>Review release</button></td>
      </tr>)}</tbody></table></div>}
    </details>
    <section className="card">
      <div className="card-head"><h2>Usage explorer</h2><button className="ghost small" onClick={exportCsv} disabled={!rows.length}>Export loaded rows CSV</button></div>
      <form onSubmit={(e) => { e.preventDefault(); void search(); }}><div className="grid">
        <Field label="User"><select value={user} onChange={(e) => setUser(e.target.value)}><option value="">All users</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></Field>
        <Field label="Key"><select value={key} onChange={(e) => setKey(e.target.value)}><option value="">All keys</option>{keys.map((k) => <option key={k.id} value={k.id}>{k.user} · {k.prefix} {k.label}</option>)}</select></Field>
        <Field label="Provider (exact)"><input value={provider} onChange={(e) => setProvider(e.target.value)} /></Field>
        <Field label="Model (exact)"><input value={model} onChange={(e) => setModel(e.target.value)} /></Field>
        <Field label="From (UTC)"><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="Through (UTC)"><input type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} /></Field>
      </div><button className="primary" disabled={loading}>Apply filters</button></form>
      <p className="muted small">Loaded billed rows: {billed.length} · estimated {money(billed.filter((r) => r.estimated).reduce((a, r) => a + r.cost_usd, 0))} · reported {money(billed.filter((r) => !r.estimated).reduce((a, r) => a + r.cost_usd, 0))}. Totals and export cover loaded rows only; admin tests are not billed.</p>
      {rows.length === 0 ? <Empty>No requests found.</Empty> : <div className="table-wrap"><table><thead><tr><th>Time / request ID</th><th>User / key</th><th>Model</th><th>Tokens in / out</th><th>Cost</th><th>Status / duration</th></tr></thead><tbody>{rows.map((r) => <tr key={r.id}>
        <td>{fullTime(r.created_at)}<br /><code>{r.request_id}</code></td><td>{r.user_id === null ? "Admin test" : users.find((u) => u.id === r.user_id)?.name ?? `#${r.user_id}`} / {keys.find((k) => k.id === r.key_id)?.prefix ?? (r.key_id ? `#${r.key_id}` : "—")}</td><td>{r.provider}/{r.model}</td><td>{num(r.input_tokens)} / {num(r.output_tokens)}</td><td>{money(r.cost_usd)} {r.estimated ? "est." : "reported"}{r.estimated && r.input_rate !== null && <div className="muted small">{r.pricing_model}: ${r.input_rate} / ${r.output_rate} per million in / out</div>}{r.user_id === null ? " (test)" : ""}</td><td><Pill tone={r.status === "ok" ? "ok" : "bad"}>{r.status}</Pill> {r.error_code && <span>{r.error_code}</span>} {r.duration_ms !== null && <span>{(r.duration_ms / 1000).toFixed(2)}s</span>}</td>
      </tr>)}</tbody></table></div>}
      {more && <button className="ghost" disabled={loading} onClick={() => void search(true)}>Load more</button>}
    </section>
    <ErrorNote message={error} />
    {release && <Confirm title="Release reservation?" body={<>Only release <code>{release.request_id}</code> after verifying that the request has stopped on every instance and reconciling upstream charges. Releasing an active reservation can allow overspending. This returns {money(release.amount_usd)} to available credits.</>} action="Release reservation" onCancel={() => setRelease(null)} onConfirm={async () => { try { await admin("DELETE", `/reservations/${encodeURIComponent(release.request_id)}`); setRelease(null); await loadReservations(); onChanged(); } catch (e) { setError((e as Error).message); setRelease(null); } }} />}
  </>;
}
