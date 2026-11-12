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
          style={{ width: `${Math.max(2, Math.min(100, displayPercent))}%` }}
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

  return (
    <section className="card cli-limits-card">
      <div className="card-head">
        <div>
          <div className="title-with-pill">
            <h2>CLI Agent Subscription Limits</h2>
            <span className="live-indicator-pill" title="Auto-refreshing rate limits">
              <span className="live-dot" /> LIVE
            </span>
          </div>
          <p className="muted small">5-hour session & weekly rate limits across your active coding agents.</p>
        </div>
        <div className="head-actions">
          <button className="ghost small-btn" onClick={onOpenConfig}>
            ⚙ Configuration
          </button>
        </div>
      </div>

      {!hasAny && !loading ? (
        <div className="empty-limits muted">
          No CLI rate limits detected yet. Make sure Codex, Claude Code, or Antigravity has been used on this machine, or check{" "}
          <button className="link" onClick={onOpenConfig}>Configuration</button>.
        </div>
      ) : (
        <div className="cli-agents-grid">
          {/* Antigravity Card */}
          {agy && (
            <div className="cli-provider-box">
              <div className="box-header">
                <div className="provider-info">
                  <span className="agent-badge agy-badge">Antigravity</span>
                  <span className="provider-sub">{agy.plan_name || "Google AI Pro"}</span>
                </div>
                <span className="status-tag ok">Active</span>
              </div>
              <div className="gauges-list">
                <GaugeBar
                  label="Gemini 5h Limit"
                  leftPercent={agy.five_hour.left_percent}
                  usedPercent={agy.five_hour.used_percent}
                  resetStr={agy.five_hour.reset_str}
                  mode="left"
                  exhausted={agy.five_hour.is_exhausted}
                  description={agy.five_hour.description}
                />
                <GaugeBar
                  label="Gemini Weekly Limit"
                  leftPercent={agy.weekly.left_percent}
                  usedPercent={agy.weekly.used_percent}
                  resetStr={agy.weekly.reset_str}
                  mode="left"
                  exhausted={agy.weekly.is_exhausted}
                  description={agy.weekly.description}
                />
                {agy.claude_gpt_5h && (
                  <div className="mini-sub-limit muted xsmall">
                    Claude & GPT: {agy.claude_gpt_5h.left_percent}% left 5h · {agy.claude_gpt_weekly?.left_percent ?? 100}% left week
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
                <span className={`status-tag ${codex.five_hour.is_exhausted ? "exhausted" : "ok"}`}>
                  {codex.five_hour.is_exhausted ? "5h Exhausted" : "Active"}
                </span>
              </div>
              <div className="gauges-list">
                <GaugeBar
                  label="5h Limit"
                  leftPercent={codex.five_hour.left_percent}
                  usedPercent={codex.five_hour.used_percent}
                  resetStr={codex.five_hour.reset_str}
                  mode="left"
                  exhausted={codex.five_hour.is_exhausted}
                />
                <GaugeBar
                  label="Weekly Limit"
                  leftPercent={codex.weekly.left_percent}
                  usedPercent={codex.weekly.used_percent}
                  resetStr={codex.weekly.reset_str}
                  mode="left"
                  exhausted={codex.weekly.is_exhausted}
                />
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
                <span className="status-tag ok">Active</span>
              </div>
              <div className="gauges-list">
                <GaugeBar
                  label="Current Session"
                  leftPercent={claude.five_hour.left_percent}
                  usedPercent={claude.five_hour.used_percent}
                  resetStr={claude.five_hour.reset_str}
                  mode="used"
                  exhausted={claude.five_hour.is_exhausted}
                />
                <GaugeBar
                  label="Current Week (all models)"
                  leftPercent={claude.weekly.left_percent}
                  usedPercent={claude.weekly.used_percent}
                  resetStr={claude.weekly.reset_str}
                  mode="used"
                  exhausted={claude.weekly.is_exhausted}
                />
                {claude.weekly_scoped && (
                  <GaugeBar
                    label={`Current Week (${claude.weekly_scoped.model_name})`}
                    leftPercent={claude.weekly_scoped.left_percent}
                    usedPercent={claude.weekly_scoped.used_percent}
                    resetStr={claude.weekly_scoped.reset_str}
                    mode="used"
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
