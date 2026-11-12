import { useCallback, useEffect, useState } from "react";
import { admin, StatusBarData } from "../api";
import type { Tab } from "../App";
import CliRateLimitsCard from "../components/CliRateLimitsCard";
import { ErrorNote } from "../components/ui";

export default function SubscriptionUsage({ go }: { go: (tab: Tab) => void }) {
  const [data, setData] = useState<StatusBarData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try {
      setData(await admin<StatusBarData>("GET", "/status-bar"));
      setError("");
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [load]);
  return <>
    <div className="page-head"><div><h1>Subscription usage</h1><p className="muted">Remaining agent subscription limits. These are separate from API gateway request costs.</p></div><button className="ghost" onClick={() => void load()}>Refresh</button></div>
    <ErrorNote message={error ? `Unable to refresh subscription usage: ${error}${data ? " (showing the last result)" : ""}` : ""} />
    {(data || loading) && <CliRateLimitsCard rateLimits={data?.rate_limits} loading={loading} onOpenConfig={() => go("statusbar")} />}
  </>;
}
