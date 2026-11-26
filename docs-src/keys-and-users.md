# Keys, users and budgets

Access is controlled with users, API keys and a credit ledger. Manage them under **Keys & users** in the dashboard, or through the [admin API](api.md#admin-api).

## Users and credits

Add a user, then add credits. Requests are charged against the caller's credits. The available balance excludes outstanding reservations.

## API keys

- A key is shown **once** when created. It is stored hashed (HMAC-SHA256 with a pepper).
- Changing `PROXY_KEY_PEPPER` invalidates every issued key.

### Per-key limits

Every key can carry:

| Limit | Meaning |
|---|---|
| Lifetime budget | Total USD the key may spend |
| Daily budget | Resets at UTC midnight |
| Monthly budget | Resets at UTC month boundary |
| Expiry | Expires after N days |
| Model allow-list | Exact IDs or globs, e.g. `claude/haiku`, `codex/*` |

```sh
curl -s http://127.0.0.1:43187/admin/keys \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{
  "user_id": 1, "label": "ci",
  "budget_usd": 2.0, "daily_budget_usd": 0.5, "monthly_budget_usd": 1.5,
  "expires_in_days": 30,
  "allowed_models": ["claude/haiku", "codex/*"]
}'

# null clears a limit; omitted fields are left alone
curl -s -X PATCH http://127.0.0.1:43187/admin/keys/3 \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d '{"budget_usd": null}'
```

| Situation | Response |
|---|---|
| Over budget | `429 key_budget_exhausted` |
| Model not allowed | `403 model_not_allowed` |
| Expired | `401` |

## Limits are admission limits, not hard caps

When a request starts, the gateway **reserves** available credits and key budget, then settles the actual charge on completion. A reservation stops concurrent requests spending the same funds.

These are **not guaranteed hard spending caps**: only the Claude CLI receives a per-run dollar limit, and any backend can report a final cost above its reservation. Direct APIs and the other CLIs don't enforce the dollar limit. Use provider-side spending controls where you need a hard limit.

## Reservations

Reservations stay in the database after an unclean shutdown, so overspend isn't silently allowed. To clear an orphan:

1. Inspect them: `GET /admin/reservations`, or the **Request usage** page.
2. Verify the request has stopped on **every** instance and reconcile any upstream charges.
3. Release it: `DELETE /admin/reservations/{request_id}`, or the guarded action in the dashboard.

!!! danger
    Releasing a reservation for a request that is still active allows overspending.

## Default budget

`PROXY_DEFAULT_MAX_BUDGET_USD` (default `0.50`) sets the default per-request spend limit. See [Configuration](configuration.md).
