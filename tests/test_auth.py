async def test_register_returns_user_without_password(client):
    response = await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "longenough", "full_name": "A B"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "a@example.com"
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_rejects_duplicate_email(client):
    payload = {"email": "dup@example.com", "password": "longenough", "full_name": "A B"}
    await client.post("/auth/register", json=payload)
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 409


async def test_login_returns_token_for_correct_credentials(client):
    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "longenough", "full_name": "A B"},
    )
    response = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "longenough"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_rejects_wrong_password(client):
    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "longenough", "full_name": "A B"},
    )
    response = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "wrong-pass"}
    )
    assert response.status_code == 401


async def test_me_returns_current_user_with_valid_token(client):
    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "longenough", "full_name": "A B"},
    )
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
