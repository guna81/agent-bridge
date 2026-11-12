import { useState } from "react";
import { StatusBarConfig } from "../api";

interface Props {
  config: StatusBarConfig;
  onSave: (newCfg: StatusBarConfig) => Promise<void>;
  onClose: () => void;
}

export default function StatusBarConfigModal({ config, onSave, onClose }: Props) {
  const [enabledProviders, setEnabledProviders] = useState(config.enabled_providers);
  const [pinnedMetric, setPinnedMetric] = useState(config.pinned_metric || "antigravity_gemini_5h");
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
        enabled_providers: enabledProviders,
        pinned_metric: pinnedMetric,
        refresh_interval_seconds: Number(interval),
        codex_sqlite_path: codexPath.trim(),
        claude_json_path: claudePath.trim(),
        antigravity_ls_address: agyAddress.trim(),
        antigravity_csrf_token: agyToken.trim(),
      });
      onClose();
    } catch (err) {
      setError((err as Error).message || "Failed to save configuration");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card config-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3>Status Bar & CLI Agent Configuration</h3>
            <p className="muted small">Configure CLI rate limit tracking and macOS menu bar options.</p>
          </div>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        {error && <div className="error-note">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="group-label">Active CLI Providers</label>
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
            <label htmlFor="pinnedMetric" className="group-label">Pinned Status Bar Metric</label>
            <p className="muted xsmall">Choose which gauge renders in the macOS top status bar.</p>
            <select
              id="pinnedMetric"
              value={pinnedMetric}
              onChange={(e) => setPinnedMetric(e.target.value)}
              className="select-input"
            >
              <option value="antigravity_gemini_5h">Antigravity: Gemini 5-Hour Limit</option>
              <option value="antigravity_gemini_weekly">Antigravity: Gemini Weekly Limit</option>
              <option value="codex_5h">Codex: 5-Hour Limit</option>
              <option value="codex_weekly">Codex: Weekly Limit</option>
              <option value="claude_session">Claude Code: Current Session</option>
              <option value="claude_weekly">Claude Code: Current Week (All Models)</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="refreshInterval" className="group-label">Polling Refresh Interval</label>
            <select
              id="refreshInterval"
              value={interval}
              onChange={(e) => setInterval(Number(e.target.value))}
              className="select-input"
            >
              <option value={2}>2 seconds (High responsiveness)</option>
              <option value={3}>3 seconds (Recommended)</option>
              <option value={5}>5 seconds</option>
              <option value={10}>10 seconds (Battery saver)</option>
            </select>
          </div>

          <details className="advanced-paths">
            <summary className="muted small">Advanced: Custom Paths & Overrides</summary>
            <div className="details-body">
              <div className="field">
                <label className="xsmall muted">Antigravity Language Server Address</label>
                <input
                  type="text"
                  placeholder="Auto-detected (e.g. localhost:64863)"
                  value={agyAddress}
                  onChange={(e) => setAgyAddress(e.target.value)}
                  className="text-input"
                />
              </div>
              <div className="field">
                <label className="xsmall muted">Antigravity CSRF Token</label>
                <input
                  type="text"
                  placeholder="Auto-detected from CLI session"
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
            <button type="button" className="ghost" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" className="primary" disabled={saving}>
              {saving ? "Saving…" : "Save Configuration"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
