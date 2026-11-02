import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.auth import JWT_ALGORITHM
from app.config import get_settings

SIGNUP = {"email": "a@b.com", "password": "secret12", "name": "Test User"}


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_signup_login_me(client):
    signed_up = client.post("/auth/signup", json=SIGNUP)
    assert signed_up.status_code == 200
    body = signed_up.json()
    assert set(body) == {"token", "user"}
    assert set(body["user"]) == {"id", "email", "name"}
    assert body["user"]["email"] == "a@b.com"

    logged_in = client.post("/auth/login", json={"email": "a@b.com", "password": "secret12"})
    assert logged_in.status_code == 200

    me = client.get("/auth/me", headers=_bearer(logged_in.json()["token"]))
    assert me.status_code == 200
    assert me.json() == body["user"]


def test_token_expires_in_seven_days(client):
    token = client.post("/auth/signup", json=SIGNUP).json()["token"]
    claims = jwt.decode(token, get_settings().jwt_secret, algorithms=[JWT_ALGORITHM])
    assert claims["exp"] - claims["iat"] == 7 * 24 * 3600


def test_wrong_password_and_unknown_email_give_same_401(client):
    client.post("/auth/signup", json=SIGNUP)
    wrong = client.post("/auth/login", json={"email": "a@b.com", "password": "not-the-password"})
    unknown = client.post("/auth/login", json={"email": "nobody@b.com", "password": "secret12"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_password_is_not_stored_in_plain_text(client, test_engine):
    from sqlalchemy import text

    client.post("/auth/signup", json=SIGNUP)
    with test_engine.connect() as conn:
        stored = conn.execute(text("SELECT password_hash FROM users")).scalar_one()
    assert stored.startswith("$argon2") and "secret12" not in stored


def test_duplicate_email_is_409_ignoring_case(client):
    assert client.post("/auth/signup", json=SIGNUP).status_code == 200
    assert client.post("/auth/signup", json={**SIGNUP, "email": "A@B.com"}).status_code == 409
    assert client.post("/auth/login", json={"email": "A@B.COM", "password": "secret12"}).status_code == 200


def test_short_password_is_422(client):
    assert client.post("/auth/signup", json={**SIGNUP, "password": "short"}).status_code == 422


def test_me_rejects_bad_tokens(client):
    user_id = client.post("/auth/signup", json=SIGNUP).json()["user"]["id"]
    now = datetime.now(timezone.utc)
    secret = get_settings().jwt_secret
    expired = jwt.encode({"sub": user_id, "exp": now - timedelta(seconds=1)}, secret, algorithm=JWT_ALGORITHM)
    other_key = jwt.encode(
        {"sub": user_id, "exp": now + timedelta(days=1)}, "another-secret-that-is-long-enough!!", algorithm=JWT_ALGORITHM
    )
    no_such_user = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": now + timedelta(days=1)}, secret, algorithm=JWT_ALGORITHM
    )

    assert client.get("/auth/me").status_code == 401
    for token in ["garbage", expired, other_key, no_such_user]:
        assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_empty_jwt_secret_refuses_tokens(client, monkeypatch):
    token = client.post("/auth/signup", json=SIGNUP).json()["token"]
    monkeypatch.setattr(get_settings(), "jwt_secret", "")
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 503
    assert client.post("/auth/login", json={"email": "a@b.com", "password": "secret12"}).status_code == 503
