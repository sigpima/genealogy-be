from tests.test_roles_auth import make_user


async def test_login_returns_token_for_correct_credentials(client):
    await make_user(client, "a@example.com", "A B", role="superadmin", password="longenough")
    response = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "longenough"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_rejects_wrong_password(client):
    await make_user(client, "a@example.com", "A B", role="superadmin", password="longenough")
    response = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "wrong-pass"}
    )
    assert response.status_code == 401


async def test_me_returns_current_user_with_valid_token(client):
    await make_user(client, "a@example.com", "A B", role="superadmin", password="longenough")
    login_response = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "longenough"}
    )
    token = login_response.json()["access_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "a@example.com"


async def test_me_rejects_missing_token(client):
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_login_sets_httponly_cookie(client):
    await make_user(client, "cookie@example.com", "A B", role="superadmin", password="longenough")
    response = await client.post(
        "/auth/login", json={"email": "cookie@example.com", "password": "longenough"}
    )
    set_cookie = response.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie
    assert "httponly" in set_cookie.lower()


async def test_me_succeeds_via_cookie_alone(client):
    await make_user(client, "cookie2@example.com", "A B", role="superadmin", password="longenough")
    await client.post(
        "/auth/login", json={"email": "cookie2@example.com", "password": "longenough"}
    )
    # httpx.AsyncClient's cookie jar carries the cookie from the login response automatically.
    response = await client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "cookie2@example.com"


async def test_logout_clears_cookie_and_me_then_requires_header(client):
    await make_user(client, "cookie3@example.com", "A B", role="superadmin", password="longenough")
    await client.post(
        "/auth/login", json={"email": "cookie3@example.com", "password": "longenough"}
    )
    logout_response = await client.post("/auth/logout")
    assert logout_response.status_code == 200

    response = await client.get("/auth/me")
    assert response.status_code == 401
