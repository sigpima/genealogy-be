import pytest

from tests.test_roles_auth import PASSWORD, login, register, set_setting, set_user


@pytest.fixture
async def admin(client):
    await register(client, "admin@example.com", "Admin")
    await login(client, "admin@example.com")
    return client


@pytest.fixture
async def member(admin, make_client, session):
    """An active, logged-in non-admin."""
    other = make_client()
    await register(other, "member@example.com", "Member")
    await set_user(session, "member@example.com", status="active")
    await login(other, "member@example.com")
    return other


@pytest.fixture
def guest(make_client):
    return make_client()


async def make_member_record(admin, name="Root", parent_id=None, **extra):
    response = await admin.post("/members", json={"full_name": name, "parent_id": parent_id, **extra})
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------------------------------------------------------------- /admin/users


async def test_admin_endpoints_need_an_admin(admin, member, guest):
    assert (await guest.get("/admin/users")).status_code == 401
    assert (await member.get("/admin/users")).status_code == 403
    assert (await member.get("/admin/settings")).status_code == 403
    assert (await member.put("/admin/settings", json={"visibility": "public", "registration": "open"})).status_code == 403
    assert (await admin.get("/admin/users")).status_code == 200


async def test_admin_lists_users_with_role_and_status_but_no_password(admin, member):
    users = (await admin.get("/admin/users")).json()
    assert [(u["email"], u["role"], u["status"]) for u in users] == [
        ("admin@example.com", "admin", "active"),
        ("member@example.com", "member", "active"),
    ]
    assert all("password" not in key for u in users for key in u)


async def test_admin_approves_a_pending_account_and_it_can_then_log_in(admin, make_client):
    stranger = make_client()
    await register(stranger, "stranger@example.com")
    assert (await login(stranger, "stranger@example.com")).status_code == 403

    pending = next(u for u in (await admin.get("/admin/users")).json() if u["email"] == "stranger@example.com")
    assert pending["status"] == "pending"
    response = await admin.patch(f"/admin/users/{pending['id']}", json={"status": "active"})
    assert response.status_code == 200 and response.json()["status"] == "active"
    assert (await login(stranger, "stranger@example.com")).status_code == 200


async def test_admin_can_change_a_role_and_disable_a_user(admin, member):
    users = (await admin.get("/admin/users")).json()
    target = next(u for u in users if u["email"] == "member@example.com")
    assert (await admin.patch(f"/admin/users/{target['id']}", json={"role": "admin"})).json()["role"] == "admin"
    assert (await admin.patch(f"/admin/users/{target['id']}", json={"status": "disabled"})).json()["status"] == "disabled"
    assert (await member.get("/auth/me")).status_code == 403  # their old cookie stopped working


async def test_patch_rejects_unknown_values_and_unknown_users(admin):
    me = (await admin.get("/auth/me")).json()
    assert (await admin.patch(f"/admin/users/{me['id']}", json={"role": "superuser"})).status_code == 422
    assert (await admin.patch(f"/admin/users/{me['id']}", json={"status": "banned"})).status_code == 422
    assert (await admin.patch("/admin/users/9999", json={"status": "active"})).status_code == 404


async def test_the_last_active_admin_cannot_be_demoted_or_disabled(admin):
    me = (await admin.get("/auth/me")).json()
    assert (await admin.patch(f"/admin/users/{me['id']}", json={"role": "member"})).status_code == 409
    assert (await admin.patch(f"/admin/users/{me['id']}", json={"status": "disabled"})).status_code == 409
    assert (await admin.get("/auth/me")).json()["role"] == "admin"


async def test_an_admin_can_step_down_once_another_admin_exists(admin, member):
    target = next(u for u in (await admin.get("/admin/users")).json() if u["email"] == "member@example.com")
    await admin.patch(f"/admin/users/{target['id']}", json={"role": "admin"})
    me = (await admin.get("/auth/me")).json()
    assert (await admin.patch(f"/admin/users/{me['id']}", json={"role": "member"})).status_code == 200


async def test_admin_creates_an_active_user_directly(admin, make_client):
    created = await admin.post(
        "/admin/users",
        json={"email": "cousin@example.com", "full_name": "Cousin", "password": PASSWORD, "role": "member"},
    )
    assert created.status_code == 201
    assert (created.json()["role"], created.json()["status"]) == ("member", "active")
    cousin = make_client()
    assert (await login(cousin, "cousin@example.com")).status_code == 200


async def test_admin_create_user_validates_input(admin):
    base = {"email": "x@example.com", "full_name": "X", "password": PASSWORD}
    assert (await admin.post("/admin/users", json={**base, "password": "short"})).status_code == 422
    assert (await admin.post("/admin/users", json={**base, "role": "root"})).status_code == 422
    assert (await admin.post("/admin/users", json={**base, "email": "admin@example.com"})).status_code == 409


async def test_creating_users_works_even_when_registration_is_closed(admin, session):
    await set_setting(session, "registration", "closed")
    response = await admin.post(
        "/admin/users", json={"email": "invited@example.com", "full_name": "I", "password": PASSWORD}
    )
    assert response.status_code == 201


# ------------------------------------------------------------ settings + site


async def test_settings_default_and_update(admin):
    assert (await admin.get("/admin/settings")).json() == {"visibility": "private", "registration": "approval"}
    updated = await admin.put("/admin/settings", json={"visibility": "public", "registration": "closed"})
    assert updated.status_code == 200
    assert (await admin.get("/admin/settings")).json() == {"visibility": "public", "registration": "closed"}
    # updating again must overwrite, not duplicate
    await admin.put("/admin/settings", json={"visibility": "private", "registration": "open"})
    assert (await admin.get("/admin/settings")).json() == {"visibility": "private", "registration": "open"}


async def test_settings_reject_unknown_values(admin):
    assert (await admin.put("/admin/settings", json={"visibility": "secret", "registration": "open"})).status_code == 422
    assert (await admin.put("/admin/settings", json={"visibility": "private", "registration": "whatever"})).status_code == 422


async def test_site_info_is_public_and_reflects_settings(admin, guest):
    assert (await guest.get("/site/info")).json() == {"visibility": "private", "registration": "approval"}
    await admin.put("/admin/settings", json={"visibility": "public", "registration": "closed"})
    assert (await guest.get("/site/info")).json() == {"visibility": "public", "registration": "closed"}


# ------------------------------------------------------------------ members


async def test_members_can_read_but_not_write(admin, member):
    root = await make_member_record(admin, "Root")
    assert (await member.get("/members/tree")).status_code == 200
    assert (await member.get(f"/members/{root}")).status_code == 200

    assert (await member.post("/members", json={"full_name": "X", "parent_id": root})).status_code == 403
    assert (await member.put(f"/members/{root}", json={"full_name": "Hacked"})).status_code == 403
    assert (await member.delete(f"/members/{root}")).status_code == 403
    assert (await member.post(f"/members/{root}/marriages", json={"spouse_full_name": "S"})).status_code == 403
    assert (await member.post(f"/members/{root}/avatar", files={"file": ("a.png", b"x", "image/png")})).status_code == 403
    assert (await member.delete(f"/members/{root}/avatar")).status_code == 403
    assert (await member.put("/members/marriages/1", json={"spouse_full_name": "S"})).status_code == 403
    assert (await admin.get(f"/members/{root}")).json() is not None  # nothing was changed
    assert (await admin.get("/members/tree")).json()["name"] == "Root"


async def test_private_site_refuses_guests_entirely(admin, guest):
    root = await make_member_record(admin, "Root")
    assert (await guest.get("/members/tree")).status_code == 401
    assert (await guest.get(f"/members/{root}")).status_code == 401
    assert (await guest.post("/members", json={"full_name": "X"})).status_code == 401


async def test_public_site_lets_guests_read_but_never_write(admin, guest):
    root = await make_member_record(admin, "Root")
    await admin.put("/admin/settings", json={"visibility": "public", "registration": "approval"})
    assert (await guest.get("/members/tree")).json()["name"] == "Root"
    assert (await guest.get(f"/members/{root}")).status_code == 200
    assert (await guest.post("/members", json={"full_name": "X"})).status_code == 401
    assert (await guest.put(f"/members/{root}", json={"full_name": "H"})).status_code == 401
    assert (await guest.delete(f"/members/{root}")).status_code == 401


async def test_guests_get_a_redacted_detail_while_members_and_admins_see_everything(admin, member, guest):
    root = await make_member_record(
        admin,
        "Root",
        birth_year=1900,
        gender="male",
        notes="private story",
        residence="Hà Tĩnh",
        burial_place="Nghĩa trang",
        burial_latitude=18.5,
        burial_longitude=105.7,
        title="Thủy Tổ",
    )
    await admin.put("/admin/settings", json={"visibility": "public", "registration": "approval"})

    seen_by_guest = (await guest.get(f"/members/{root}")).json()
    assert seen_by_guest["birth_year"] == 1900 and seen_by_guest["title"] == "Thủy Tổ"
    for hidden in ("notes", "residence", "burial_place", "burial_latitude", "burial_longitude"):
        assert seen_by_guest[hidden] is None, hidden

    for person in (member, admin):
        full = (await person.get(f"/members/{root}")).json()
        assert full["notes"] == "private story"
        assert full["residence"] == "Hà Tĩnh"
        assert full["burial_place"] == "Nghĩa trang"
        assert full["burial_latitude"] == 18.5


async def test_a_stale_cookie_does_not_lock_a_guest_out_of_a_public_site(admin, make_client):
    await make_member_record(admin, "Root")
    await admin.put("/admin/settings", json={"visibility": "public", "registration": "approval"})
    visitor = make_client()
    visitor.cookies.set("access_token", "not-a-valid-token")
    assert (await visitor.get("/members/tree")).status_code == 200


async def test_a_disabled_user_is_refused_even_on_a_public_site(admin, member, session):
    await make_member_record(admin, "Root")
    await admin.put("/admin/settings", json={"visibility": "public", "registration": "approval"})
    await set_user(session, "member@example.com", status="disabled")
    assert (await member.get("/members/tree")).status_code == 403
