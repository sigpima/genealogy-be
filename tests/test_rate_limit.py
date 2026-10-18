"""GĐ11 operations: rate limiting, the client address and security headers."""

import pytest
from starlette.requests import Request

from app.core.rate_limit import RateLimiter, client_ip, limiter
from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    tree = await create_tree(session, "Họ A", "ho-a")
    await create_user(session, email="admin_a@example.com", full_name="admin_a", password=PASSWORD, role="admin", tree=tree)
    return tree


@pytest.fixture
def on():
    limiter.enabled = True
    limiter.reset()
    yield limiter


def test_the_window_slides_and_reports_when_to_retry():
    now = [100.0]
    local = RateLimiter()
    local.enabled = True
    local._clock = lambda: now[0]
    for _ in range(3):
        local.hit("k", 3, 60)
    with pytest.raises(Exception) as caught:
        local.hit("k", 3, 60)
    assert caught.value.status_code == 429 and caught.value.headers["Retry-After"] == "60"
    now[0] += 61
    local.hit("k", 3, 60)  # the old attempts expired
    local.hit("other", 3, 60)  # keys are independent


def request_with(headers: dict[str, str], host="10.0.0.9") -> Request:
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()], "client": (host, 1234)})


def test_forwarded_for_is_trusted_only_as_far_as_configured(monkeypatch):
    from app.core.config import get_settings

    request = request_with({"X-Forwarded-For": "6.6.6.6, 203.0.113.7"})
    assert client_ip(request) == "10.0.0.9"  # default: trust nothing
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    get_settings.cache_clear()
    assert client_ip(request) == "203.0.113.7"  # the address the one trusted proxy saw; the forged left part is ignored
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    get_settings.cache_clear()
    assert client_ip(request) == "6.6.6.6"
    assert client_ip(request_with({})) == "10.0.0.9"  # fewer entries than hops: fall back to the socket


async def test_repeated_failed_logins_for_one_account_are_blocked_from_any_address(world, make_client, on):
    for i in range(8):
        c = make_client()
        c.headers["X-Forwarded-For"] = f"1.1.1.{i}"
        assert (await c.post("/auth/login", json={"email": "admin_a@example.com", "password": "wrong-password"})).status_code == 401
    r = await make_client().post("/auth/login", json={"email": "admin_a@example.com", "password": PASSWORD})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1  # even the right password waits


async def test_successful_logins_do_not_lock_the_owner_out(world, make_client, on):
    for _ in range(12):
        assert (await login(make_client(), "admin_a@example.com")).status_code == 200  # 12 > the per-account failure limit, < per-IP 20


async def test_one_address_is_slowed_down_whatever_the_account(world, make_client, on, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")  # a trusted proxy tells us the real address, so the full limit applies
    get_settings.cache_clear()
    c = make_client()
    c.headers["X-Forwarded-For"] = "203.0.113.50"
    codes = [(await c.post("/auth/login", json={"email": f"nobody{i}@example.com", "password": "x" * 9})).status_code for i in range(22)]
    assert codes[:20] == [401] * 20 and codes[20:] == [429, 429]
    other = make_client()
    other.headers["X-Forwarded-For"] = "203.0.113.51"
    assert (await other.post("/auth/login", json={"email": "nobody@example.com", "password": "x" * 9})).status_code == 401


async def test_without_a_trusted_proxy_the_shared_address_gets_a_looser_limit(world, make_client, on):
    c = make_client()
    codes = [(await c.post("/auth/login", json={"email": f"nobody{i}@example.com", "password": "x" * 9})).status_code for i in range(102)]
    assert codes[:100] == [401] * 100 and codes[100:] == [429, 429]


async def test_forgot_password_is_limited_per_address(world, make_client, on, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    get_settings.cache_clear()
    c = make_client()
    c.headers["X-Forwarded-For"] = "203.0.113.60"
    c.cookies.set("tree_slug", "ho-a")
    codes = [(await c.post("/auth/forgot-password", json={"email": "x@example.com"})).status_code for i in range(6)]
    assert codes[-1] == 429 and codes[:5] == [200] * 5


async def test_nothing_is_limited_when_switched_off(world, make_client):
    c = make_client()
    codes = {(await c.post("/auth/login", json={"email": "a@example.com", "password": "x" * 9})).status_code for _ in range(25)}
    assert codes == {401}


async def test_security_headers_on_every_response(world, make_client):
    r = await make_client().get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    r = await make_client().get("/members/tree")  # an error response gets them too
    assert r.status_code == 401 and r.headers["x-content-type-options"] == "nosniff"


async def test_public_rsvp_answers_are_limited_per_address(world, make_client, on, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    get_settings.cache_clear()
    admin = make_client()
    assert (await login(admin, "admin_a@example.com")).status_code == 200
    event = (await admin.post("/events", json={"title": "Giỗ", "kind": "memorial", "calendar": "solar", "month": 12, "day": 20, "year": 2024})).json()
    card = (await admin.post(f"/events/{event['id']}/cards", json={"date": "2024-12-20"})).json()
    guest = make_client()
    guest.headers["X-Forwarded-For"] = "203.0.113.70"
    codes = [(await guest.post(f"/invitations/{card['token']}/respond", json={"name": f"Khách {i}", "response": "yes"})).status_code for i in range(41)]
    assert codes[:40].count(429) == 0 and codes[40] == 429
