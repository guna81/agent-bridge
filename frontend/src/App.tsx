import { useCallback, useEffect, useState } from "react";
import { admin, AdminSettings, getToken, setToken } from "./api";
import Overview from "./pages/Overview";
import Providers from "./pages/Providers";
import Keys from "./pages/Keys";
import Playground from "./pages/Playground";
import QuickStart from "./pages/QuickStart";

const TABS = [
  { id: "overview", label: "Overview", icon: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" },
  { id: "providers", label: "Providers", icon: "M4 6h16v4H4V6zm0 8h16v4H4v-4zm3-6.5a1 1 0 100 2 1 1 0 000-2zm0 8a1 1 0 100 2 1 1 0 000-2z" },
  { id: "keys", label: "Keys & usage", icon: "M14 3a7 7 0 00-6.7 9.1L2 17.4V22h4.6v-2.5H9V17h2.4l1.5-1.5A7 7 0 1014 3zm2.5 6.5a2 2 0 110-4 2 2 0 010 4z" },
  { id: "playground", label: "Playground", icon: "M4 4h16a1 1 0 011 1v11a1 1 0 01-1 1H9l-5 4V5a1 1 0 011-1z" },
  { id: "quickstart", label: "Quick start", icon: "M8.6 16.6L4 12l4.6-4.6L10 8.8 6.8 12l3.2 3.2-1.4 1.4zm6.8 0L14 15.2l3.2-3.2L14 8.8l1.4-1.4L20 12l-4.6 4.6z" },
] as const;
export type Tab = (typeof TABS)[number]["id"];

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
    } catch {
      setAuthed(false);
      setToken("");
      setError(token ? "That admin token was rejected." : "");
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

  if (checking) return <div className="splash">Loading…</div>;

  if (!authed) {
    return (
      <main className="login">
        <div className="brand big">
          <Logo /> LLM CLI Gateway
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
            Enter the admin token: the value of <code>PROXY_ADMIN_TOKEN</code>, or the contents of <code>data/admin_token</code> if you did not set one.
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
          <Logo /> LLM CLI Gateway
        </div>
        <nav aria-label="Sections">
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? "active" : ""} aria-current={tab === t.id ? "page" : undefined} onClick={() => setTab(t.id)}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d={t.icon} />
              </svg>
              <span>{t.label}</span>
            </button>
          ))}
        </nav>
        <div className="side-foot">
          {q && (
            <div className="queue" title="CLI runs in progress on this server">
              <span className={`dot ${q.running ? "live" : ""}`} />
              {q.running} running · {q.waiting} queued
              <span className="muted"> / {q.max_concurrency}</span>
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
        </div>
      </aside>
      <main className="content">
        {tab === "overview" && settings && <Overview settings={settings} go={setTab} />}
        {tab === "providers" && settings && <Providers settings={settings} />}
        {tab === "keys" && <Keys go={setTab} />}
        {tab === "playground" && <Playground go={setTab} />}
        {tab === "quickstart" && <QuickStart />}
      </main>
    </div>
  );
}

function Logo() {
  return (
    <svg className="logo" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient id="g-grad" x1="4" y1="4" x2="28" y2="28" gradientUnits="userSpaceOnUse">
          <stop stopColor="#38BDF8" />
          <stop offset="0.5" stopColor="#818CF8" />
          <stop offset="1" stopColor="#C084FC" />
        </linearGradient>
        <linearGradient id="tile-bg" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0F172A" />
          <stop offset="1" stopColor="#1E1B4B" />
        </linearGradient>
        <linearGradient id="tile-stroke" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#38BDF8" stopOpacity="0.6" />
          <stop offset="1" stopColor="#A855F7" stopOpacity="0.4" />
        </linearGradient>
      </defs>
      <rect x="1.5" y="1.5" width="29" height="29" rx="8" fill="url(#tile-bg)" stroke="url(#tile-stroke)" strokeWidth="1.2" />
      <path
        d="M22 10.5C20.3 8.3 17.6 7 14.5 7C9.8 7 6 10.8 6 15.5C6 20.2 9.8 24 14.5 24C19.2 24 23 20.2 23 15.5V15"
        stroke="url(#g-grad)"
        strokeWidth="2.75"
        strokeLinecap="round"
      />
      <path
        d="M11 13L15 16L11 19"
        stroke="#FFFFFF"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M17 19H21"
        stroke="#38BDF8"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path
        d="M24 5L24.8 7.2L27 8L24.8 8.8L24 11L23.2 8.8L21 8L23.2 7.2Z"
        fill="#38BDF8"
      />
    </svg>
  );
}
