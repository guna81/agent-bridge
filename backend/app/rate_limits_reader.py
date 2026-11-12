import datetime as dt
import glob
import json
import os
from pathlib import Path
import re
import sqlite3
import urllib.request


def get_codex_rate_limits(custom_path: str | None = None) -> dict | None:
    """Reads the latest 5-hour and weekly subscription limits logged by Codex CLI."""
    db_path = os.path.expanduser(custom_path or "~/.codex/logs_2.sqlite")
    if not os.path.exists(db_path):
        return None

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
        cur = conn.cursor()
        cur.execute("""
            SELECT ts, feedback_log_body FROM logs 
            WHERE feedback_log_body LIKE '%x-codex-primary-used-percent%'
            ORDER BY id DESC LIMIT 1
        """)
        row = cur.fetchone()
        conn.close()
        if not row:
            return None

        ts_log, text = row

        p_used = re.search(r'\"x-codex-primary-used-percent\":\s*\"(\d+)\"', text)
        s_used = re.search(r'\"x-codex-secondary-used-percent\":\s*\"(\d+)\"', text)
        p_reset = re.search(r'\"x-codex-primary-reset-at\":\s*\"(\d+)\"', text)
        s_reset = re.search(r'\"x-codex-secondary-reset-at\":\s*\"(\d+)\"', text)

        primary_used_val = int(p_used.group(1)) if p_used else 0
        secondary_used_val = int(s_used.group(1)) if s_used else 0
        primary_reset_val = int(p_reset.group(1)) if p_reset else 0
        secondary_reset_val = int(s_reset.group(1)) if s_reset else 0

        primary_left_val = max(0, 100 - primary_used_val)
        secondary_left_val = max(0, 100 - secondary_used_val)

        now_ts = int(dt.datetime.now().timestamp())
        if primary_reset_val and now_ts >= primary_reset_val:
            primary_left_val = 100
            primary_used_val = 0

        if secondary_reset_val and now_ts >= secondary_reset_val:
            secondary_left_val = 100
            secondary_used_val = 0

        def fmt_time(ts: int | None) -> str | None:
            if not ts:
                return None
            return dt.datetime.fromtimestamp(ts).strftime("%-I:%M %p")

        def fmt_date(ts: int | None) -> str | None:
            if not ts:
                return None
            return dt.datetime.fromtimestamp(ts).strftime("%-I:%M %p on %-d %b")

        return {
            "five_hour": {
                "label": "5h limit",
                "used_percent": primary_used_val,
                "left_percent": primary_left_val,
                "reset_at": primary_reset_val,
                "reset_str": fmt_time(primary_reset_val),
                "is_exhausted": primary_left_val == 0,
            },
            "weekly": {
                "label": "Weekly limit",
                "used_percent": secondary_used_val,
                "left_percent": secondary_left_val,
                "reset_at": secondary_reset_val,
                "reset_str": fmt_date(secondary_reset_val),
                "is_exhausted": secondary_left_val == 0,
            },
            "updated_at": ts_log,
        }
    except Exception:
        return None


def get_claude_rate_limits(custom_path: str | None = None) -> dict | None:
    """Reads real-time session and weekly rate limits from Claude Code (~/.claude.json)."""
    claude_json_path = os.path.expanduser(custom_path or "~/.claude.json")
    if os.path.exists(claude_json_path):
        try:
            with open(claude_json_path, "r", encoding="utf-8") as f:
                d = json.load(f)

            cached = d.get("cachedUsageUtilization", {})
            u = cached.get("utilization", {})

            if u:
                five_h = u.get("five_hour", {})
                seven_d = u.get("seven_day", {})

                five_used = int(five_h.get("utilization", 0))
                five_left = max(0, 100 - five_used)
                five_reset_iso = five_h.get("resets_at")

                seven_used = int(seven_d.get("utilization", 0))
                seven_left = max(0, 100 - seven_used)
                seven_reset_iso = seven_d.get("resets_at")

                def fmt_iso_time(iso_str: str | None) -> str | None:
                    if not iso_str:
                        return None
                    try:
                        dt_obj = dt.datetime.fromisoformat(iso_str)
                        local_dt = dt_obj.astimezone()
                        return local_dt.strftime("%-I:%M%p").lower()
                    except Exception:
                        return None

                def fmt_iso_date(iso_str: str | None) -> str | None:
                    if not iso_str:
                        return None
                    try:
                        dt_obj = dt.datetime.fromisoformat(iso_str)
                        local_dt = dt_obj.astimezone()
                        return local_dt.strftime("%b %-d at %-I:%M%p").lower()
                    except Exception:
                        return None

                limits = u.get("limits", [])
                scoped_item = next((x for x in limits if x.get("kind") == "weekly_scoped"), None)

                scoped_dict = None
                if scoped_item:
                    sc_used = int(scoped_item.get("percent", 0))
                    sc_model = scoped_item.get("scope", {}).get("model", {}).get("display_name", "Model")
                    scoped_dict = {
                        "label": f"Current week ({sc_model})",
                        "model_name": sc_model,
                        "used_percent": sc_used,
                        "left_percent": max(0, 100 - sc_used),
                        "reset_str": fmt_iso_date(scoped_item.get("resets_at")),
                        "is_exhausted": sc_used >= 100,
                    }

                now = dt.datetime.now(dt.timezone.utc)
                if five_reset_iso:
                    try:
                        if now >= dt.datetime.fromisoformat(five_reset_iso):
                            five_used = 0
                            five_left = 100
                    except Exception:
                        pass

                return {
                    "five_hour": {
                        "label": "Current session",
                        "used_percent": five_used,
                        "left_percent": five_left,
                        "reset_at": None,
                        "reset_str": fmt_iso_time(five_reset_iso),
                        "is_exhausted": five_used >= 100,
                    },
                    "weekly": {
                        "label": "Current week (all models)",
                        "used_percent": seven_used,
                        "left_percent": seven_left,
                        "reset_at": None,
                        "reset_str": fmt_iso_date(seven_reset_iso),
                        "is_exhausted": seven_used >= 100,
                    },
                    "weekly_scoped": scoped_dict,
                }
        except Exception:
            pass

    return {
        "five_hour": {"label": "Current session", "used_percent": 0, "left_percent": 100, "reset_at": None, "reset_str": None, "is_exhausted": False},
        "weekly": {"label": "Current week", "used_percent": 0, "left_percent": 100, "reset_at": None, "reset_str": None, "is_exhausted": False},
        "weekly_scoped": None,
    }


def get_antigravity_rate_limits() -> dict | None:
    """Reads real-time 5-hour, weekly, and third-party rate limits from Google Antigravity."""
    from .status_bar_config import load_status_bar_config

    cfg = load_status_bar_config()
    ls_address = cfg.antigravity_ls_address or os.environ.get("ANTIGRAVITY_LS_ADDRESS", "")
    csrf_token = cfg.antigravity_csrf_token or os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "")

    cache_dir = Path(__file__).resolve().parent.parent / "data"
    cache_path = cache_dir / "antigravity_quota_cache.json"

    def fmt_iso_time(iso_str: str | None) -> str | None:
        if not iso_str:
            return None
        try:
            dt_obj = dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            local_dt = dt_obj.astimezone()
            return local_dt.strftime("%-I:%M %p")
        except Exception:
            return None

    def fmt_iso_date(iso_str: str | None) -> str | None:
        if not iso_str:
            return None
        try:
            dt_obj = dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            local_dt = dt_obj.astimezone()
            return local_dt.strftime("%b %-d at %-I:%M %p")
        except Exception:
            return None

    def iso_to_epoch(iso_str: str | None) -> int | None:
        if not iso_str:
            return None
        try:
            dt_obj = dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return int(dt_obj.timestamp())
        except Exception:
            return None

    fetched = False
    quota_data = None
    plan_name = "Google AI Pro"
    tier_id = "g1-pro-tier"

    if ls_address:
        try:
            url_quota = f"http://{ls_address}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
            req_quota = urllib.request.Request(url_quota, data=b"{}", headers={
                "Content-Type": "application/json",
                "x-codeium-csrf-token": csrf_token
            })
            with urllib.request.urlopen(req_quota, timeout=1.5) as resp:
                quota_data = json.loads(resp.read().decode())
                fetched = True

            try:
                url_tier = f"http://{ls_address}/exa.language_server_pb.LanguageServerService/GetLoadCodeAssist"
                req_tier = urllib.request.Request(url_tier, data=b"{}", headers={
                    "Content-Type": "application/json",
                    "x-codeium-csrf-token": csrf_token
                })
                with urllib.request.urlopen(req_tier, timeout=1.0) as resp:
                    tier_data = json.loads(resp.read().decode())
                    resp_tier = tier_data.get("response", {})
                    paid = resp_tier.get("paidTier", {})
                    if paid.get("name"):
                        plan_name = paid.get("name")
                    tier_id = paid.get("id", tier_id)
            except Exception:
                pass
        except Exception:
            pass

    # Update cache or load from cache
    now = dt.datetime.now(dt.timezone.utc)
    if fetched and quota_data:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({
                    "quota_data": quota_data,
                    "plan_name": plan_name,
                    "tier_id": tier_id,
                    "cached_at": now.isoformat()
                }, f, indent=2)
        except Exception:
            pass
    elif cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_obj = json.load(f)
                quota_data = cached_obj.get("quota_data")
                plan_name = cached_obj.get("plan_name", plan_name)
                tier_id = cached_obj.get("tier_id", tier_id)
        except Exception:
            pass

    if not quota_data:
        return {
            "five_hour": {"label": "Gemini 5h limit", "used_percent": 0, "left_percent": 100, "reset_at": None, "reset_str": None, "is_exhausted": False, "description": None},
            "weekly": {"label": "Gemini Weekly limit", "used_percent": 0, "left_percent": 100, "reset_at": None, "reset_str": None, "is_exhausted": False, "description": None},
            "claude_gpt_5h": {"label": "Claude & GPT 5h limit", "used_percent": 0, "left_percent": 100, "reset_at": None, "reset_str": None, "is_exhausted": False},
            "claude_gpt_weekly": {"label": "Claude & GPT Weekly limit", "used_percent": 0, "left_percent": 100, "reset_at": None, "reset_str": None, "is_exhausted": False},
            "plan_name": plan_name,
            "tier_id": tier_id,
            "updated_at": int(now.timestamp()),
        }

    groups = quota_data.get("response", {}).get("groups", [])
    gemini_group = next((g for g in groups if "gemini" in g.get("displayName", "").lower()), {})
    claude_gpt_group = next((g for g in groups if "claude" in g.get("displayName", "").lower() or "gpt" in g.get("displayName", "").lower()), {})

    def parse_bucket(bucket_list: list, window: str, label_fallback: str) -> dict:
        b = next((x for x in bucket_list if x.get("window") == window), None)
        if not b:
            return {"label": label_fallback, "used_percent": 0, "left_percent": 100, "reset_at": None, "reset_str": None, "is_exhausted": False, "description": None}
        
        rem_frac = float(b.get("remainingFraction", 1.0))
        pct_left = max(0, min(100, int(round(rem_frac * 100))))
        r_iso = b.get("resetTime")

        # Check if reset has already passed
        if r_iso:
            try:
                r_dt = dt.datetime.fromisoformat(r_iso.replace("Z", "+00:00"))
                if now >= r_dt:
                    pct_left = 100
            except Exception:
                pass

        pct_used = max(0, 100 - pct_left)
        reset_str = fmt_iso_time(r_iso) if window == "5h" else fmt_iso_date(r_iso)
        
        return {
            "label": b.get("displayName", label_fallback),
            "used_percent": pct_used,
            "left_percent": pct_left,
            "reset_at": iso_to_epoch(r_iso),
            "reset_str": reset_str,
            "is_exhausted": pct_left == 0,
            "description": b.get("description"),
        }

    gemini_buckets = gemini_group.get("buckets", [])
    claude_gpt_buckets = claude_gpt_group.get("buckets", [])

    return {
        "five_hour": parse_bucket(gemini_buckets, "5h", "Gemini 5h limit"),
        "weekly": parse_bucket(gemini_buckets, "weekly", "Gemini Weekly limit"),
        "claude_gpt_5h": parse_bucket(claude_gpt_buckets, "5h", "Claude & GPT 5h limit"),
        "claude_gpt_weekly": parse_bucket(claude_gpt_buckets, "weekly", "Claude & GPT Weekly limit"),
        "plan_name": plan_name,
        "tier_id": tier_id,
        "updated_at": int(now.timestamp()),
    }


def get_all_cli_rate_limits() -> dict:
    from .status_bar_config import load_status_bar_config
    cfg = load_status_bar_config()
    res = {}
    if cfg.enabled_providers.codex:
        res["codex"] = get_codex_rate_limits(cfg.codex_sqlite_path or None)
    if cfg.enabled_providers.claude:
        res["claude"] = get_claude_rate_limits(cfg.claude_json_path or None)
    if cfg.enabled_providers.antigravity:
        res["antigravity"] = get_antigravity_rate_limits()
    return res
