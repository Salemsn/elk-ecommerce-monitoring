"""Authentification, rôles et gestion des comptes (US01, US02, US09 ; RM01 à RM04)."""
from conftest import login


def test_admin_created_at_startup(client):
    r = login(client, "admin@test.tn", "Admin@2026")
    assert r.status_code == 200
    assert r.json["role"] == "admin"


def test_wrong_password_is_rejected(client):
    assert login(client, "admin@test.tn", "mauvais").status_code == 401


def test_api_requires_login(client):
    r = client.get("/api/v1/logs")
    assert r.status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401


def test_web_page_redirects_to_login(client):
    r = client.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_web_login_form(client):
    r = client.post("/login", data={"email": "admin@test.tn", "password": "Admin@2026"})
    assert r.status_code == 302
    assert client.get("/").status_code == 200


def test_login_open_redirect_is_blocked(client):
    r = client.post("/login?next=https://evil.example.com", data={"email": "admin@test.tn", "password": "Admin@2026"})
    assert r.headers["Location"] == "/"


def test_admin_creates_client(admin_client):
    r = admin_client.post("/api/v1/users", json={"email": "Boutique@Test.tn", "password": "Client@2026",
                                                 "full_name": "Boutique Carthage"})
    assert r.status_code == 201
    assert r.json["email"] == "boutique@test.tn"
    assert r.json["role"] == "client"
    assert r.json["allowed_categories"] == ["transaction", "comportement"]
    assert "password_hash" not in r.json


def test_duplicate_email_conflict(admin_client):
    body = {"email": "dup@test.tn", "password": "Client@2026"}
    assert admin_client.post("/api/v1/users", json=body).status_code == 201
    assert admin_client.post("/api/v1/users", json=body).status_code == 409


def test_short_password_rejected(admin_client):
    r = admin_client.post("/api/v1/users", json={"email": "x@test.tn", "password": "court"})
    assert r.status_code == 422


def test_client_cannot_manage_users(client_user):
    assert client_user.get("/api/v1/users").status_code == 403
    assert client_user.get("/api/v1/files").status_code == 403


def test_deactivated_account_cannot_login(admin_client, app):
    r = admin_client.post("/api/v1/users", json={"email": "off@test.tn", "password": "Client@2026"})
    uid = r.json["id"]
    assert admin_client.patch(f"/api/v1/users/{uid}", json={"is_active": False}).json["is_active"] is False
    other = app.test_client()
    assert login(other, "off@test.tn", "Client@2026").status_code == 403


def test_admin_cannot_deactivate_himself(admin_client):
    me = admin_client.get("/api/v1/auth/me").json
    r = admin_client.patch(f"/api/v1/users/{me['id']}", json={"is_active": False})
    assert r.status_code == 400


def test_logout(admin_client):
    assert admin_client.post("/api/v1/auth/logout").status_code == 204
    assert admin_client.get("/api/v1/auth/me").status_code == 401


def test_session_is_stored_in_redis(clients, tmp_path):
    from app import create_app
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "UPLOAD_FOLDER": str(tmp_path),
                      "ADMIN_EMAIL": "admin@test.tn", "ADMIN_PASSWORD": "Admin@2026"}, clients=clients)
    c = app.test_client()
    assert login(c, "admin@test.tn", "Admin@2026").status_code == 200
    assert any(k.startswith(b"session:") for k in clients["redis"].keys())
    assert c.get("/api/v1/auth/me").status_code == 200
