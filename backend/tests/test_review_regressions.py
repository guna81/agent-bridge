import base64
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import ledger
from app.api.openai import ChatRequest, normalize
from app.errors import ProxyError
from app.pricing import estimate_cost


def test_reservations_are_atomic_and_settle(live):
    user_id, _ = live.new_user("reservation-regression", credits=1.0)
    key = live.admin("POST", "/keys", json={"user_id": user_id, "budget_usd": 0.6})

    def reserve(i):
        try:
            return ledger.reserve(user_id, key["id"], f"reservation-test-{i}", 0.5)
        except ProxyError:
            return 0.0

    with ThreadPoolExecutor(max_workers=2) as pool:
        amounts = list(pool.map(reserve, range(2)))
    assert sum(amounts) == pytest.approx(0.6)
    for i, amount in enumerate(amounts):
        if amount:
            ledger.record(user_id=user_id, key_id=key["id"], request_id=f"reservation-test-{i}", provider="test", model="test",
                          input_tokens=0, output_tokens=0, cost_usd=0.02, estimated=True, status="ok")
    assert ledger.balance(user_id) == pytest.approx(1.0 - 0.02 * sum(amount > 0 for amount in amounts))
    assert not [r for r in live.admin("GET", "/reservations") if r["user_id"] == user_id]


def test_orphan_reservation_can_be_released(live):
    user_id, _ = live.new_user("reservation-release", credits=1.0)
    ledger.reserve(user_id, None, "orphan-test", 0.3)
    assert ledger.balance(user_id) == pytest.approx(0.7)
    live.admin("DELETE", "/reservations/orphan-test")
    assert ledger.balance(user_id) == pytest.approx(1.0)


def test_earlier_image_is_associated_with_its_turn():
    image = "data:image/png;base64," + base64.b64encode(b"image").decode()
    request = ChatRequest(model="claude/sonnet", messages=[
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image}}]},
        {"role": "assistant", "content": "A picture"}, {"role": "user", "content": "What color?"},
    ])
    normalized = normalize(request, "sonnet")
    assert list(normalized.images_by_turn) == [0]
    assert normalized.images_by_turn[0][0].data == b"image"


def test_configured_model_price():
    assert estimate_cost("real-model", 1_000_000, 1_000_000, {"real-model": [3, 15]}) == 18


def test_ledger_filters_and_cursor(live):
    user_id, _ = live.new_user("usage-filter", credits=5.0)
    key = live.admin("POST", "/keys", json={"user_id": user_id})
    for i, model in enumerate(("alpha", "beta", "alpha")):
        ledger.record(user_id=user_id, key_id=key["id"], request_id=f"filter-{i}", provider="filter-test", model=model,
                      input_tokens=10, output_tokens=2, cost_usd=0.01, estimated=i != 1, status="ok")
    path = f"/ledger?user_id={user_id}&key_id={key['id']}&provider=filter-test&model=alpha&limit=1"
    first = live.admin("GET", path)
    assert len(first) == 1 and first[0]["request_id"] == "filter-2"
    second = live.admin("GET", path + f"&before_id={first[0]['id']}")
    assert len(second) == 1 and second[0]["request_id"] == "filter-0"
    assert live.admin("GET", path + "&start=2099-01-01T00:00:00Z") == []


def test_recurring_budget_reservations(live):
    user_id, _ = live.new_user("recurring-test", credits=5)
    key = live.admin("POST", "/keys", json={"user_id": user_id, "daily_budget_usd": 0.4, "monthly_budget_usd": 1})
    assert ledger.reserve(user_id, key["id"], "daily-1", 0.3) == pytest.approx(0.3)
    assert ledger.reserve(user_id, key["id"], "daily-2", 0.3) == pytest.approx(0.1)
    with pytest.raises(ProxyError, match="daily"):
        ledger.reserve(user_id, key["id"], "daily-3", 0.3)
    ledger.record(user_id=user_id, key_id=key["id"], request_id="daily-1", provider="test", model="test",
                  input_tokens=0, output_tokens=0, cost_usd=0.25, estimated=True, status="ok")
    ledger.release_reservation("daily-2")
    assert ledger.key_period_spent(key["id"], "daily") == pytest.approx(0.25)
    assert ledger.reserve(user_id, key["id"], "daily-4", 0.3) == pytest.approx(0.15)
    ledger.release_reservation("daily-4")


def test_routing_respects_allowlists_and_only_falls_back_before_start(live):
    from app.api.common import resolve_routed_provider
    from app.db import session_scope
    from app.models import ApiKey

    user_id, _ = live.new_user("routing-test", credits=2)
    created = live.admin("POST", "/keys", json={"user_id": user_id, "allowed_models": ["primary/*", "fallback/*"]})
    live.admin("POST", "/providers", json={"name": "primary", "kind": "custom", "enabled": False,
               "default_model": "a", "models": ["a"], "extra": {"fallback_model": "fallback/b"}})
    live.admin("POST", "/providers", json={"name": "fallback", "kind": "custom", "enabled": True,
               "default_model": "b", "models": ["b"]})
    with session_scope() as s:
        key = s.get(ApiKey, created["id"])
        selected, slug, model = resolve_routed_provider(key, "primary/a")
        assert (selected.name, slug, model) == ("fallback", "b", "fallback/b")
        key.allowed_models = ["primary/*"]
        with pytest.raises(ProxyError, match="fallback model"):
            resolve_routed_provider(key, "primary/a")


def test_routing_and_estimate_over_http(live):
    import httpx
    user_id, token = live.new_user("routing-http-test", credits=2)
    live.admin("POST", "/providers", json={"name": "route-source", "kind": "custom", "enabled": False,
               "default_model": "a", "models": ["a"], "extra": {"fallback_model": "route-target/b"}})
    live.admin("POST", "/providers", json={"name": "route-target", "kind": "custom", "enabled": True,
               "binary_path": live.wrappers["text"], "default_model": "b", "models": ["b"],
               "extra": {"args_template": ["{prompt}"], "output_format": "text", "pricing_rates": {"b": [2, 4]}}})
    headers = {"Authorization": f"Bearer {token}"}
    estimate = httpx.get(live.v1 + "/estimate", headers=headers, params={"model": "route-source/a", "input_tokens": 1000000, "output_tokens": 1000000})
    assert estimate.status_code == 200
    assert estimate.json()["model"] == "route-target/b" and estimate.json()["cost_usd"] == 6
    response = httpx.post(live.v1 + "/chat/completions", headers=headers, json={"model": "route-source/a", "messages": [{"role": "user", "content": "hello"}]}, timeout=30)
    assert response.status_code == 200
    assert response.headers["X-Proxy-Model"] == "route-target/b"
    assert response.headers["X-Proxy-Requested-Model"] == "route-source/a"
    assert response.json()["model"] == "route-target/b"
    row = next(r for r in live.admin("GET", f"/ledger?user_id={user_id}") if r["request_id"] == response.headers["X-Request-Id"])
    assert row["duration_ms"] is not None and row["pricing_model"] == "b" and row["input_rate"] == 2


def test_cli_rejects_historical_images(live):
    import httpx
    image = "data:image/png;base64," + base64.b64encode(b"image").decode()
    response = httpx.post(live.v1 + "/chat/completions", headers={"Authorization": f"Bearer {live.key}"}, json={
        "model": "claude/sonnet", "messages": [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image}}]},
            {"role": "assistant", "content": "A picture"}, {"role": "user", "content": "What color?"},
        ]}, timeout=30)
    assert response.status_code == 400 and "direct API" in response.json()["error"]["message"]
