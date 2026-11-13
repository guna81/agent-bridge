import { useCallback, useEffect, useState } from "react";
import { admin, AdminSettings, ApiError, getToken, setToken } from "./api";
import Overview from "./pages/Overview";
import Providers from "./pages/Providers";
import Keys from "./pages/Keys";
import Playground from "./pages/Playground";
import QuickStart from "./pages/QuickStart";
import StatusBarSettings from "./pages/StatusBarSettings";
import SubscriptionUsage from "./pages/SubscriptionUsage";

const TABS = [
  { id: "overview", label: "Overview", icon: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" },
  { id: "subscription", label: "Subscription usage", icon: "M4 4h4v16H4V4zm6 5h4v11h-4V9zm6-3h4v14h-4V6z" },
  { id: "statusbar", label: "Status indicator", icon: "M4 4h16v4H4V4zm0 6h16v10H4V10zm3 3v4h2v-4H7zm4 2v2h2v-2h-2zm4-3v5h2v-5h-2z" },
  { id: "providers", label: "Providers", icon: "M4 6h16v4H4V6zm0 8h16v4H4v-4zm3-6.5a1 1 0 100 2 1 1 0 000-2zm0 8a1 1 0 100 2 1 1 0 000-2z" },
  { id: "keys", label: "API keys & users", icon: "M14 3a7 7 0 00-6.7 9.1L2 17.4V22h4.6v-2.5H9V17h2.4l1.5-1.5A7 7 0 1014 3zm2.5 6.5a2 2 0 110-4 2 2 0 010 4z" },
  { id: "requests", label: "Request usage", icon: "M4 4h16v16H4V4zm3 3v2h10V7H7zm0 4v2h10v-2H7zm0 4v2h7v-2H7z" },
  { id: "playground", label: "Playground", icon: "M4 4h16a1 1 0 011 1v11a1 1 0 01-1 1H9l-5 4V5a1 1 0 011-1z" },
  { id: "quickstart", label: "API quick start", icon: "M8.6 16.6L4 12l4.6-4.6L10 8.8 6.8 12l3.2 3.2-1.4 1.4zm6.8 0L14 15.2l3.2-3.2L14 8.8l1.4-1.4L20 12l-4.6 4.6z" },
] as const;
export type Tab = (typeof TABS)[number]["id"];

// CLI-provided credentials stay in the fragment, which is not sent to the server.
// Remove it before rendering or making requests.
const fragment = new URLSearchParams(window.location.hash.slice(1));
const launchToken = fragment.get("admin_token");
if (launchToken) {
  history.replaceState(null, "", `${location.pathname}${location.search}#overview`);
  setToken(launchToken);
}

const tabFromHash = (): Tab => (TABS.find((t) => t.id === location.hash.slice(1))?.id ?? "overview") as Tab;
const THEME_KEY = "proxy.theme";

function useTheme() {
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem(THEME_KEY) ?? "";
    } catch {
      return "";
    }
  });
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try {
      if (theme) localStorage.setItem(THEME_KEY, theme);
      else localStorage.removeItem(THEME_KEY);
    } catch {
      /* ignore */
    }
  }, [theme]);
  const isDark = theme ? theme === "dark" : window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  return { isDark, toggle: () => setTheme(isDark ? "light" : "dark") };
}

export default function App() {
  const [tab, setTabState] = useState<Tab>(tabFromHash);
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(!!getToken());
  const [tokenInput, setTokenInput] = useState("");
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [error, setError] = useState("");
  const [update, setUpdate] = useState<{ current: string; latest: string | null; available: boolean; release_url: string } | null>(null);
  const { isDark, toggle } = useTheme();

  const setTab = useCallback((t: Tab) => {
    setTabState(t);
    history.replaceState(null, "", `#${t}`);
    window.scrollTo(0, 0);
  }, []);

  const login = useCallback(async (token: string) => {
    setToken(token);
    try {
      setSettings(await admin<AdminSettings>("GET", "/settings"));
      setAuthed(true);
      setError("");
    } catch (e) {
      setAuthed(false);
      setToken("");
      setError(token ? (e instanceof ApiError && e.status === 401 ? "That admin token was rejected." : `Could not connect to the server: ${(e as Error).message}`) : "");
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    if (getToken()) void login(getToken());
    const onHash = () => setTabState(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [login]);

  // keep the queue indicator fresh
  useEffect(() => {
    if (!authed) return;
    const t = setInterval(() => admin<AdminSettings>("GET", "/settings").then(setSettings).catch(() => {}), 5000);
    return () => clearInterval(t);
  }, [authed]);

  useEffect(() => {
    if (!authed) { setUpdate(null); return; }
    const check = () => admin<{ current: string; latest: string | null; available: boolean; release_url: string }>("GET", "/update-status").then(setUpdate).catch(() => {});
    void check();
    const timer = setInterval(check, 60 * 60 * 1000);
    return () => clearInterval(timer);
  }, [authed]);

  if (checking) return <div className="splash">Loading…</div>;

  if (!authed) {
    return (
      <main className="login">
        <div className="brand big">
          <Logo /> AgentBridge
        </div>
        <form
          className="card"
          onSubmit={(e) => {
            e.preventDefault();
            void login(tokenInput.trim());
          }}
        >
          <h1>Sign in</h1>
          <p className="muted">
            Run <code>agentbridge dashboard</code> to open this page signed in, or enter the admin token configured for your server.
          </p>
          <input type="password" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} placeholder="Admin token" aria-label="Admin token" autoFocus />
          {error && (
            <p className="note bad" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="primary block" disabled={!tokenInput.trim()}>
            Sign in
          </button>
        </form>
      </main>
    );
  }

  const q = settings?.queue;
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <Logo />
          <div className="brand-copy"><span>AgentBridge</span><small>API & usage dashboard</small></div>
        </div>
        <div className="side-label">Workspace</div>
        <nav aria-label="Sections">
          {TABS.map((t) => (
            <div key={t.id}>
            {t.id === "subscription" && <div className="side-label">Agent usage</div>}
            {t.id === "providers" && <div className="side-label">API gateway</div>}
            <button key={t.id} className={tab === t.id ? "active" : ""} style={{ width: "100%" }} aria-current={tab === t.id ? "page" : undefined} onClick={() => setTab(t.id)}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d={t.icon} />
              </svg>
              <span>{t.label}</span>
            </button>
            </div>
          ))}
        </nav>
        <div className="side-foot">
          {q && (
            <div className="queue-card" title="CLI runs in progress on this server">
              <div className="queue-title">CLI activity</div>
              <div className="queue"><span className={`dot ${q.running ? "live" : ""}`} />
                {q.running} running · {q.waiting} queued
              </div>
              <div className="queue-capacity">Concurrency limit: {q.max_concurrency}</div>
            </div>
          )}
          <div className="row">
            <button className="ghost small" onClick={toggle} aria-label="Switch colour theme">
              {isDark ? "☀ Light" : "☾ Dark"}
            </button>
            <button
              className="ghost small"
              onClick={() => {
                setToken("");
                setAuthed(false);
                setTokenInput("");
              }}
            >
              Sign out
            </button>
          </div>
          {update && <div className="sidebar-version"><div>AgentBridge v{update.current}</div>{update.available && <a href={update.release_url} target="_blank" rel="noopener noreferrer">Update available ↗</a>}</div>}
        </div>
      </aside>
      <main className="content">
        {update?.available && <div className="note update-notice" role="status"><div><strong>AgentBridge {update.latest} is available</strong><p className="small">You are running {update.current}. Run agentbridge update, then restart AgentBridge to use the new version.</p></div><a href={update.release_url} target="_blank" rel="noopener noreferrer">View release and install instructions ↗</a></div>}
        {tab === "overview" && settings && <Overview settings={settings} go={setTab} />}
        {tab === "subscription" && <SubscriptionUsage go={setTab} />}
        {tab === "providers" && settings && <Providers settings={settings} />}
        {tab === "keys" && <Keys go={setTab} />}
        {tab === "requests" && <Keys go={setTab} usageOnly />}
        {tab === "playground" && <Playground go={setTab} />}
        {tab === "statusbar" && <StatusBarSettings />}
        {tab === "quickstart" && <QuickStart go={setTab} />}
      </main>
    </div>
  );
}

function Logo() {
  return <img className="logo" src="/agentbridge-icon.svg" alt="" aria-hidden="true" />;
}
