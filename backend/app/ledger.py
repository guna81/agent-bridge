from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, update

from .db import session_scope
from .models import Ledger, TopUp, User, as_utc, iso_utc, utcnow


def balance(user_id: int) -> float:
    with session_scope() as s:
        u = s.get(User, user_id)
        return u.credits_usd if u else 0.0


def key_spent(key_id: int) -> float:
    """Lifetime spend of one API key (drives per-key budgets)."""
    with session_scope() as s:
        return float(s.scalar(select(func.coalesce(func.sum(Ledger.cost_usd), 0.0)).where(Ledger.key_id == key_id)) or 0.0)


def keys_spent() -> dict[int, float]:
    with session_scope() as s:
        rows = s.execute(select(Ledger.key_id, func.sum(Ledger.cost_usd)).where(Ledger.key_id.is_not(None)).group_by(Ledger.key_id))
        return {int(k): float(v or 0.0) for k, v in rows}


def record(*, user_id: int | None, request_id: str, provider: str, model: str, input_tokens: int, output_tokens: int,
           cost_usd: float, estimated: bool, status: str, key_id: int | None = None) -> None:  # fmt: skip
    """Append a ledger row and decrement the user's balance in the same transaction.

    user_id=None is an admin test run: it is logged for visibility but nobody is charged.
    """
    with session_scope() as s:
        s.add(Ledger(request_id=request_id, user_id=user_id, key_id=key_id, provider=provider, model=model,
                     input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
                     estimated=estimated, status=status))  # fmt: skip
        if cost_usd and user_id is not None:
            s.execute(update(User).where(User.id == user_id).values(credits_usd=User.credits_usd - cost_usd))


def top_up(user_id: int, amount_usd: float, note: str = "") -> float:
    with session_scope() as s:
        s.add(TopUp(user_id=user_id, amount_usd=amount_usd, note=note))
        s.execute(update(User).where(User.id == user_id).values(credits_usd=User.credits_usd + amount_usd))
        s.flush()
        return s.get(User, user_id).credits_usd


def usage_summary(user_id: int) -> dict:
    with session_scope() as s:
        row = s.execute(
            select(func.count(Ledger.id), func.coalesce(func.sum(Ledger.input_tokens), 0),
                   func.coalesce(func.sum(Ledger.output_tokens), 0), func.coalesce(func.sum(Ledger.cost_usd), 0.0))
            .where(Ledger.user_id == user_id)
        ).one()  # fmt: skip
        u = s.get(User, user_id)
        return {"requests": row[0], "input_tokens": int(row[1]), "output_tokens": int(row[2]),
                "spent_usd": float(row[3]), "credits_usd": u.credits_usd if u else 0.0}  # fmt: skip


def recent(user_id: int | None, limit: int = 100) -> list[dict]:
    with session_scope() as s:
        q = select(Ledger).order_by(Ledger.id.desc()).limit(limit)
        if user_id is not None:
            q = q.where(Ledger.user_id == user_id)
        return [
            {"id": r.id, "request_id": r.request_id, "user_id": r.user_id, "key_id": r.key_id, "provider": r.provider,
             "model": r.model, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "cost_usd": r.cost_usd,
             "estimated": r.estimated, "status": r.status, "created_at": iso_utc(r.created_at)}
            for r in s.scalars(q)
        ]  # fmt: skip


def daily_usage(days: int = 14) -> list[dict]:
    """Per-day totals for the last `days` days (UTC), oldest first, with a per-provider cost split.

    Aggregated in Python so it behaves the same on SQLite and Postgres. Admin test runs are excluded.
    """
    today = utcnow().date()
    start = today - dt.timedelta(days=days - 1)
    cutoff = dt.datetime.combine(start, dt.time.min, tzinfo=dt.timezone.utc)
    out = {
        start + dt.timedelta(days=i): {"date": (start + dt.timedelta(days=i)).isoformat(), "requests": 0, "input_tokens": 0,
                                       "output_tokens": 0, "cost_usd": 0.0, "by_provider": {}}
        for i in range(days)
    }  # fmt: skip
    with session_scope() as s:
        q = select(Ledger.created_at, Ledger.provider, Ledger.input_tokens, Ledger.output_tokens, Ledger.cost_usd).where(
            Ledger.created_at >= cutoff, Ledger.user_id.is_not(None)
        )
        for created, provider, tin, tout, cost in s.execute(q):
            d = out.get(as_utc(created).date())
            if d is None:
                continue
            d["requests"] += 1
            d["input_tokens"] += tin
            d["output_tokens"] += tout
            d["cost_usd"] += cost
            d["by_provider"][provider] = d["by_provider"].get(provider, 0.0) + cost
    return list(out.values())


def provider_usage_stats() -> dict:
    """Returns today, 7-day, and lifetime usage broken down by provider, plus credit totals."""
    today = utcnow().date()
    start_today = dt.datetime.combine(today, dt.time.min, tzinfo=dt.timezone.utc)
    start_7d = start_today - dt.timedelta(days=6)

    providers_stats: dict[str, dict] = {}
    totals = {
        "today_cost_usd": 0.0,
        "today_requests": 0,
        "seven_days_cost_usd": 0.0,
        "seven_days_requests": 0,
        "lifetime_cost_usd": 0.0,
        "lifetime_requests": 0,
    }

    with session_scope() as s:
        lifetime_q = select(
            Ledger.provider,
            func.count(Ledger.id),
            func.coalesce(func.sum(Ledger.cost_usd), 0.0),
            func.coalesce(func.sum(Ledger.input_tokens), 0),
            func.coalesce(func.sum(Ledger.output_tokens), 0),
        ).where(Ledger.user_id.is_not(None)).group_by(Ledger.provider)

        for prov, reqs, cost, tin, tout in s.execute(lifetime_q):
            providers_stats[prov] = {
                "lifetime_cost_usd": float(cost),
                "lifetime_requests": int(reqs),
                "lifetime_input_tokens": int(tin),
                "lifetime_output_tokens": int(tout),
                "today_cost_usd": 0.0,
                "today_requests": 0,
                "seven_days_cost_usd": 0.0,
                "seven_days_requests": 0,
            }
            totals["lifetime_cost_usd"] += float(cost)
            totals["lifetime_requests"] += int(reqs)

        q = select(Ledger.created_at, Ledger.provider, Ledger.cost_usd).where(
            Ledger.created_at >= start_7d, Ledger.user_id.is_not(None)
        )
        for created, provider, cost in s.execute(q):
            c_utc = as_utc(created)
            if provider not in providers_stats:
                providers_stats[provider] = {
                    "lifetime_cost_usd": 0.0,
                    "lifetime_requests": 0,
                    "lifetime_input_tokens": 0,
                    "lifetime_output_tokens": 0,
                    "today_cost_usd": 0.0,
                    "today_requests": 0,
                    "seven_days_cost_usd": 0.0,
                    "seven_days_requests": 0,
                }
            cost_f = float(cost or 0.0)
            providers_stats[provider]["seven_days_cost_usd"] += cost_f
            providers_stats[provider]["seven_days_requests"] += 1
            totals["seven_days_cost_usd"] += cost_f
            totals["seven_days_requests"] += 1

            if c_utc.date() == today:
                providers_stats[provider]["today_cost_usd"] += cost_f
                providers_stats[provider]["today_requests"] += 1
                totals["today_cost_usd"] += cost_f
                totals["today_requests"] += 1

        total_credits = float(s.scalar(select(func.coalesce(func.sum(User.credits_usd), 0.0))) or 0.0)

    return {
        "by_provider": providers_stats,
        "totals": totals,
        "credits_remaining_usd": total_credits,
    }

