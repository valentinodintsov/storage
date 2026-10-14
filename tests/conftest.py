import os
import secrets
import tempfile

# Тесты работают на отдельной временной БД с собственными секретами — до импорта приложения
_tmp = tempfile.mkdtemp()
os.environ["STORAGE_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["STORAGE_SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["STORAGE_ADMIN_PASSWORD"] = "admin-test-pass"
os.environ["STORAGE_DEMO_PASSWORD"] = "demo12345"
os.environ["STORAGE_SIGNATURE_PROVIDER"] = "simple"  # не зависеть от локального .env

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "demo12345"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        seed.run()
        yield c


@pytest.fixture(scope="session")
def tokens(client):
    result = {}
    for login, password in (("admin", "admin-test-pass"), ("manager", PASSWORD), ("head", PASSWORD),
                            ("ivanov", PASSWORD), ("smirnova", PASSWORD)):
        r = client.post("/api/v1/auth/token", data={"username": login, "password": password})
        assert r.status_code == 200, r.text
        result[login] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return result
