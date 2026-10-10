import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from agent.cache import PolicyCache
from agent.simulator import Simulator
from server.app.models import Device, EnrollmentCode, ParentSession
from tests.conftest import pair, sign_in


def test_login_cookie_and_logout(parent):
    assert parent.get("/api/auth/me").status_code == 200
    cookie = parent.cookies["ogk_session"]
    assert parent.post("/api/auth/logout").status_code == 204
    parent.cookies.set("ogk_session", cookie)
    assert parent.get("/api/auth/me").status_code == 401


def test_csrf_blocks_writes(parent):
    parent.headers.pop("X-CSRF-Token")
    assert parent.post("/api/children", json={"display_name": "An"}).status_code == 403


def test_cross_origin_login(client):
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "https://evil.test"},
        json={
            "email": "parent@example.test",
            "password": "ExamplePassword123!",
        },
    )
    assert response.status_code == 403


def test_lock_after_five_failures(client):
    for _ in range(5):
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "email": "parent@example.test",
                    "password": "wrong",
                },
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/login",
            json={
                "email": "parent@example.test",
                "password": "ExamplePassword123!",
            },
        ).status_code
        == 401
    )


def test_enroll_heartbeat_policy(parent, child):
    tokens, _ = pair(parent, child)
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    assert (
        parent.post("/api/heartbeat", headers=headers, json={"policy_version": 0}).json()[
            "policy_version"
        ]
        == 1
    )
    policy = parent.get("/api/policy", headers=headers).json()
    assert policy["weekday_minutes"] == 90
    devices = parent.get("/api/devices").json()
    assert devices[0]["online"] is True
    assert devices[0]["id"] == tokens["device_id"]
    assert "access_hash" not in devices[0]


def test_code_cannot_be_reused(parent, child):
    _, code = pair(parent, child)
    assert (
        parent.post(
            "/api/enroll",
            json={
                "code": code,
                "display_name": "Second PC",
                "fingerprint": "another-installation-id",
            },
        ).status_code
        == 400
    )


def test_expired_code(parent, child, app):
    code = parent.post(
        "/api/enrollment-codes",
        json={
            "child_id": child["id"],
            "consent": True,
        },
    ).json()["code"]
    with app.state.sessions() as db:
        row = db.scalar(select(EnrollmentCode))
        row.expires_at = time.time() - 1
        db.commit()
    assert (
        parent.post(
            "/api/enroll",
            json={
                "code": code,
                "display_name": "Lab",
                "fingerprint": "random-installation-id",
            },
        ).status_code
        == 400
    )


def test_enrollment_requires_consent(parent, child):
    assert (
        parent.post(
            "/api/enrollment-codes",
            json={
                "child_id": child["id"],
                "consent": False,
            },
        ).status_code
        == 422
    )


def test_ownership(parent, child, app):
    with TestClient(app) as other:
        sign_in(other, "other@example.test")
        assert other.get("/api/children").json() == []
        assert other.get("/api/children/" + child["id"] + "/policy").status_code == 404
        assert (
            other.post(
                "/api/enrollment-codes",
                json={
                    "child_id": child["id"],
                    "consent": True,
                },
            ).status_code
            == 404
        )
        assert (
            other.put(
                "/api/children/" + child["id"] + "/policy",
                json={
                    "expected_version": 1,
                    "weekday_minutes": 30,
                    "weekend_minutes": 60,
                },
            ).status_code
            == 404
        )
        assert other.get("/api/devices").json() == []
        assert other.get("/api/audit").json() == []


def test_policy_change_and_conflict(parent, child):
    path = "/api/children/" + child["id"] + "/policy"
    body = {"expected_version": 1, "weekday_minutes": 30, "weekend_minutes": 60}
    result = parent.put(path, json=body)
    assert result.status_code == 200
    assert result.json()["version"] == 2
    assert parent.put(path, json=body).status_code == 409
    audit = parent.get("/api/audit").json()[0]
    assert audit["old_value"]["weekday_minutes"] == 90
    assert audit["new_value"]["weekday_minutes"] == 30


def test_refresh_rotation_and_revocation(parent, child, app):
    tokens, _ = pair(parent, child)
    body = {"device_id": tokens["device_id"], "refresh_token": tokens["refresh_token"]}
    result = parent.post("/api/auth/device/refresh", json=body)
    assert result.status_code == 200
    assert parent.post("/api/auth/device/refresh", json=body).status_code == 401
    assert (
        parent.get(
            "/api/policy",
            headers={
                "Authorization": "Bearer " + tokens["access_token"],
            },
        ).status_code
        == 401
    )
    fresh = result.json()
    with app.state.sessions() as db:
        db.get(Device, fresh["device_id"]).revoked = True
        db.commit()
    assert (
        parent.get(
            "/api/policy",
            headers={
                "Authorization": "Bearer " + fresh["access_token"],
            },
        ).status_code
        == 401
    )


def test_expired_access_and_session(parent, child, app):
    tokens, _ = pair(parent, child)
    with app.state.sessions() as db:
        db.get(Device, tokens["device_id"]).access_expires_at = 0
        db.scalar(select(ParentSession)).expires_at = 0
        db.commit()
    assert parent.get("/api/auth/me").status_code == 401
    assert (
        parent.get(
            "/api/policy",
            headers={
                "Authorization": "Bearer " + tokens["access_token"],
            },
        ).status_code
        == 401
    )


def test_simulator_sync_refresh_and_cache(parent, child, app, tmp_path):
    code = parent.post(
        "/api/enrollment-codes",
        json={
            "child_id": child["id"],
            "consent": True,
        },
    ).json()["code"]
    cache_path = tmp_path / "agent.db"
    with TestClient(app) as agent_client:
        agent = Simulator(agent_client, PolicyCache(cache_path))
        agent.enroll(code)
        agent.tick()
        assert agent.cache.load()["version"] == 1
        parent.put(
            "/api/children/" + child["id"] + "/policy",
            json={
                "expected_version": 1,
                "weekday_minutes": 45,
                "weekend_minutes": 90,
            },
        )
        agent.refresh_at = 0
        agent.tick()
        assert PolicyCache(cache_path).load()["weekday_minutes"] == 45
        assert PolicyCache(cache_path).load()["version"] == 2


def test_dashboard_assets_and_api_health(client):
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "default-src 'self'" in dashboard.headers["content-security-policy"]
    assert dashboard.headers["cache-control"] == "no-store"
    assert "/static/app.js?v=20261010-parent-tabs" in dashboard.text
    assert "/static/style.css?v=20261010-parent-tabs" in dashboard.text
    assert 'id="schedule-error"' in dashboard.text
    for path in ("/static/style.css", "/static/app.js", "/api/health", "/openapi.json"):
        assert client.get(path).status_code == 200
    script = client.get("/static/app.js?v=20261010-parent-tabs")
    assert script.headers["cache-control"] == "no-store"
    assert 'new Option("30", "30")' in script.text
    assert 'type = "time"' not in script.text
