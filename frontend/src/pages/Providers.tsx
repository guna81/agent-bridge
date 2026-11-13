import { useCallback, useEffect, useState } from "react";
import { admin, AdminSettings, ApiError, Provider, Status, TestResult } from "../api";
import ConnectModal from "../components/ConnectModal";
import { Confirm, ErrorNote, Field, Modal, Pill } from "../components/ui";

const KIND_NOTES: Record<string, string> = {
  claude: "Claude Code CLI",
  agy: "Google Antigravity CLI",
  codex: "OpenAI Codex CLI",
  gemini: "Google Gemini CLI",
  custom: "Custom CLI",
};

export default function Providers({ settings }: { settings: AdminSettings }) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      setProviders(await admin<Provider[]>("GET", "/providers"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => void load(), [load]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Providers</h1>
          <p className="muted">Configure where API gateway requests are routed as <code>provider/model</code>. Subscription usage tracking is configured separately.</p>
        </div>
        <button className="primary" onClick={() => setAdding(true)}>
          Add custom CLI
        </button>
      </div>

      <details className="note warn">
        <summary>
          <strong>Subscription logins are for personal use only.</strong> Use API keys for anything that serves other people.
        </summary>
        <p>
          Choose a sign-in method for each provider. API keys are available for all providers; CLI login reuse is{" "}
          <strong>{settings.single_user_personal_use ? "available for personal use" : "disabled in this server configuration"}</strong>.
          Anthropic's terms restrict consumer-subscription OAuth tokens to Claude Code and Claude.ai. Check each provider's terms before using a subscription.
          {!settings.single_user_personal_use && <> For a separately configured server, enable <code>PROXY_SINGLE_USER_PERSONAL_USE</code> to allow CLI logins.</>}
        </p>
      </details>
      <ErrorNote message={error} />

      {providers.map((p) => (
        <ProviderCard key={p.name} p={p} settings={settings} onChanged={load} />
      ))}
      {adding && (
        <CustomForm
          kinds={settings.adapter_kinds}
          onClose={() => setAdding(false)}
          onCreated={() => {
            setAdding(false);
            void load();
          }}
        />
      )}
    </>
  );
}

function ProviderCard({ p, settings, onChanged }: { p: Provider; settings: AdminSettings; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [d, setD] = useState<Provider>(p);
  const [modelsText, setModelsText] = useState(p.models.join(", "));
  const [extraText, setExtraText] = useState(JSON.stringify(p.extra ?? {}, null, 2));
  const [pricingText, setPricingText] = useState(() => Object.entries((p.extra?.pricing_rates as Record<string, number[]>) ?? {}).map(([model, rates]) => `${model}, ${rates[0]}, ${rates[1]}`).join("\n"));
  const [fallbackModel, setFallbackModel] = useState(String(p.extra?.fallback_model ?? ""));
  const [apiKey, setApiKey] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [statusError, setStatusError] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [testPrompt, setTestPrompt] = useState("Say hello in five words.");
  const [busy, setBusy] = useState("");
  const [connect, setConnect] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [userId, setUserId] = useState(0);

  const set = <K extends keyof Provider>(k: K, v: Provider[K]) => setD((x) => ({ ...x, [k]: v }));
  const oauthOk = settings.single_user_personal_use;
  const isCli = d.backend === "cli";
  const configuredRateIds = new Set(pricingText.split("\n").map((line) => line.split(",")[0].trim()).filter(Boolean));
  const unconfigured = modelsText.split(",").map((x) => x.trim()).filter((x) => x && !configuredRateIds.has(x));

  const refresh = useCallback(async () => {
    setBusy((b) => b || "status");
    try {
      setStatus(await admin<Status>("GET", `/providers/${p.name}/status?user_id=${userId}`));
      setStatusError("");
    } catch (e) {
      setStatusError((e as Error).message);
      setStatus(null);
    } finally {
      setBusy((b) => (b === "status" ? "" : b));
    }
  }, [p.name, userId]);
  useEffect(() => void refresh(), [refresh]);

  async function save(patch?: Partial<Provider>) {
    setBusy("save");
    try {
      const models = modelsText.split(",").map((s) => s.trim()).filter(Boolean);
      const extra = JSON.parse(extraText || "{}");
      if (!extra || typeof extra !== "object" || Array.isArray(extra)) throw new Error("Extra config must be a JSON object.");
      const rates: Record<string, number[]> = {};
      for (const line of pricingText.split("\n")) {
        if (!line.trim()) continue;
        const parts = line.split(",").map((v) => v.trim());
        if (parts.length !== 3 || !parts[0] || !parts[1] || !parts[2] || parts.slice(1).some((v) => !Number.isFinite(Number(v)) || Number(v) < 0)) throw new Error("Each pricing line must be model, input rate, output rate, with non-negative numbers.");
        if (Object.prototype.hasOwnProperty.call(rates, parts[0])) throw new Error(`Duplicate pricing model: ${parts[0]}`);
        rates[parts[0]] = [Number(parts[1]), Number(parts[2])];
      }
      if (fallbackModel.trim()) extra.fallback_model = fallbackModel.trim();
      else delete extra.fallback_model;
      if (Object.keys(rates).length) extra.pricing_rates = rates;
      else delete extra.pricing_rates;
      const v = { ...d, ...patch };
      await admin("PUT", `/providers/${p.name}`, {
        enabled: v.enabled, backend: v.backend, binary_path: v.binary_path, default_model: v.default_model, models, mode: v.mode,
        auth_mode: v.auth_mode, raw_system_prompt: v.raw_system_prompt, skip_permissions: v.mode === "agent" && v.skip_permissions,
        use_host_home: v.use_host_home, max_budget_usd: v.max_budget_usd || null, extra,
      });
      if (apiKey) {
        await admin("PUT", `/providers/${p.name}/secret`, { api_key: apiKey });
        setApiKey("");
      }
      setMsg({ ok: true, text: "Saved" });
      setTimeout(() => setMsg(null), 2500);
      onChanged();
      void refresh();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof SyntaxError ? `Extra config is not valid JSON: ${e.message}` : (e as ApiError).message });
      if (patch) setD(p); // undo the optimistic toggle
    } finally {
      setBusy("");
    }
  }

  async function runTest() {
    setBusy("test");
    setTest(null);
    try {
      setTest(await admin<TestResult>("POST", `/providers/${p.name}/test`, { prompt: testPrompt }));
    } catch (e) {
      setTest({ ok: false, text: "", usage: null, error: { code: "request", message: (e as Error).message }, duration_ms: 0, raw_lines: [] });
    } finally {
      setBusy("");
    }
  }

  async function setEnabled(enabled: boolean) {
    setBusy("save");
    try {
      await admin("PUT", `/providers/${p.name}`, { enabled });
      onChanged();
    } catch (e) {
      setD((current) => ({ ...current, enabled: p.enabled }));
      setMsg({ ok: false, text: (e as Error).message });
    } finally { setBusy(""); }
  }

  const ready = status?.installed && status.authenticated;
  return (
    <section className={`card provider ${d.enabled ? "" : "off"}`}>
      <div className="provider-head">
        <button className="expander" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <span className={`chev ${open ? "open" : ""}`} aria-hidden="true">›</span>
          <span>
            <strong className="provider-name">{p.name}</strong>
            <span className="muted small"> {KIND_NOTES[p.kind] ?? p.kind}</span>
            <span className="provider-sub muted small">
              {d.backend === "direct" ? "direct API" : `${d.mode} mode`} · default <code>{p.name}/{d.default_model || "?"}</code> · {p.models.length} model{p.models.length === 1 ? "" : "s"}
            </span>
          </span>
        </button>
        <div className="row nowrap">
          {statusError ? (
            <Pill tone="warn" title={statusError}>unable to check</Pill>
          ) : !status ? (
            <Pill>checking…</Pill>
          ) : !status.installed ? (
            <Pill tone="bad" title={status.detail}>not installed</Pill>
          ) : ready ? (
            <Pill tone="ok" title={`${status.version ?? ""} ${status.detail}`}>ready</Pill>
          ) : (
            <Pill tone={status.authenticated === false ? "bad" : "warn"} title={status.detail}>
              {status.authenticated === false ? "not signed in" : "sign-in unknown"}
            </Pill>
          )}
          <label className="switch" title={d.enabled ? "Enabled" : "Disabled"}>
            <input
              type="checkbox"
              checked={d.enabled}
              disabled={busy === "save"}
              aria-label={`${p.name} enabled`}
              onChange={(e) => {
                set("enabled", e.target.checked);
                void setEnabled(e.target.checked);
              }}
            />
            <span />
          </label>
        </div>
      </div>
      {!open && msg && !msg.ok && <ErrorNote message={msg.text} />}

      {open && (
        <div className="provider-body">
          <div className="row status-line">
            {status?.version && <span className="muted small">Version {status.version}</span>}
            {status?.detail && <span className="muted small">· {status.detail}</span>}
            <button className="ghost small" onClick={() => void refresh()} disabled={busy === "status"}>
              Re-check
            </button>
          </div>

          <h3>Connection</h3>
          <div className="grid">
            <Field label="Backend">
              <select value={d.backend} onChange={(e) => setD((x) => ({ ...x, backend: e.target.value as Provider["backend"], ...(e.target.value === "direct" ? { auth_mode: "api_key", use_host_home: false } : {}) }))}>
                <option value="cli">CLI subprocess</option>
                <option value="direct">Direct API (no CLI)</option>
              </select>
            </Field>
            {isCli && (
              <Field label="CLI binary (name or path)">
                <input value={d.binary_path} onChange={(e) => set("binary_path", e.target.value)} />
              </Field>
            )}
            {isCli && (
              <Field label="Sign-in method">
                <select value={d.auth_mode} onChange={(e) => setD((x) => ({ ...x, auth_mode: e.target.value as Provider["auth_mode"], ...(e.target.value === "api_key" ? { use_host_home: false } : {}) }))}>
                  <option value="api_key">Provider API key</option>
                  <option value="oauth_cli" disabled={!oauthOk}>
                    CLI login {oauthOk ? "(personal use)" : "(disabled in server configuration)"}
                  </option>
                </select>
              </Field>
            )}
            {(!isCli || d.auth_mode === "api_key") && (
              <Field label="API key" hint={p.has_api_key ? "A key is stored (encrypted). Leave blank to keep it." : "Not set yet."}>
                <input type="password" value={apiKey} placeholder={p.has_api_key ? "••••••••" : "Paste the provider's API key"} onChange={(e) => setApiKey(e.target.value)} autoComplete="new-password" />
              </Field>
            )}
          </div>
          {isCli && d.auth_mode === "oauth_cli" && !oauthOk && (
            <p className="note warn">This saved CLI login is disabled in the server configuration. Select a provider API key or enable personal CLI logins.</p>
          )}
          {isCli && d.auth_mode === "oauth_cli" && (
            <div className="row" style={{ marginTop: 10 }}>
              <label className="check">
                <input type="checkbox" checked={d.use_host_home} onChange={(e) => set("use_host_home", e.target.checked)} />
                Reuse this machine's existing CLI login
              </label>
              {!d.use_host_home && (
                <>
                  <span className="muted small">or sign in for user #</span>
                  <input type="number" min={0} value={userId} className="narrow" aria-label="User id" onChange={(e) => setUserId(Number(e.target.value))} />
                  <button className="ghost" onClick={() => setConnect(true)}>
                    Connect account…
                  </button>
                </>
              )}
            </div>
          )}

          <h3>Models</h3>
          <div className="grid">
            <Field label="Default model">
              <input value={d.default_model} onChange={(e) => set("default_model", e.target.value)} />
            </Field>
            <Field label="Request budget (USD)" hint="Blank uses the server default. Only the Claude CLI receives a spend limit; other backends may exceed it.">
              <input type="number" step="0.01" min="0" value={d.max_budget_usd ?? ""} placeholder="server default" onChange={(e) => set("max_budget_usd", e.target.value ? Number(e.target.value) : null)} />
            </Field>
          </div>
          <Field label="Models offered" hint={<>Comma separated. Callers request <code>{p.name}/&lt;model&gt;</code>.{["codex", "gemini"].includes(p.kind) && <> <code>default</code> lets the CLI pick its own model.</>}</>}>
            <input value={modelsText} onChange={(e) => setModelsText(e.target.value)} />
          </Field>

          <h3>Behaviour</h3>
          <div className="choice" role="radiogroup" aria-label="Mode">
            {(["raw", "agent"] as const).map((m) => (
              <label key={m} className={d.mode === m ? "active" : ""}>
                <input type="radio" name={`mode-${p.name}`} checked={d.mode === m} onChange={() => set("mode", m)} />
                <strong>{m === "raw" ? "Raw" : "Agent"}</strong>
                <span className="muted small">{m === "raw" ? "Plain assistant replies; the CLI's own tools are switched off where it allows." : "Full coding agent: can run commands and edit files in its working directory."}</span>
              </label>
            ))}
          </div>
          {d.mode === "raw" && (
            <Field label="System prompt for raw mode">
              <textarea value={d.raw_system_prompt} onChange={(e) => set("raw_system_prompt", e.target.value)} />
            </Field>
          )}
          {d.mode === "agent" && isCli && (
            <div className="note bad">
              <label className="check">
                <input type="checkbox" checked={d.skip_permissions} onChange={(e) => set("skip_permissions", e.target.checked)} />
                <span>
                  <strong>Skip all permission prompts.</strong> The agent will run shell commands and edit files with no approval, as this server's user, for
                  every API caller. Only enable inside a throwaway sandbox.
                </span>
              </label>
            </div>
          )}

          <Field label="Fallback model (optional)" hint="Used only when this provider is disabled, its CLI is missing, or its direct API key is absent before a request starts. Both models must be allowed for the key. No request is retried after starting."><input value={fallbackModel} onChange={(e) => setFallbackModel(e.target.value)} placeholder="provider/model" /></Field>
          <h3>Pricing overrides</h3>
          <Field label="Rates by resolved model" hint="One line per model: model ID, input USD per million tokens, output USD per million tokens. Unknown models use an approximate fallback price; configure aliases explicitly. Claude-reported costs take precedence. Save changes to apply.">
            <textarea className="mono" value={pricingText} onChange={(e) => setPricingText(e.target.value)} placeholder={"example-model, 3, 15"} />
          </Field>
          {unconfigured.length > 0 && <p className="muted small">Models without an exact configured rate: {unconfigured.join(", ")}. Direct model mappings may use a different resolved ID; check the usage explorer for the rate actually applied.</p>}
          <details className="advanced">
            <summary>Advanced settings (JSON)</summary>
            <textarea className="mono" value={extraText} onChange={(e) => setExtraText(e.target.value)} spellCheck={false} />
            <p className="muted small">
              Agent mode: <code>workdir</code> (run in a fixed project folder instead of a temp folder), <code>extra_args</code> (extra CLI flags, e.g.{" "}
              <code>["--agent", "reviewer"]</code>). Custom CLI: <code>args_template</code>, <code>output_format</code>, <code>json_path</code>, <code>stdin</code>,{" "}
              <code>use_pty</code>, <code>login_argv</code>. Direct API: <code>base_url</code>, <code>direct_model_map</code>. Pricing rates are edited above and override the JSON field.
            </p>
          </details>

          <div className="row form-foot">
            <button className="primary" onClick={() => void save()} disabled={busy === "save"}>
              {busy === "save" ? "Saving…" : "Save changes"}
            </button>
            {msg && <span className={msg.ok ? "ok-text" : "bad-text"}>{msg.text}</span>}
            <span className="grow" />
            {p.kind === "custom" && (
              <button className="ghost danger-text" onClick={() => setRemoving(true)}>
                Delete provider
              </button>
            )}
          </div>

          <h3>Try it</h3>
          <p className="muted small">Runs one prompt with the saved settings. It is logged as an admin test and not charged to any user.</p>
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              void runTest();
            }}
          >
            <input className="grow" value={testPrompt} onChange={(e) => setTestPrompt(e.target.value)} aria-label="Test prompt" />
            <button type="submit" className="ghost" disabled={busy === "test" || !testPrompt.trim()}>
              {busy === "test" ? "Running…" : "Run test"}
            </button>
          </form>
          {test && (
            <div className="test-out">
              <div className="row">
                {test.ok ? <Pill tone="ok">passed</Pill> : <Pill tone="bad">failed</Pill>}
                <span className="muted small">
                  {(test.duration_ms / 1000).toFixed(1)}s{test.usage && ` · ${test.usage.input_tokens.toLocaleString()} in / ${test.usage.output_tokens.toLocaleString()} out tokens`}
                </span>
              </div>
              {test.error && <ErrorNote message={`${test.error.code}: ${test.error.message}`} />}
              {test.text && <div className="answer">{test.text}</div>}
              <details className="advanced">
                <summary>Raw CLI output ({test.raw_lines.length} lines)</summary>
                <pre>{test.raw_lines.join("\n")}</pre>
              </details>
            </div>
          )}
        </div>
      )}

      {connect && (
        <ConnectModal
          provider={p.name}
          userId={userId}
          onClose={() => {
            setConnect(false);
            void refresh();
          }}
        />
      )}
      {removing && (
        <Confirm
          title={`Delete ${p.name}?`}
          body="The provider and its settings are removed. Usage history is kept."
          action="Delete provider"
          onCancel={() => setRemoving(false)}
          onConfirm={async () => {
            setRemoving(false);
            await admin("DELETE", `/providers/${p.name}`).catch((e) => setMsg({ ok: false, text: (e as Error).message }));
            onChanged();
          }}
        />
      )}
    </section>
  );
}

function CustomForm({ kinds, onCreated, onClose }: { kinds: string[]; onCreated: () => void; onClose: () => void }) {
  const [name, setName] = useState("");
  const [binary, setBinary] = useState("");
  const [args, setArgs] = useState("-p {prompt} --model {model}");
  const [fmt, setFmt] = useState("text");
  const [path, setPath] = useState("");
  const [stdin, setStdin] = useState(false);
  const [model, setModel] = useState("default");
  const [err, setErr] = useState("");

  async function create() {
    try {
      await admin("POST", "/providers", {
        name, kind: kinds.includes("custom") ? "custom" : kinds[0], binary_path: binary, default_model: model, models: [model], enabled: true,
        extra: { args_template: args, output_format: fmt, ...(path ? { json_path: path } : {}), stdin },
      });
      onCreated();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <Modal title="Add a custom CLI" onClose={onClose}>
      <p className="muted">
        Any program that takes a prompt and prints an answer. In the arguments, <code>{"{prompt}"}</code>, <code>{"{model}"}</code> and <code>{"{system}"}</code> are
        replaced per request.
      </p>
      <div className="grid">
        <Field label="Name" hint="Lowercase; becomes the prefix in model ids.">
          <input value={name} onChange={(e) => setName(e.target.value.toLowerCase())} placeholder="mycli" />
        </Field>
        <Field label="Program path">
          <input value={binary} onChange={(e) => setBinary(e.target.value)} placeholder="/usr/local/bin/mycli" />
        </Field>
        <Field label="Arguments">
          <input value={args} onChange={(e) => setArgs(e.target.value)} />
        </Field>
        <Field label="Model id">
          <input value={model} onChange={(e) => setModel(e.target.value)} />
        </Field>
        <Field label="Output format">
          <select value={fmt} onChange={(e) => setFmt(e.target.value)}>
            <option value="text">Plain text</option>
            <option value="json">JSON (one document)</option>
            <option value="ndjson">NDJSON (one JSON object per line)</option>
          </select>
        </Field>
        {fmt !== "text" && (
          <Field label="JSONPath to the answer text">
            <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="$.result.text" />
          </Field>
        )}
      </div>
      <label className="check" style={{ marginTop: 10 }}>
        <input type="checkbox" checked={stdin} onChange={(e) => setStdin(e.target.checked)} /> Send the prompt on standard input
      </label>
      <ErrorNote message={err} />
      <div className="modal-foot">
        <button className="ghost" onClick={onClose}>
          Cancel
        </button>
        <button className="primary" onClick={() => void create()} disabled={!name || !binary}>
          Create provider
        </button>
      </div>
    </Modal>
  );
}
