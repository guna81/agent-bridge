import { useEffect, useRef, useState } from "react";
import { getToken, Status } from "../api";
import { Modal } from "./ui";

interface Props {
  provider: string;
  userId: number;
  onClose: (auth?: Status) => void;
}

// Strip ANSI escapes and apply carriage-return overwrites so the <pre> looks like the terminal line.
const ANSI = /\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]/g;
function render(raw: string): string {
  return raw
    .replace(ANSI, "")
    .split("\n")
    .map((l) => l.split("\r").filter(Boolean).pop() ?? "")
    .join("\n");
}

export default function ConnectModal({ provider, userId, onClose }: Props) {
  const [raw, setRaw] = useState("");
  const [urls, setUrls] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [state, setState] = useState<"connecting" | "running" | "done" | "error">("connecting");
  const [result, setResult] = useState<{ code: number | null; auth: Status } | null>(null);
  const [message, setMessage] = useState("");
  const ws = useRef<WebSocket | null>(null);
  const term = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    // The admin token is sent as the first frame, never in the URL (URLs end up in access logs).
    const s = new WebSocket(`${proto}://${location.host}/admin/ws/login/${encodeURIComponent(provider)}?user_id=${userId}`);
    ws.current = s;
    s.onopen = () => {
      s.send(JSON.stringify({ type: "auth", token: getToken() }));
      setState("running");
    };
    s.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "output") setRaw((r) => (r + m.data).slice(-20000));
      else if (m.type === "url") setUrls((u) => (u.includes(m.url) ? u : [...u, m.url]));
      else if (m.type === "exit") {
        setResult({ code: m.code, auth: m.auth });
        setState("done");
      } else if (m.type === "error") {
        setMessage(m.message);
        setState("error");
      }
    };
    s.onclose = (ev) => {
      setState((st) => (st === "running" || st === "connecting" ? (ev.code === 4401 ? "error" : "done") : st));
      if (ev.code === 4401) setMessage("Admin token rejected.");
    };
    return () => s.close();
  }, [provider, userId]);

  useEffect(() => {
    term.current?.scrollTo(0, term.current.scrollHeight);
  }, [raw]);

  const send = (data: string) => ws.current?.readyState === WebSocket.OPEN && ws.current.send(JSON.stringify({ type: "input", data }));

  return (
    <Modal title={`Connect account: ${provider}`} onClose={() => onClose(result?.auth)} wide>
        <p className="muted small">
          This runs the CLI's login command in a terminal on the server, using the isolated config directory for user #{userId}. Open the link, sign in,
          then paste the code you are given below.
        </p>

        {urls.length > 0 && (
          <div className="note ok links">
            <strong>Sign-in link{urls.length > 1 ? "s" : ""}:</strong>
            {urls.map((u) => (
              <a key={u} href={u} target="_blank" rel="noreferrer noopener">
                {u}
              </a>
            ))}
          </div>
        )}

        <pre className="term" ref={term}>
          {render(raw) || (state === "connecting" ? "Connecting…" : "(no output yet)")}
        </pre>

        <form
          className="row"
          style={{ marginTop: 8 }}
          onSubmit={(e) => {
            e.preventDefault();
            send(code + "\r");
            setCode("");
          }}
        >
          <input
            style={{ flex: 1 }}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Paste the authorization code here, then Send"
            disabled={state !== "running"}
            autoComplete="off"
          />
          <button type="submit" className="primary" disabled={state !== "running"}>
            Send
          </button>
          <button type="button" className="ghost" disabled={state !== "running"} onClick={() => send("\r")}>
            Enter ⏎
          </button>
        </form>

        {state === "error" && <p className="note bad">{message || "Connection failed."}</p>}
        {state === "done" && result && (
          <p>
            Login process exited ({result.code}).{" "}
            {result.auth.authenticated ? (
              <span className="ok-text">Signed in{result.auth.detail ? ` (${result.auth.detail})` : ""}.</span>
            ) : (
              <span className="bad-text">Not signed in{result.auth.detail ? ` (${result.auth.detail})` : ""}.</span>
            )}
          </p>
        )}
    </Modal>
  );
}
