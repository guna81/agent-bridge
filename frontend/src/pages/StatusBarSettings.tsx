import { useEffect, useState } from "react";
import { admin, StatusBarConfig } from "../api";
import StatusBarConfigModal from "../components/StatusBarConfigModal";

export default function StatusBarSettings() {
  const [config, setConfig] = useState<StatusBarConfig | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    admin<StatusBarConfig>("GET", "/status-bar/config").then(setConfig).catch((e) => setError(e.message));
  }, []);
  return <>
    <div className="page-head"><h1>Status indicator settings</h1><p className="muted">Choose what AgentBridge shows in the macOS menu bar or the Windows or Linux system tray. Settings apply to the machine running the gateway.</p></div>
    {error && <p className="note bad" role="alert">{error}</p>}
    {saved && <p className="note" role="status">Settings saved. Your indicator will update on its next refresh.</p>}
    {config && <StatusBarConfigModal inline config={config} onClose={() => {}} onSave={async (next) => {
      setSaved(false);
      const updated = await admin<StatusBarConfig>("POST", "/status-bar/config", next);
      setConfig(updated);
      setSaved(true);
    }} />}
    {!config && !error && <p>Loading settings…</p>}
  </>;
}
