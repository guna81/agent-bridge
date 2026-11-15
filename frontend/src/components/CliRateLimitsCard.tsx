import { AllRateLimits } from "../api";

interface Props {
  rateLimits?: AllRateLimits | null;
  onOpenConfig: () => void;
  loading?: boolean;
}

function GaugeBar({
  label,
  leftPercent,
  usedPercent,
  resetStr,
  mode = "left",
  exhausted = false,
  description,
}: {
  label: string;
  leftPercent: number;
  usedPercent: number;
  resetStr?: string | null;
  mode?: "left" | "used";
  exhausted?: boolean;
  description?: string | null;
}) {
  const displayPercent = mode === "left" ? leftPercent : usedPercent;
  const suffix = mode === "left" ? "left" : "used";

  // Determine color tone
  let toneClass = "tone-green";
  if (mode === "left") {
    if (exhausted || leftPercent <= 10) toneClass = "tone-red";
    else if (leftPercent <= 35) toneClass = "tone-amber";
  } else {
    if (usedPercent >= 90) toneClass = "tone-red";
    else if (usedPercent >= 70) toneClass = "tone-amber";
  }

  return (
    <div className="limit-gauge-item">
      <div className="gauge-header">
        <span className="gauge-label">{label}</span>
        <span className={`gauge-value ${toneClass}`}>
          {displayPercent}% {suffix}
        </span>
      </div>
      <div className="gauge-track">
        <div
          className={`gauge-fill ${toneClass}`}
          style={{ width: `${Math.max(0, Math.min(100, displayPercent))}%` }}
        />
      </div>
      <div className="gauge-footer">
        {resetStr ? (
          <span className="reset-hint muted xsmall">
            Resets {resetStr}
          </span>
        ) : (
          <span className="reset-hint muted xsmall">&nbsp;</span>
        )}
        {description && <span className="desc-hint muted xsmall" title={description}>ⓘ</span>}
      </div>
    </div>
  );
}

export default function CliRateLimitsCard({ rateLimits, onOpenConfig, loading }: Props) {
  const agy = rateLimits?.antigravity;
  const codex = rateLimits?.codex;
  const claude = rateLimits?.claude;

  const hasAny = !!(agy || codex || claude);
  const agyAvailable = !!(agy?.five_hour || agy?.weekly || agy?.claude_gpt_5h || agy?.claude_gpt_weekly);

  return (
    <section className="card cli-limits-card">
      <div className="card-head">
        <div>
          <div className="title-with-pill">
            <h2>Subscription usage</h2>

          </div>
          <p className="muted small">5-hour session & weekly rate limits across your active coding agents.</p>
        </div>
        <div className="head-actions">
          <button className="ghost small-btn" onClick={onOpenConfig}>
            Indicator settings
          </button>
        </div>
      </div>

      {loading ? <p className="muted">Loading subscription usage…</p> : !hasAny ? (
        <div className="empty-limits muted">
          No CLI rate limits detected yet. Make sure Codex, Claude Code, or Antigravity has been used on this machine, or check{" "}
          <button className="link" onClick={onOpenConfig}>indicator settings</button>.
        </div>
      ) : (
        <div className="cli-agents-grid">
          {/* Antigravity Card */}
          {agy && (
            <div className="cli-provider-box">
              <div className="box-header">
                <div className="provider-info">
                  <span className="agent-badge agy-badge">Antigravity</span>
                  <span className="provider-sub">{agy.plan_name || "Subscription Limits"}</span>
                </div>
                <span className={`status-tag ${agyAvailable ? "ok" : ""}`}>{agyAvailable ? "Available" : "Unavailable"}</span>
              </div>
              <div className="gauges-list">
                {agy.five_hour ? <GaugeBar
                  label="Gemini 5h Limit"
                  leftPercent={agy.five_hour.left_percent}
                  usedPercent={agy.five_hour.used_percent}
                  resetStr={agy.five_hour.reset_str}
                  mode="left"
                  exhausted={agy.five_hour.is_exhausted}
                  description={agy.five_hour.description}
                /> : <span className="muted xsmall">Gemini 5h Limit: unavailable</span>}
                {agy.weekly ? <GaugeBar
                  label="Gemini Weekly Limit"
                  leftPercent={agy.weekly.left_percent}
                  usedPercent={agy.weekly.used_percent}
                  resetStr={agy.weekly.reset_str}
                  mode="left"
                  exhausted={agy.weekly.is_exhausted}
                  description={agy.weekly.description}
                /> : <span className="muted xsmall">Gemini Weekly Limit: unavailable</span>}
                {agy.updated_at && <span className="muted xsmall">Last reported: {new Date(agy.updated_at * 1000).toLocaleString()}</span>}
                {!agyAvailable && <span className="muted xsmall">Waiting for Antigravity usage. Check that agy is installed and signed in.</span>}
                {agy.claude_gpt_5h && (
                  <div className="mini-sub-limit muted xsmall">
                    Claude & GPT: {agy.claude_gpt_5h.left_percent}% left 5h · {agy.claude_gpt_weekly ? `${agy.claude_gpt_weekly.left_percent}% left week` : "weekly unavailable"}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* OpenAI Codex Card */}
          {codex && (
            <div className="cli-provider-box">
              <div className="box-header">
                <div className="provider-info">
                  <span className="agent-badge codex-badge">OpenAI Codex</span>
                  <span className="provider-sub">Subscription Limits</span>
                </div>
                <span className={`status-tag ${codex.five_hour?.is_exhausted || codex.weekly?.is_exhausted ? "exhausted" : codex.five_hour || codex.weekly ? "ok" : ""}`}>
                  {codex.five_hour?.is_exhausted || codex.weekly?.is_exhausted ? "Exhausted" : codex.five_hour || codex.weekly ? "Available" : "Unavailable"}
                </span>
              </div>
              <div className="gauges-list">
                {codex.five_hour && <GaugeBar
                  label="5h Limit"
                  leftPercent={codex.five_hour.left_percent}
                  usedPercent={codex.five_hour.used_percent}
                  resetStr={codex.five_hour.reset_str}
                  mode="left"
                  exhausted={codex.five_hour.is_exhausted}
                />}
                {codex.weekly && <GaugeBar
                  label="Weekly Limit"
                  leftPercent={codex.weekly.left_percent}
                  usedPercent={codex.weekly.used_percent}
                  resetStr={codex.weekly.reset_str}
                  mode="left"
                  exhausted={codex.weekly.is_exhausted}
                />}
                <span className="muted xsmall">Last reported by Codex{codex.updated_at ? `: ${new Date(typeof codex.updated_at === "number" ? codex.updated_at * 1000 : codex.updated_at).toLocaleString()}` : ""}. Missing windows have not been reported.</span>
              </div>
            </div>
          )}

          {/* Claude Code Card */}
          {claude && (
            <div className="cli-provider-box">
              <div className="box-header">
                <div className="provider-info">
                  <span className="agent-badge claude-badge">Claude Code</span>
                  <span className="provider-sub">Utilization</span>
                </div>
                <span className={`status-tag ${claude.five_hour || claude.weekly || claude.weekly_scoped ? "ok" : ""}`}>{claude.five_hour || claude.weekly || claude.weekly_scoped ? "Available" : "Unavailable"}</span>
              </div>
              <div className="gauges-list">
                <span className="muted xsmall">
                  {claude.is_stale ? "Stale usage. " : ""}
                  {claude.updated_at ? `Last updated: ${new Date(claude.updated_at * 1000).toLocaleString()}. ` : "Update time unavailable. "}
                  {claude.refreshing ? "Refreshing…" : "Automatically refreshes every 2 minutes."}
                </span>
                {claude.refresh_error && <span className="muted xsmall">{claude.refresh_error}</span>}
                {claude.five_hour ? <GaugeBar
                  label="Current Session"
                  leftPercent={claude.five_hour.left_percent}
                  usedPercent={claude.five_hour.used_percent}
                  resetStr={claude.five_hour.reset_str}
                  mode="left"
                  exhausted={claude.five_hour.is_exhausted}
                /> : <span className="muted xsmall">Current Session: unavailable</span>}
                {claude.weekly ? <GaugeBar
                  label="Current Week (all models)"
                  leftPercent={claude.weekly.left_percent}
                  usedPercent={claude.weekly.used_percent}
                  resetStr={claude.weekly.reset_str}
                  mode="left"
                  exhausted={claude.weekly.is_exhausted}
                /> : <span className="muted xsmall">Current Week (all models): unavailable</span>}
                {claude.weekly_scoped && (
                  <GaugeBar
                    label={`Current Week (${claude.weekly_scoped.model_name})`}
                    leftPercent={claude.weekly_scoped.left_percent}
                    usedPercent={claude.weekly_scoped.used_percent}
                    resetStr={claude.weekly_scoped.reset_str}
                    mode="left"
                    exhausted={claude.weekly_scoped.is_exhausted}
                  />
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
