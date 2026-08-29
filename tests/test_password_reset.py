async def test_forgot_password_existing_user_sends_email(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to_email, reset_url: sent.append({"to_email": to_email, "reset_url": reset_url}),
    )

    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "old-password", "full_name": "A B"},
    )

    response = await client.post("/auth/forgot-password", json={"email": "a@example.com"})
    assert response.status_code == 200
    assert len(sent) == 1
    assert sent[0]["to_email"] == "a@example.com"
    assert "/reset-password?token=" in sent[0]["reset_url"]


async def test_forgot_password_nonexistent_user_does_not_send_email(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email", lambda *args: sent.append(args)
    )

    response = await client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert response.status_code == 200
    assert sent == []


async def test_reset_password_with_valid_token_changes_password(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to_email, reset_url: sent.append(reset_url),
    )

    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "old-password", "full_name": "A B"},
    )
    await client.post("/auth/forgot-password", json={"email": "a@example.com"})
    token = sent[0].split("token=")[1]

    response = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "new-password"}
    )
    assert response.status_code == 204

    old_login = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "old-password"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "new-password"}
    )
    assert new_login.status_code == 200


async def test_reset_password_rejects_unknown_token(client):
    response = await client.post(
        "/auth/reset-password", json={"token": "does-not-exist", "new_password": "new-password"}
    )
    assert response.status_code == 400


async def test_reset_password_rejects_expired_token(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to_email, reset_url: sent.append(reset_url),
    )
    monkeypatch.setattr("app.routers.auth.RESET_TOKEN_EXPIRE_MINUTES", -1)

    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "old-password", "full_name": "A B"},
    )
    await client.post("/auth/forgot-password", json={"email": "a@example.com"})
    token = sent[0].split("token=")[1]

    response = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "new-password"}
    )
    assert response.status_code == 400


async def test_reset_password_rejects_reused_token(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to_email, reset_url: sent.append(reset_url),
    )

    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "old-password", "full_name": "A B"},
    )
    await client.post("/auth/forgot-password", json={"email": "a@example.com"})
    token = sent[0].split("token=")[1]

    first = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "new-password"}
    )
    assert first.status_code == 204

    second = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "another-password"}
    )
    assert second.status_code == 400


async def test_reset_password_rejects_short_password(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to_email, reset_url: sent.append(reset_url),
    )
    await client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "old-password", "full_name": "A B"},
    )
    await client.post("/auth/forgot-password", json={"email": "a@example.com"})
    token = sent[0].split("token=")[1]

    response = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "short"}
    )
    assert response.status_code == 422
