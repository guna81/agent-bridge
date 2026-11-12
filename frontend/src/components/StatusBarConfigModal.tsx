import { useState } from "react";
import { StatusBarConfig } from "../api";

interface Props {
  config: StatusBarConfig;
  onSave: (newCfg: StatusBarConfig) => Promise<void>;
  onClose: () => void;
  inline?: boolean;
}

export default function StatusBarConfigModal({ config, onSave, onClose, inline = false }: Props) {
  const [indicatorEnabled, setIndicatorEnabled] = useState(config.indicator_enabled ?? true);
  const [enabledProviders, setEnabledProviders] = useState(config.enabled_providers);
  const [selectedClis, setSelectedClis] = useState<string[]>(config.selected_clis || ["antigravity"]);
  const [displayMode, setDisplayMode] = useState(config.display_mode || "bars");
  const [interval, setInterval] = useState(config.refresh_interval_seconds || 3);
  const [codexPath, setCodexPath] = useState(config.codex_sqlite_path || "");
  const [claudePath, setClaudePath] = useState(config.claude_json_path || "");
  const [agyAddress, setAgyAddress] = useState(config.antigravity_ls_address || "");
  const [agyToken, setAgyToken] = useState(config.antigravity_csrf_token || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onSave({
        indicator_enabled: indicatorEnabled,
        enabled_providers: enabledProviders,
        display_mode: displayMode,
        pinned_metric: config.pinned_metric,
        selected_clis: selectedClis,
        refresh_interval_seconds: Number(interval),
        codex_sqlite_path: codexPath.trim(),
        claude_json_path: claudePath.trim(),
        antigravity_ls_address: agyAddress.trim(),
        antigravity_csrf_token: agyToken.trim(),
      });
      if (!inline) onClose();
    } catch (err) {
      setError((err as Error).message || "Failed to save configuration");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={inline ? "status-settings-page" : "modal-backdrop"} onClick={inline ? undefined : onClose}>
      <div className={inline ? "card config-modal" : "modal-card config-modal"} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3>Usage tracking and indicator</h3>
            <p className="muted small">Configure usage tracking and the menu bar or system tray on this computer.</p>
          </div>
          {!inline && <button className="close-btn" onClick={onClose}>&times;</button>}
        </div>

        {error && <div className="error-note">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="indicator-setting">
            <div><label className="group-label" htmlFor="indicatorEnabled">Show status indicator</label>
              <p className="muted small">Show AgentBridge in the menu bar or system tray. Usage tracking and the gateway stay active when hidden. Changes apply on the next indicator refresh; if started with --no-tray, restart without it.</p></div>
            <label className="switch"><input id="indicatorEnabled" type="checkbox" role="switch" checked={indicatorEnabled} onChange={(e) => setIndicatorEnabled(e.target.checked)} /><span /></label>
          </div>
          <div className="form-group">
            <label className="group-label">Tracked agents</label>
            <div className="checkbox-row">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={enabledProviders.antigravity}
                  onChange={(e) => setEnabledProviders({ ...enabledProviders, antigravity: e.target.checked })}
                />
                Google Antigravity
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={enabledProviders.codex}
                  onChange={(e) => setEnabledProviders({ ...enabledProviders, codex: e.target.checked })}
                />
                OpenAI Codex
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={enabledProviders.claude}
                  onChange={(e) => setEnabledProviders({ ...enabledProviders, claude: e.target.checked })}
                />
                Claude Code
              </label>
            </div>
          </div>

          <div className="form-group">
            <label className="group-label">Agents shown in indicator (choose one or two)</label>
            <p className="muted small">Only tracked agents can provide usage data. Tracking is separate from gateway provider settings.</p>
            <div className="checkbox-row">
              {[["codex", "Codex"], ["claude", "Claude Code"], ["antigravity", "Antigravity"]].map(([id, label]) => (
                <label className="checkbox-label" key={id}>
                  <input type="checkbox" checked={selectedClis.includes(id)}
                    disabled={selectedClis.includes(id) ? selectedClis.length === 1 : selectedClis.length === 2}
                    onChange={() => setSelectedClis(selectedClis.includes(id) ? selectedClis.filter(x => x !== id) : [...selectedClis, id])} />
                  {label}
                </label>
              ))}
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="displayMode" className="group-label">Display style</label>
            <select id="displayMode" className="select-input" value={displayMode} onChange={(e) => setDisplayMode(e.target.value as "bars" | "compact")}>
              <option value="bars">Agent icons and usage bars</option>
              <option value="compact">Compact AgentBridge icon with click-to-view details</option>
            </select>
            <div className="indicator-preview" aria-label={displayMode === "bars" ? "Illustration of remaining usage bars" : "Illustration of compact indicator"}>
              {displayMode === "bars" ? <><span className="preview-agent">Agent</span><span className="preview-bars"><span><i style={{width: "72%"}} /></span><span><i style={{width: "38%"}} /></span></span><span className="muted small">5h · week remaining</span></> : <><svg className="preview-bridge" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="18" fill="#101114"/><path d="M12 40h9l8-15a3.4 3.4 0 0 1 6 0l8 15h9" fill="none" stroke="#f7f8fa" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/><path d="M26 40h12" fill="none" stroke="#6597ff" strokeWidth="5" strokeLinecap="round"/></svg><span className="muted small">Click for usage details</span></>}
            </div>
            <p className="muted small">Illustrative preview; actual appearance varies by platform. Bars show remaining usage: they shrink as usage increases. Click the indicator for percentages and reset times. Windows and Linux use compact tray graphics; an always-visible widget is not currently available.</p>
          </div>

          <div className="form-group">
            <label htmlFor="refreshInterval" className="group-label">Refresh interval</label>
            <select
              id="refreshInterval"
              value={interval}
              onChange={(e) => setInterval(Number(e.target.value))}
              className="select-input"
            >
              {![2, 3, 5, 10].includes(interval) && <option value={interval}>{interval} seconds</option>}
              <option value={2}>2 seconds (High responsiveness)</option>
              <option value={3}>3 seconds (Recommended)</option>
              <option value={5}>5 seconds</option>
              <option value={10}>10 seconds (Battery saver)</option>
            </select>
          </div>

          <details className="advanced-paths">
            <summary className="muted small">Advanced: custom paths and overrides</summary>
            <div className="details-body">
              <div className="field">
                <label className="xsmall muted">Antigravity Language Server Address</label>
                <input
                  type="text"
                  placeholder="Optional (e.g. localhost:64863)"
                  value={agyAddress}
                  onChange={(e) => setAgyAddress(e.target.value)}
                  className="text-input"
                />
              </div>
              <div className="field">
                <label className="xsmall muted">Antigravity CSRF Token</label>
                <input
                  type="text"
                  placeholder="Optional language server token"
                  value={agyToken}
                  onChange={(e) => setAgyToken(e.target.value)}
                  className="text-input"
                />
              </div>
              <div className="field">
                <label className="xsmall muted">Codex SQLite Log Path</label>
                <input
                  type="text"
                  placeholder="Default: ~/.codex/logs_2.sqlite"
                  value={codexPath}
                  onChange={(e) => setCodexPath(e.target.value)}
                  className="text-input"
                />
              </div>
              <div className="field">
                <label className="xsmall muted">Claude Code Config Path</label>
                <input
                  type="text"
                  placeholder="Default: ~/.claude.json"
                  value={claudePath}
                  onChange={(e) => setClaudePath(e.target.value)}
                  className="text-input"
                />
              </div>
            </div>
          </details>

          <div className="modal-actions">
            {!inline && <button type="button" className="ghost" onClick={onClose} disabled={saving}>
              Cancel
            </button>}
            <button type="submit" className="primary" disabled={saving}>
              {saving ? "Saving…" : "Save settings"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
