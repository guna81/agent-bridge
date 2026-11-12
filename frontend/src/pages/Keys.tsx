import { useCallback, useEffect, useState } from "react";
import { admin, ago, fullTime, KeyRow, LedgerRow, money, num, setPlaygroundKey, until, UserRow } from "../api";
import type { Tab } from "../App";
import Operations from "../components/Operations";
import { Confirm, CopyButton, Empty, ErrorNote, Field, Modal, Pill } from "../components/ui";

type Dialog =
  | { kind: "user" }
  | { kind: "topup"; user: UserRow }
  | { kind: "key"; user?: UserRow }
  | { kind: "edit"; key: KeyRow }
  | { kind: "revoke"; key: KeyRow }
  | null;

export default function Keys({ go, usageOnly = false }: { go: (t: Tab) => void; usageOnly?: boolean }) {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [keys, setKeys] = useState<KeyRow[]>([]);
  const [ledger, setLedger] = useState<LedgerRow[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [fresh, setFresh] = useState<{ key: string; user: string } | null>(null);
  const [showRevoked, setShowRevoked] = useState(false);
  const [filter, setFilter] = useState<"all" | "billed" | "tests" | "failed">("all");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [u, k, l, p] = await Promise.all([
        admin<UserRow[]>("GET", "/users"),
        admin<KeyRow[]>("GET", "/keys"),
        admin<LedgerRow[]>("GET", "/ledger?limit=100"),
        admin<{ name: string; enabled: boolean; models: string[]; default_model: string }[]>("GET", "/providers"),
      ]);
      setUsers(u);
      setKeys(k);
      setLedger(l);
      setModels(p.filter((x) => x.enabled).flatMap((x) => [...new Set([...x.models, x.default_model].filter(Boolean))].map((m) => `${x.name}/${m}`)));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => void load(), [load]);

  const done = () => {
    setDialog(null);
    void load();
  };
  const userName = (id: number | null) => (id === null ? "admin test" : users.find((u) => u.id === id)?.name ?? `#${id}`);
  const shownKeys = keys.filter((k) => showRevoked || !k.revoked);
  const rows = ledger.filter((r) => (filter === "billed" ? r.user_id !== null : filter === "tests" ? r.user_id === null : filter === "failed" ? r.status !== "ok" : true));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{usageOnly ? "Request usage" : "API keys & users"}</h1>
          <p className="muted">{usageOnly ? "Explore gateway requests, costs, and usage. Subscription limits are shown separately." : "Users hold credits; each API key belongs to a user and can carry its own limits."}</p>
        </div>
        {!usageOnly && <div className="row">
          <button className="ghost" onClick={() => setDialog({ kind: "user" })}>
            Add user
          </button>
          <button className="primary" onClick={() => setDialog({ kind: "key" })} disabled={users.length === 0}>
            New API key
          </button>
        </div>}
      </div>
      <ErrorNote message={error} />

      {!usageOnly && fresh && (
        <div className="note ok keybox">
          <strong>New key for {fresh.user}. Copy it now: it is stored hashed and cannot be shown again.</strong>
          <div className="row">
            <code className="grow">{fresh.key}</code>
            <CopyButton text={fresh.key} />
            <button
              className="ghost small"
              onClick={() => {
                setPlaygroundKey(fresh.key);
                go("playground");
              }}
            >
              Use in Playground
            </button>
            <button className="ghost small" onClick={() => setFresh(null)}>
              Dismiss
            </button>
          </div>
        </div>
      )}

      {!usageOnly && <>
      <section className="card">
        <div className="card-head">
          <h2>Users</h2>
        </div>
        {users.length === 0 ? (
          <Empty>No users yet. Add one, give it credits, then create a key for it.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th className="r">Credits left</th>
                  <th className="r">Spent</th>
                  <th className="r">Requests</th>
                  <th className="r">Tokens in / out</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <strong>{u.name}</strong> <span className="muted small">#{u.id}</span>
                    </td>
                    <td className="r mono">{u.credits_usd <= 0 ? <Pill tone="bad">{money(u.credits_usd)}</Pill> : money(u.credits_usd)}</td>
                    <td className="r mono">{money(u.spent_usd)}</td>
                    <td className="r mono">{num(u.requests)}</td>
                    <td className="r mono">
                      {num(u.input_tokens)} / {num(u.output_tokens)}
                    </td>
                    <td className="r actions">
                      <button className="ghost small" onClick={() => setDialog({ kind: "topup", user: u })}>
                        Add credits
                      </button>
                      <button className="ghost small" onClick={() => setDialog({ kind: "key", user: u })}>
                        New key
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>API keys</h2>
          {keys.some((k) => k.revoked) && (
            <label className="check small">
              <input type="checkbox" checked={showRevoked} onChange={(e) => setShowRevoked(e.target.checked)} /> Show revoked
            </label>
          )}
        </div>
        {shownKeys.length === 0 ? (
          <Empty>No keys yet.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Key</th>
                  <th>User</th>
                  <th>Budget</th>
                  <th>Models</th>
                  <th>Expires</th>
                  <th>Last used</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {shownKeys.map((k) => {
                  const expired = !!k.expires_at && new Date(k.expires_at).getTime() <= Date.now();
                  const pct = k.budget_usd ? Math.min(100, (k.spent_usd / k.budget_usd) * 100) : 0;
                  return (
                    <tr key={k.id} className={k.revoked ? "dim" : ""}>
                      <td>
                        <code>{k.prefix}…</code> {k.label && <span className="muted small">{k.label}</span>} {k.revoked && <Pill tone="bad">revoked</Pill>}
                      </td>
                      <td>{k.user}</td>
                      <td>
                        {k.budget_usd === null ? (
                          <span className="muted small">{money(k.spent_usd)} spent · no cap</span>
                        ) : (
                          <div className="meter" title={`${money(k.spent_usd)} of ${money(k.budget_usd)} used`}>
                            <div className="meter-track">
                              <div className={`meter-fill ${pct >= 100 ? "full" : pct >= 80 ? "high" : ""}`} style={{ width: `${pct}%` }} />
                            </div>
                            <span className="small mono">
                              {money(k.spent_usd)} / {money(k.budget_usd)}
                            </span>
                          </div>
                        )}
                        {(k.daily_budget_usd !== null || k.monthly_budget_usd !== null) && <div className="muted small">{k.daily_budget_usd !== null && `Today ${money(k.daily_spent_usd)} / ${money(k.daily_budget_usd)} `}{k.monthly_budget_usd !== null && `Month ${money(k.monthly_spent_usd)} / ${money(k.monthly_budget_usd)}`}</div>}
                      </td>
                      <td className="small">{k.allowed_models.length ? k.allowed_models.join(", ") : <span className="muted">all</span>}</td>
                      <td className="small" title={fullTime(k.expires_at)}>
                        {!k.expires_at ? <span className="muted">never</span> : expired ? <Pill tone="bad">expired</Pill> : until(k.expires_at)}
                      </td>
                      <td className="small muted" title={fullTime(k.last_used_at)}>
                        {ago(k.last_used_at)}
                      </td>
                      <td className="r actions">
                        {!k.revoked && (
                          <>
                            <button className="ghost small" onClick={() => setDialog({ kind: "edit", key: k })}>
                              Limits
                            </button>
                            <button className="ghost small danger-text" onClick={() => setDialog({ kind: "revoke", key: k })}>
                              Revoke
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      </>}
      {usageOnly && <>
      <section className="card">
        <div className="card-head">
          <h2>Recent requests</h2>
          <div className="row">
            <div className="seg" role="group" aria-label="Filter requests">
              {(["all", "billed", "tests", "failed"] as const).map((f) => (
                <button key={f} className={filter === f ? "active" : ""} onClick={() => setFilter(f)}>
                  {f === "all" ? "All" : f === "billed" ? "Billed" : f === "tests" ? "Admin tests" : "Failed"}
                </button>
              ))}
            </div>
            <button className="ghost small" onClick={() => void load()}>
              Refresh
            </button>
          </div>
        </div>
        {rows.length === 0 ? (
          <Empty>Nothing to show.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Who</th>
                  <th>Model</th>
                  <th className="r">Tokens in / out</th>
                  <th className="r">Cost</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="small" title={ago(r.created_at)}>
                      {fullTime(r.created_at)}
                    </td>
                    <td>{r.user_id === null ? <span className="muted">admin test</span> : userName(r.user_id)}</td>
                    <td>
                      {r.provider}/{r.model}
                    </td>
                    <td className="r mono">
                      {num(r.input_tokens)} / {num(r.output_tokens)}
                    </td>
                    <td className="r mono">
                      {money(r.cost_usd)}
                      {r.estimated && <span className="muted small"> est.</span>}
                      {r.user_id === null && <span className="muted small"> (not billed)</span>}
                    </td>
                    <td>
                      <Pill tone={r.status === "ok" ? "ok" : "bad"}>{r.status}</Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small">Showing the latest {rows.length} of up to 100 loaded. Times are in your local time zone.</p>
      </section>

      <Operations users={users} keys={keys} onChanged={() => void load()} />
      </>}

      {dialog?.kind === "user" && <UserDialog onClose={() => setDialog(null)} onDone={done} />}
      {dialog?.kind === "topup" && <TopUpDialog user={dialog.user} onClose={() => setDialog(null)} onDone={done} />}
      {dialog?.kind === "key" && (
        <KeyDialog
          users={users}
          user={dialog.user}
          models={models}
          onClose={() => setDialog(null)}
          onDone={(key, user) => {
            setFresh({ key, user });
            done();
          }}
        />
      )}
      {dialog?.kind === "edit" && <KeyDialog users={users} editing={dialog.key} models={models} onClose={() => setDialog(null)} onDone={done} />}
      {dialog?.kind === "revoke" && (
        <Confirm
          title="Revoke this key?"
          body={
            <>
              <code>{dialog.key.prefix}…</code> ({dialog.key.user}) will stop working immediately. This cannot be undone.
            </>
          }
          action="Revoke key"
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            await admin("DELETE", `/keys/${dialog.key.id}`).catch((e) => setError((e as Error).message));
            done();
          }}
        />
      )}
    </>
  );
}

function UserDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [credits, setCredits] = useState("5");
  const [err, setErr] = useState("");
  return (
    <Modal title="Add user" onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await admin("POST", "/users", { name: name.trim(), credits_usd: Number(credits) || 0 });
            onDone();
          } catch (x) {
            setErr((x as Error).message);
          }
        }}
      >
        <div className="grid">
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="alice" />
          </Field>
          <Field label="Starting credits (USD)">
            <input type="number" min={0} step="0.5" value={credits} onChange={(e) => setCredits(e.target.value)} />
          </Field>
        </div>
        <ErrorNote message={err} />
        <div className="modal-foot">
          <button type="button" className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={!name.trim()}>
            Add user
          </button>
        </div>
      </form>
    </Modal>
  );
}

function TopUpDialog({ user, onClose, onDone }: { user: UserRow; onClose: () => void; onDone: () => void }) {
  const [amount, setAmount] = useState("5");
  const [err, setErr] = useState("");
  const n = Number(amount);
  return (
    <Modal title={`Add credits for ${user.name}`} onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await admin("POST", `/users/${user.id}/topup`, { amount_usd: n, note: "UI top-up" });
            onDone();
          } catch (x) {
            setErr((x as Error).message);
          }
        }}
      >
        <Field label="Amount (USD)" hint={`Current balance ${money(user.credits_usd)}${n ? `, new balance ${money(user.credits_usd + n)}` : ""}. Use a negative amount to remove credits.`}>
          <input type="number" step="0.5" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <ErrorNote message={err} />
        <div className="modal-foot">
          <button type="button" className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={!n}>
            Add credits
          </button>
        </div>
      </form>
    </Modal>
  );
}

const toLocalInput = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

function KeyDialog({ users, user, editing, models, onClose, onDone }: {
  users: UserRow[]; user?: UserRow; editing?: KeyRow; models: string[]; onClose: () => void; onDone: (key: string, user: string) => void;
}) {
  const [userId, setUserId] = useState(editing?.user_id ?? user?.id ?? users[0]?.id ?? 0);
  const [label, setLabel] = useState(editing?.label ?? "");
  const [budget, setBudget] = useState(editing?.budget_usd?.toString() ?? "");
  const [dailyBudget, setDailyBudget] = useState(editing?.daily_budget_usd?.toString() ?? "");
  const [monthlyBudget, setMonthlyBudget] = useState(editing?.monthly_budget_usd?.toString() ?? "");
  const [expires, setExpires] = useState(toLocalInput(editing?.expires_at ?? null));
  const [allowed, setAllowed] = useState((editing?.allowed_models ?? []).join(", "));
  const [err, setErr] = useState("");

  async function submit() {
    const body = {
      label,
      budget_usd: budget ? Number(budget) : null,
      daily_budget_usd: dailyBudget ? Number(dailyBudget) : null,
      monthly_budget_usd: monthlyBudget ? Number(monthlyBudget) : null,
      expires_at: expires ? new Date(expires).toISOString() : null,
      allowed_models: allowed.split(",").map((s) => s.trim()).filter(Boolean),
    };
    try {
      if (editing) {
        await admin("PATCH", `/keys/${editing.id}`, body);
        onDone("", "");
      } else {
        const r = await admin<{ key: string }>("POST", "/keys", { user_id: userId, ...body });
        onDone(r.key, users.find((u) => u.id === userId)?.name ?? "");
      }
    } catch (x) {
      setErr((x as Error).message);
    }
  }

  return (
    <Modal title={editing ? `Limits for ${editing.prefix}…` : "New API key"} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="grid">
          {!editing && (
            <Field label="User">
              <select value={userId} onChange={(e) => setUserId(Number(e.target.value))}>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({money(u.credits_usd)} left)
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Label" hint="Optional. Where the key is used.">
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="laptop, ci, my-agent" />
          </Field>
          <Field label="Spending budget (USD)" hint="Optional. Requests stop once the budget is exhausted; a running request may exceed it.">
            <input type="number" min={0} step="0.5" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="no cap" />
          </Field>
          <Field label="Daily budget (USD)" hint="Optional. Resets at midnight UTC."><input type="number" min="0.000001" step="any" value={dailyBudget} onChange={(e) => setDailyBudget(e.target.value)} placeholder="no limit" /></Field>
          <Field label="Monthly budget (USD)" hint="Optional. Resets on the first day of each UTC month."><input type="number" min="0.000001" step="any" value={monthlyBudget} onChange={(e) => setMonthlyBudget(e.target.value)} placeholder="no limit" /></Field>
          <Field label="Expires" hint="Optional. Your local time.">
            <input type="datetime-local" value={expires} onChange={(e) => setExpires(e.target.value)} />
          </Field>
        </div>
        <Field label="Allowed models" hint={<>Optional, comma separated. Exact ids or patterns such as <code>claude/*</code>. Blank allows every model.</>}>
          <input value={allowed} onChange={(e) => setAllowed(e.target.value)} placeholder="all models" list="model-ids" />
        </Field>
        <datalist id="model-ids">
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
        <ErrorNote message={err} />
        <div className="modal-foot">
          <button type="button" className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={!editing && !userId}>
            {editing ? "Save limits" : "Create key"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
