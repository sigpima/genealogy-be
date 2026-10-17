from sqlalchemy import text

PASSWORD = "longenough"


async def register(client, email, name="User"):
    return await client.post(
        "/auth/register", json={"email": email, "password": PASSWORD, "full_name": name}
    )


async def login(client, email, password=PASSWORD):
    return await client.post("/auth/login", json={"email": email, "password": password})


async def set_setting(session, key, value):
    await session.execute(
        text(
            "INSERT INTO site_settings (key, value) VALUES (:k, :v) "
            "ON CONFLICT (key) DO UPDATE SET value = :v"
        ),
        {"k": key, "v": value},
    )
    await session.commit()


async def set_user(session, email, **columns):
    assignments = ", ".join(f"{name} = :{name}" for name in columns)
    await session.execute(
        text(f"UPDATE users SET {assignments} WHERE email = :email"), {"email": email, **columns}
    )
    await session.commit()


async def test_first_registered_user_becomes_active_admin(client):
    response = await register(client, "first@example.com")
    assert response.status_code == 201
    assert response.json()["role"] == "admin"
    assert response.json()["status"] == "active"


async def test_later_registrations_wait_for_approval_by_default(client):
    await register(client, "first@example.com")
    response = await register(client, "second@example.com")
    assert response.status_code == 201
    assert response.json()["role"] == "member"
    assert response.json()["status"] == "pending"


async def test_registration_open_activates_new_members_at_once(client, session):
    await register(client, "first@example.com")
    await set_setting(session, "registration", "open")
    response = await register(client, "second@example.com")
    assert (response.json()["role"], response.json()["status"]) == ("member", "active")


async def test_registration_closed_is_refused_but_the_very_first_user_can_still_bootstrap(client, session):
    await set_setting(session, "registration", "closed")
    assert (await register(client, "first@example.com")).status_code == 201
    refused = await register(client, "second@example.com")
    assert refused.status_code == 403


async def test_pending_user_cannot_log_in(client):
    await register(client, "first@example.com")
    await register(client, "second@example.com")
    response = await login(client, "second@example.com")
    assert response.status_code == 403
    assert response.json()["detail"] == "account_pending"


async def test_wrong_password_is_still_401_for_a_pending_user(client):
    await register(client, "first@example.com")
    await register(client, "second@example.com")
    assert (await login(client, "second@example.com", "wrong-password")).status_code == 401


async def test_disabled_user_cannot_log_in(client, session):
    await register(client, "first@example.com")
    await set_user(session, "first@example.com", status="disabled")
    response = await login(client, "first@example.com")
    assert response.status_code == 403
    assert response.json()["detail"] == "account_disabled"


async def test_existing_token_stops_working_the_moment_the_user_is_disabled(client, session):
    await register(client, "first@example.com")
    await login(client, "first@example.com")
    assert (await client.get("/auth/me")).status_code == 200
    await set_user(session, "first@example.com", status="disabled")
    assert (await client.get("/auth/me")).status_code == 403


async def test_me_returns_role_and_status(client):
    await register(client, "first@example.com")
    await login(client, "first@example.com")
    body = (await client.get("/auth/me")).json()
    assert (body["role"], body["status"]) == ("admin", "active")
