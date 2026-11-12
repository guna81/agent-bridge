import { useEffect, useRef, useState } from "react";
import { admin, ChatMessage, ChatPart, getPlaygroundKey, money, setPlaygroundKey, streamChat, UserRow, Provider } from "../api";
import type { Tab } from "../App";
import { Empty, ErrorNote, Field } from "../components/ui";

interface Msg {
  role: "user" | "assistant";
  content: string;
  image?: string; // data: URL
  meta?: string;
}

const MAX_IMAGE = 5 * 1024 * 1024;

export default function Playground({ go }: { go: (t: Tab) => void }) {
  const [key, setKey] = useState(getPlaygroundKey);
  const [keyDraft, setKeyDraft] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [creatingKey, setCreatingKey] = useState(false);
  const [model, setModel] = useState(() => { try { return localStorage.getItem("proxy.playgroundModel") ?? ""; } catch { return ""; } });
  const [system, setSystem] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [outputTokens, setOutputTokens] = useState("512");
  const [estimate, setEstimate] = useState("");
  const [input, setInput] = useState("");
  const [image, setImage] = useState("");
  const [history, setHistory] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [balance, setBalance] = useState<number | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [newKeyUser, setNewKeyUser] = useState(0);
  const abort = useRef<AbortController | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => { admin<Provider[]>("GET", "/providers").then(setProviders).catch(() => {}); }, []);
  useEffect(() => { if (model) { try { localStorage.setItem("proxy.playgroundModel", model); } catch { /* storage unavailable */ } } }, [model]);

  const refreshBalance = (k: string) =>
    fetch("/v1/me", { headers: { Authorization: `Bearer ${k}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setBalance(d ? d.credits_usd : null))
      .catch(() => setBalance(null));

  useEffect(() => {
    setPlaygroundKey(key);
    if (!key) {
      setModels([]);
      setBalance(null);
      admin<UserRow[]>("GET", "/users")
        .then((u) => {
          setUsers(u);
          setNewKeyUser((id) => id || u[0]?.id || 0);
        })
        .catch(() => {});
      return;
    }
    let active = true;
    setModelsLoading(true);
    setModels([]);
    setError("");
    fetch("/v1/models", { headers: { Authorization: `Bearer ${key}` } })
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d?.error?.message ?? `HTTP ${r.status}`);
        if (!active) return;
        const ids = (d.data as { id: string }[]).map((m) => m.id);
        setModels(ids);
        setModel((m) => (ids.includes(m) ? m : ids[0] ?? ""));
        setError("");
        void refreshBalance(key);
      })
      .catch((e: Error) => {
        if (active) { setModels([]); setError(e.message); }
      })
      .finally(() => { if (active) setModelsLoading(false); });
    return () => { active = false; };
  }, [key]);

  useEffect(() => {
    if (stickToBottom.current && log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [history]);

  async function createKey() {
    setCreatingKey(true);
    setError("");
    try {
      const r = await admin<{ key: string }>("POST", "/keys", { user_id: newKeyUser, label: "playground" });
      setKey(r.key);
    } catch (e) {
      setError((e as Error).message);
    } finally { setCreatingKey(false); }
  }

  function pickImage(f: File | undefined) {
    if (!f) return;
    if (f.size > MAX_IMAGE) return setError("That image is larger than 5 MB.");
    const rd = new FileReader();
    rd.onload = () => setImage(String(rd.result));
    rd.readAsDataURL(f);
  }

  async function estimateCost() {
    try {
      const text = [system, ...history.map((m) => m.content), input].join("\n");
      const inputTokens = Math.ceil(text.length / 4);
      const output = Number(outputTokens);
      if (!Number.isInteger(output) || output < 0 || output > 10000000) throw new Error("Enter an output token count between 0 and 10,000,000.");
      const q = new URLSearchParams({ model, input_tokens: String(inputTokens), output_tokens: String(output) });
      const r = await fetch(`/v1/estimate?${q}`, { headers: { Authorization: `Bearer ${key}` } });
      const d = await r.json();
      if (!r.ok) throw new Error(d?.error?.message ?? `HTTP ${r.status}`);
      setEstimate(`${money(d.cost_usd)} for ~${inputTokens} input / ${output} output tokens, using ${d.pricing_model} ($${d.input_rate} / $${d.output_rate} per million; ${d.explicit_rate ? "configured" : "fallback rate"}). Image tokens, CLI prompt overhead, and actual output are not included.`);
    } catch (e) { setError((e as Error).message); }
  }

  async function send() {
    if (!input.trim() || busy || !model || !models.includes(model)) return;
    stickToBottom.current = true;
    if (history.some((m) => m.image) && providers.find((p) => p.name === model.split("/")[0])?.backend !== "direct") { setError("Earlier-turn images require a direct API provider. Clear the chat or choose a direct provider."); return; }
    const mine: Msg = { role: "user", content: input, image: image || undefined };
    const next = [...history, mine];
    setHistory([...next, { role: "assistant", content: "" }]);
    setInput("");
    setImage("");
    setBusy(true);
    setError("");
    abort.current = new AbortController();
    const t0 = performance.now();
    const wire: ChatMessage[] = [
      ...(system ? [{ role: "system", content: system }] : []),
      ...next.map((m) => ({
        role: m.role,
        content: m.image ? ([{ type: "text", text: m.content }, { type: "image_url", image_url: { url: m.image } }] as ChatPart[]) : m.content,
      })),
    ];
    const patchLast = (f: (m: Msg) => Msg) => setHistory((h) => h.map((m, i) => (i === h.length - 1 ? f(m) : m)));
    try {
      const stats = await streamChat(key, model, wire, (d) => patchLast((m) => ({ ...m, content: m.content + d })), abort.current.signal);
      const secs = ((performance.now() - t0) / 1000).toFixed(1);
      patchLast((m) => ({ ...m, meta: `${stats?.model || model}${stats?.model && stats.model !== model ? ` (requested ${model})` : ""} · ${secs}s${stats ? ` · ${stats.prompt_tokens.toLocaleString()} in / ${stats.completion_tokens.toLocaleString()} out tokens` : ""}${stats?.ignored ? ` · ignored: ${stats.ignored}` : ""}` }));
    } catch (e) {
      if ((e as Error).name === "AbortError") patchLast((m) => ({ ...m, meta: "stopped" }));
      else {
        setError((e as Error).message);
        setHistory((h) => (h[h.length - 1]?.content ? h : h.slice(0, -1)));
      }
    } finally {
      setBusy(false);
      void refreshBalance(key);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Playground</h1>
          <p className="muted">
            Test a model through your API gateway. Requests use the selected API key and are billed to its user.
          </p>
        </div>
        {balance !== null && <span className="pill">{money(balance)} credits left</span>}
      </div>

      {!key && (
        <section className="card playground-setup">
          <h2>Connect an API key</h2>
          <p className="muted">Keys are stored hashed, so an existing key can't be looked up. Paste one, or create a new one for this browser.</p>
          <div className="grid">
            <form onSubmit={(e) => { e.preventDefault(); setKey(keyDraft.trim()); }}>
              <Field label="Paste an existing API key">
                <input type="password" placeholder="sk-proxy-…" autoComplete="off" value={keyDraft} onChange={(e) => setKeyDraft(e.target.value)} />
              </Field>
              <button className="primary" type="submit" disabled={!keyDraft.trim()}>Use key</button>
            </form>
            {users.length > 0 ? (
              <Field label="Or create a key for">
                <div className="row nowrap">
                  <select value={newKeyUser} onChange={(e) => setNewKeyUser(Number(e.target.value))}>
                    {users.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name} ({money(u.credits_usd)} left)
                      </option>
                    ))}
                  </select>
                  <button className="primary" disabled={creatingKey || !newKeyUser} onClick={() => void createKey()}>
                    {creatingKey ? "Creating…" : "Create key"}
                  </button>
                </div>
              </Field>
            ) : (
              <Empty>
                No users yet. <button className="link" onClick={() => go("keys")}>Add a user</button> first.
              </Empty>
            )}
          </div>
          <ErrorNote message={error} />
        </section>
      )}

      {key && (
        <section className="card chat" aria-label="Playground chat">
          <div className="chat-bar">
            <Field label="Model">
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {models.length === 0 && <option value="">{modelsLoading ? "Loading models…" : "No models available"}</option>}
                {models.map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </Field>

            <div className="row nowrap chat-bar-actions">
              <button className="ghost small" onClick={() => setHistory([])} disabled={busy || history.length === 0}>
                Clear chat
              </button>
              <button className="ghost small" disabled={busy} onClick={() => { setKey(""); setKeyDraft(""); setHistory([]); setEstimate(""); setError(""); setImage(""); }}>
                Change key
              </button>
            </div>
          </div>

          <details className="playground-options">
            <summary>Chat options</summary>
            <div className="playground-options-body">
              <Field label="System message (optional)">
                <input value={system} onChange={(e) => setSystem(e.target.value)} placeholder="e.g. Answer in one sentence." />
              </Field>
              <div className="estimate-controls"><Field label="Estimated output tokens"><input type="number" min="0" max="10000000" value={outputTokens} onChange={(e) => { setOutputTokens(e.target.value); setEstimate(""); }} /></Field><button type="button" className="ghost small" disabled={!model || modelsLoading} onClick={() => void estimateCost()}>Estimate cost</button></div>
              {estimate && <p className="muted small" role="status">{estimate}</p>}
              <p className="muted small">The estimate is informational. CLI providers may ignore output token limits; earlier-turn images require a direct API provider.</p>
            </div>
          </details>

          <div ref={log} className="chat-log" role="log" aria-label="Conversation" aria-live="polite" onScroll={(e) => { const el = e.currentTarget; stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100; }}>
            {history.length === 0 && (
              <Empty>{modelsLoading ? "Loading available models…" : models.length ? "Start a conversation by sending a message below." : error ? "Unable to load models. Check the error below or change your key." : <>No models are available to this key. <button className="link" onClick={() => go("providers")}>Enable a provider</button>.</>}</Empty>
            )}
            {history.map((m, i) => (
              <div key={i} className={`bubble ${m.role}`}>
                <div className="bubble-role">{m.role === "user" ? "You" : "Assistant"}</div>
                {m.image && <img src={m.image} alt="Attached" />}
                <div className="bubble-text">{m.content || (busy && i === history.length - 1 ? <span className="typing">●●●</span> : "")}</div>
                {m.meta && <div className="bubble-meta">{m.meta}</div>}
              </div>
            ))}
          </div>
          <ErrorNote message={error} />

          {image && (
            <div className="attach">
              <img src={image} alt="To be sent" />
              <button className="ghost small" onClick={() => setImage("")}>
                Remove image
              </button>
            </div>
          )}
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <input ref={file} type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden onChange={(e) => { pickImage(e.target.files?.[0]); e.target.value = ""; }} />
            <button type="button" className="ghost icon" title="Attach an image (Claude and Codex providers)" aria-label="Attach an image" onClick={() => file.current?.click()} disabled={!model || modelsLoading || busy}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 19V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2zM8.5 13.5l2.5 3 3.5-4.5 4.5 6H5l3.5-4.5z" /></svg>
            </button>
            <textarea
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
              placeholder={model ? "Message (Enter to send, Shift+Enter for a new line)" : "No model selected"}
              aria-label="Message"
              disabled={!model || modelsLoading}
            />
            {busy ? (
              <button type="button" className="danger" onClick={() => abort.current?.abort()}>
                Stop
              </button>
            ) : (
              <button type="submit" className="primary" disabled={!model || modelsLoading || !input.trim()}>
                Send
              </button>
            )}
          </form>
          <p className="composer-hint">Enter to send · Shift + Enter for a new line</p>
        </section>
      )}
    </>
  );
}
