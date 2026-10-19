import json
import os

import pytest
from fastapi.testclient import TestClient

from agent.remote_sync import RemoteConfig
from agent.transport_security import TransportPolicy
from server.app.models import AdminUser, Device
from server.app.security import FieldCipher, digest, password_hasher
from tests.conftest import pair, sign_in


def test_aes_gcm_field_cipher_authenticates_ciphertext():
    cipher = FieldCipher("VFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFQ")
    encrypted = cipher.encrypt("device-secret", purpose="test")
    assert encrypted.startswith("enc:v1:")
    assert "device-secret" not in encrypted
    assert cipher.decrypt(encrypted, purpose="test") == "device-secret"
    tampered_index = len(FieldCipher.PREFIX) + 20
    tampered = (
        encrypted[:tampered_index]
        + ("A" if encrypted[tampered_index] != "A" else "B")
        + encrypted[tampered_index + 1 :]
    )
    with pytest.raises(ValueError):
        cipher.decrypt(tampered, purpose="test")


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is a Windows security boundary")
def test_remote_config_uses_dpapi_and_migrates_plaintext(tmp_path):
    path = tmp_path / "remote-config.json"
    config = RemoteConfig(
        "http://127.0.0.1:8000",
        "device",
        "access-secret",
        "refresh-secret",
        "policy-secret-32-characters-long",
        "installation-id",
    )
    config.save(path)
    text = path.read_text(encoding="utf-8")
    assert "access-secret" not in text
    assert json.loads(text)["format"] == "dpapi-local-machine-v1"
    assert RemoteConfig.load(path) == config


def test_transport_policy_requires_https_pin_for_https_and_remote_http():
    with pytest.raises(ValueError):
        TransportPolicy("https://server.test").validate()
    with pytest.raises(ValueError):
        TransportPolicy("http://192.0.2.10:8000").validate()
    TransportPolicy("http://127.0.0.1:8000").validate()
    TransportPolicy("https://server.test", "a" * 64).validate()


def test_device_key_is_encrypted_at_rest_and_revoke_invalidates_tokens(parent, child, app):
    tokens, _ = pair(parent, child)
    with app.state.sessions() as db:
        device = db.get(Device, tokens["device_id"])
        assert device.policy_signing_key.startswith("enc:v1:")
        assert device.policy_signing_key != tokens["policy_signing_key"]
        assert device.fingerprint == digest("random-installation-identifier")
        device.active_child_id = child["id"]
        device.active_user = child["display_name"]
        device.active_since = 1
        device.used_seconds = 60
        device.remaining_seconds = 120
        device.quota_seconds = 180
        device.extra_seconds = 0
        device.active_usage = True
        device.time_status_at = 1
        db.commit()
    response = parent.post(f"/api/devices/{tokens['device_id']}/revoke", json={})
    assert response.status_code == 200
    assert response.json()["revoked"] is True
    revoked = parent.get("/api/devices").json()[0]
    assert revoked["revoked"] is True
    assert revoked["active_child_id"] is None
    assert revoked["active_user"] is None
    assert revoked["used_seconds"] is None
    assert revoked["remaining_seconds"] is None
    assert revoked["active_usage"] is False
    assert (
        parent.get(
            "/api/policy", headers={"Authorization": "Bearer " + tokens["access_token"]}
        ).status_code
        == 401
    )
    assert (
        parent.post(
            "/api/auth/device/refresh",
            json={"device_id": tokens["device_id"], "refresh_token": tokens["refresh_token"]},
        ).status_code
        == 401
    )


def test_admin_session_is_separate_and_metadata_only(app):
    object.__setattr__(app.state.settings, "admin_enabled", True)
    with app.state.sessions() as db:
        db.add(
            AdminUser(
                email="admin@example.test",
                password_hash=password_hasher.hash("AdminPassword123!"),
            )
        )
        db.commit()
    with TestClient(app) as admin:
        response = admin.post(
            "/api/admin/auth/login",
            json={"email": "admin@example.test", "password": "AdminPassword123!"},
        )
        assert response.status_code == 200
        admin.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        overview = admin.get("/api/admin/overview").json()
        assert overview["role"] == "admin"
        assert set(overview) == {"role", "parents", "children", "devices", "revoked_devices"}
        assert admin.get("/api/children").status_code == 401
    with TestClient(app) as parent_only:
        sign_in(parent_only)
        assert parent_only.get("/api/admin/overview").status_code == 401


def test_https_responses_add_hsts(app):
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/api/health")
    assert response.headers["strict-transport-security"] == "max-age=31536000"
