import { useEffect, useRef, useState } from "react";
import { admin, ChatMessage, ChatPart, getPlaygroundKey, money, setPlaygroundKey, streamChat, UserRow } from "../api";
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
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [system, setSystem] = useState("");
  const [input, setInput] = useState("");
  const [image, setImage] = useState("");
  const [history, setHistory] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [balance, setBalance] = useState<number | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [newKeyUser, setNewKeyUser] = useState(0);
  const abort = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const file = useRef<HTMLInputElement>(null);

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
    fetch("/v1/models", { headers: { Authorization: `Bearer ${key}` } })
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d?.error?.message ?? `HTTP ${r.status}`);
        const ids = (d.data as { id: string }[]).map((m) => m.id);
        setModels(ids);
        setModel((m) => (ids.includes(m) ? m : ids[0] ?? ""));
        setError("");
        void refreshBalance(key);
      })
      .catch((e: Error) => {
        setModels([]);
        setError(e.message);
      });
  }, [key]);

  useEffect(() => {
    // Braces matter: newer Chrome returns a Promise from scrollIntoView, and React would call a returned value as cleanup.
    end.current?.scrollIntoView({ block: "end" });
  }, [history]);

  async function createKey() {
    try {
      const r = await admin<{ key: string }>("POST", "/keys", { user_id: newKeyUser, label: "playground" });
      setKey(r.key);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function pickImage(f: File | undefined) {
    if (!f) return;
    if (f.size > MAX_IMAGE) return setError("That image is larger than 5 MB.");
    const rd = new FileReader();
    rd.onload = () => setImage(String(rd.result));
    rd.readAsDataURL(f);
  }

  async function send() {
    if (!input.trim() || busy) return;
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
      patchLast((m) => ({ ...m, meta: `${model} · ${secs}s${stats ? ` · ${stats.prompt_tokens.toLocaleString()} in / ${stats.completion_tokens.toLocaleString()} out tokens` : ""}` }));
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
            Chat through <code>/v1/chat/completions</code> exactly as an API client would, using a proxy key. Requests here are billed to that key's user.
          </p>
        </div>
        {balance !== null && <span className="pill">{money(balance)} credits left</span>}
      </div>

      {!key && (
        <section className="card">
          <h2>Pick a key to chat with</h2>
          <p className="muted">Keys are stored hashed, so an existing key can't be looked up. Paste one, or create a new one for this browser.</p>
          <div className="grid">
            <Field label="Paste an existing proxy key">
              <input type="password" placeholder="sk-proxy-…" autoComplete="off" onChange={(e) => e.target.value.startsWith("sk-proxy-") && e.target.value.length > 20 && setKey(e.target.value.trim())} />
            </Field>
            {users.length > 0 ? (
              <Field label="Or create a playground key for">
                <div className="row nowrap">
                  <select value={newKeyUser} onChange={(e) => setNewKeyUser(Number(e.target.value))}>
                    {users.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name} ({money(u.credits_usd)} left)
                      </option>
                    ))}
                  </select>
                  <button className="primary" onClick={() => void createKey()}>
                    Create key
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
        <section className="card chat">
          <div className="chat-bar">
            <Field label="Model">
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {models.length === 0 && <option value="">No models available</option>}
                {models.map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </Field>
            <Field label="System message (optional)">
              <input value={system} onChange={(e) => setSystem(e.target.value)} placeholder="e.g. Answer in one sentence." />
            </Field>
            <div className="row nowrap chat-bar-actions">
              <button className="ghost small" onClick={() => setHistory([])} disabled={busy || history.length === 0}>
                Clear chat
              </button>
              <button className="ghost small" onClick={() => { setKey(""); setHistory([]); }}>
                Change key
              </button>
            </div>
          </div>

          <div className="chat-log" aria-live="polite">
            {history.length === 0 && (
              <Empty>{models.length ? "Send a message to start." : <>No models are available to this key. <button className="link" onClick={() => go("providers")}>Enable a provider</button>.</>}</Empty>
            )}
            {history.map((m, i) => (
              <div key={i} className={`bubble ${m.role}`}>
                {m.image && <img src={m.image} alt="Attached" />}
                <div className="bubble-text">{m.content || (busy && i === history.length - 1 ? <span className="typing">●●●</span> : "")}</div>
                {m.meta && <div className="bubble-meta">{m.meta}</div>}
              </div>
            ))}
            <div ref={end} />
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
            <button type="button" className="ghost icon" title="Attach an image (Claude and Codex providers)" aria-label="Attach an image" onClick={() => file.current?.click()} disabled={!model}>
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
              disabled={!model}
            />
            {busy ? (
              <button type="button" className="danger" onClick={() => abort.current?.abort()}>
                Stop
              </button>
            ) : (
              <button type="submit" className="primary" disabled={!model || !input.trim()}>
                Send
              </button>
            )}
          </form>
        </section>
      )}
    </>
  );
}
