import pytest
from fastapi.testclient import TestClient

from server.app.config import Settings
from server.app.main import create_app
from server.app.models import Parent
from server.app.security import password_hasher


@pytest.fixture
def app(tmp_path):
    app = create_app(Settings(database_url="sqlite:///" + (tmp_path / "test.db").as_posix()))
    with TestClient(app):
        with app.state.sessions() as db:
            for email in ("parent@example.test", "other@example.test"):
                db.add(
                    Parent(email=email, password_hash=password_hasher.hash("ExamplePassword123!"))
                )
            db.commit()
        yield app


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def sign_in(client, email="parent@example.test"):
    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "ExamplePassword123!",
        },
    )
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


@pytest.fixture
def parent(client):
    sign_in(client)
    return client


@pytest.fixture
def child(parent):
    response = parent.post("/api/children", json={"display_name": "Bé An", "pin": "123456"})
    assert response.status_code == 201
    return response.json()


def pair(parent, child):
    code = parent.post(
        "/api/enrollment-codes",
        json={
            "child_id": child["id"],
            "consent": True,
        },
    ).json()["code"]
    response = parent.post(
        "/api/enroll",
        json={
            "code": code,
            "display_name": "Lab PC",
            "fingerprint": "random-installation-identifier",
        },
    )
    assert response.status_code == 201
    return response.json(), code
