from sqlalchemy import text

PASSWORD = "longenough"


async def make_user(client, email, name="User", *, role="member", status="active", password=PASSWORD):
    """Create an account straight in the database: there is no self-service registration any more.

    The platform superadmin belongs to no tree; everybody else joins the default tree (made if missing, like a fresh install).
    """
    from app.core.tenants import create_user, get_or_create_default_tree
    from app.db.session import get_db
    from app.main import app

    async for db in app.dependency_overrides[get_db]():
        tree = await get_or_create_default_tree(db)
        return await create_user(
            db, email=email, full_name=name, password=password, role=role, tree=None if role == "superadmin" else tree, status=status
        )


async def login(client, email, password=PASSWORD):
    return await client.post("/auth/login", json={"email": email, "password": password})


async def set_setting(session, key, value, tree_id=None):
    """Set a per-tree site setting; by default on the lowest-id tree (the default tree)."""
    if tree_id is None:
        tree_id = (await session.execute(text("SELECT MIN(id) FROM trees"))).scalar_one()
    await session.execute(
        text(
            "INSERT INTO site_settings (tree_id, key, value) VALUES (:t, :k, :v) "
            "ON CONFLICT (tree_id, key) DO UPDATE SET value = :v"
        ),
        {"t": tree_id, "k": key, "v": value},
    )
    await session.commit()


async def set_user(session, email, **columns):
    assignments = ", ".join(f"{name} = :{name}" for name in columns)
    await session.execute(
        text(f"UPDATE users SET {assignments} WHERE email = :email"), {"email": email, **columns}
    )
    await session.commit()


async def test_pending_user_cannot_log_in(client):
    await make_user(client, "first@example.com", role="superadmin")
    await make_user(client, "second@example.com", status="pending")
    response = await login(client, "second@example.com")
    assert response.status_code == 403
    assert response.json()["detail"] == "account_pending"


async def test_wrong_password_is_still_401_for_a_pending_user(client):
    await make_user(client, "first@example.com", role="superadmin")
    await make_user(client, "second@example.com", status="pending")
    assert (await login(client, "second@example.com", "wrong-password")).status_code == 401


async def test_disabled_user_cannot_log_in(client, session):
    await make_user(client, "first@example.com", role="superadmin")
    await set_user(session, "first@example.com", status="disabled")
    response = await login(client, "first@example.com")
    assert response.status_code == 403
    assert response.json()["detail"] == "account_disabled"


async def test_existing_token_stops_working_the_moment_the_user_is_disabled(client, session):
    await make_user(client, "first@example.com", role="superadmin")
    await login(client, "first@example.com")
    assert (await client.get("/auth/me")).status_code == 200
    await set_user(session, "first@example.com", status="disabled")
    assert (await client.get("/auth/me")).status_code == 403


async def test_me_returns_role_and_status(client):
    await make_user(client, "first@example.com", role="superadmin")
    await login(client, "first@example.com")
    body = (await client.get("/auth/me")).json()
    assert (body["role"], body["status"]) == ("superadmin", "active")
