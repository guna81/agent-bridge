from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, update

from .db import session_scope
from .models import ApiKey, Ledger, Reservation, TopUp, User, as_utc, iso_utc, utcnow
from .errors import ProxyError


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


def period_start(period: str) -> dt.datetime:
    now = utcnow()
    day = now.date() if period == "daily" else now.date().replace(day=1)
    return dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc)


def key_period_spent(key_id: int, period: str) -> float:
    with session_scope() as s:
        return float(s.scalar(select(func.coalesce(func.sum(Ledger.cost_usd), 0.0)).where(
            Ledger.key_id == key_id, Ledger.created_at >= period_start(period))) or 0.0)


def reserve(user_id: int, key_id: int | None, request_id: str, maximum: float) -> float:
    """Reserve available funds while holding the user's database write lock.

    Reservations survive process crashes, so they fail closed until an administrator
    reconciles them. The user-row update serializes reservations across instances.
    """
    with session_scope() as s:
        s.execute(update(User).where(User.id == user_id).values(credits_usd=User.credits_usd))
        user = s.get(User, user_id)
        if not user or user.credits_usd <= 0:
            raise ProxyError(429, "You have no available credits.", "insufficient_quota", "insufficient_quota")
        amount = min(maximum, user.credits_usd)
        if key_id is not None:
            key = s.get(ApiKey, key_id)
            if key is None or key.revoked:
                raise ProxyError(401, "API key is no longer valid.", "authentication_error", "invalid_api_key")
            held = s.scalar(select(func.coalesce(func.sum(Reservation.amount_usd), 0.0)).where(Reservation.key_id == key_id)) or 0.0
            for period, cap in ((None, key.budget_usd), ("daily", key.daily_budget_usd), ("monthly", key.monthly_budget_usd)):
                if cap is None:
                    continue
                q = select(func.coalesce(func.sum(Ledger.cost_usd), 0.0)).where(Ledger.key_id == key_id)
                if period:
                    q = q.where(Ledger.created_at >= period_start(period))
                spent = s.scalar(q) or 0.0
                amount = min(amount, cap - spent - held)
                if amount <= 0:
                    raise ProxyError(429, f"This API key has no available {period or 'lifetime'} budget.", "insufficient_quota", "key_budget_exhausted")
        if amount <= 0:
            raise ProxyError(429, "No budget is available for this request.", "insufficient_quota", "insufficient_quota")
        user.credits_usd -= amount
        s.add(Reservation(request_id=request_id, user_id=user_id, key_id=key_id, amount_usd=amount))
        return amount


def release_reservation(request_id: str) -> bool:
    """Release an orphaned reservation after the operator has verified the run stopped."""
    with session_scope() as s:
        reservation = s.get(Reservation, request_id)
        if not reservation:
            return False
        # Use the same lock order as reserve().
        s.execute(update(User).where(User.id == reservation.user_id).values(credits_usd=User.credits_usd))
        reservation = s.get(Reservation, request_id, populate_existing=True)
        if not reservation:
            return False
        s.execute(update(User).where(User.id == reservation.user_id).values(credits_usd=User.credits_usd + reservation.amount_usd))
        s.delete(reservation)
        return True


def record(*, user_id: int | None, request_id: str, provider: str, model: str, input_tokens: int, output_tokens: int,
           cost_usd: float, estimated: bool, status: str, key_id: int | None = None,
           duration_ms: int | None = None, error_code: str | None = None, pricing_model: str | None = None,
           input_rate: float | None = None, output_rate: float | None = None) -> None:  # fmt: skip
    """Append a ledger row and decrement the user's balance in the same transaction.

    user_id=None is an admin test run: it is logged for visibility but nobody is charged.
    """
    with session_scope() as s:
        s.add(Ledger(request_id=request_id, user_id=user_id, key_id=key_id, provider=provider, model=model,
                     input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
                     estimated=estimated, status=status, duration_ms=duration_ms, error_code=error_code,
                     pricing_model=pricing_model, input_rate=input_rate, output_rate=output_rate))  # fmt: skip
        if user_id is not None:
            s.execute(update(User).where(User.id == user_id).values(credits_usd=User.credits_usd))
        reservation = s.get(Reservation, request_id)
        if user_id is not None:
            held = reservation.amount_usd if reservation else 0.0
            s.execute(update(User).where(User.id == user_id).values(credits_usd=User.credits_usd + held - cost_usd))
        if reservation:
            s.delete(reservation)


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


def recent(user_id: int | None, limit: int = 100, *, key_id: int | None = None,
           provider: str | None = None, model: str | None = None,
           start: dt.datetime | None = None, end: dt.datetime | None = None,
           before_id: int | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(Ledger).order_by(Ledger.id.desc()).limit(limit)
        if user_id is not None:
            q = q.where(Ledger.user_id == user_id)
        if key_id is not None:
            q = q.where(Ledger.key_id == key_id)
        if provider:
            q = q.where(Ledger.provider == provider)
        if model:
            q = q.where(Ledger.model == model)
        if start:
            q = q.where(Ledger.created_at >= start)
        if end:
            q = q.where(Ledger.created_at < end)
        if before_id is not None:
            q = q.where(Ledger.id < before_id)
        return [
            {"id": r.id, "request_id": r.request_id, "user_id": r.user_id, "key_id": r.key_id, "provider": r.provider,
             "model": r.model, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "cost_usd": r.cost_usd,
             "estimated": r.estimated, "status": r.status, "duration_ms": r.duration_ms, "error_code": r.error_code,
             "pricing_model": r.pricing_model, "input_rate": r.input_rate, "output_rate": r.output_rate,
             "created_at": iso_utc(r.created_at)}
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

