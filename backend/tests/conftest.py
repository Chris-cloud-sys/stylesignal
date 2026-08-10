"""Test fixtures.

Every test runs against a throwaway SQLite file and a throwaway storage
directory, with the VLM switched off — so the suite exercises the §7.6 fallback
path and never spends tokens.
"""
import io
import os
import sys
import tempfile
import uuid

import pytest
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(scope="session", autouse=True)
def _isolated_environment():
    workdir = tempfile.mkdtemp(prefix="stylesignal-tests-")
    os.environ.update(
        {
            "STYLESIGNAL_ENV": "test",
            "STYLESIGNAL_JWT_SECRET": "test-secret-not-used-anywhere-real",
            "STYLESIGNAL_DATABASE_URL": "sqlite:///{0}/test.db".format(
                workdir.replace("\\", "/")
            ),
            "STYLESIGNAL_STORAGE_BACKEND": "local",
            "STYLESIGNAL_LOCAL_STORAGE_DIR": os.path.join(workdir, "objects"),
            "STYLESIGNAL_QUEUE_BACKEND": "inprocess",
            "STYLESIGNAL_INPROCESS_CONCURRENCY": "1",
            "STYLESIGNAL_VLM_DISABLED": "true",
            "STYLESIGNAL_ANTHROPIC_API_KEY": "",
            "STYLESIGNAL_FREE_MONTHLY_SCANS": "3",
            "STYLESIGNAL_COMMUNITY_ENABLED": "true",
        }
    )
    # config caches Settings; make sure nothing imported it first.
    for module in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[module]
    yield workdir


@pytest.fixture(scope="session")
def app_module(_isolated_environment):
    from app.db import init_db
    from app.main import create_app

    init_db()
    return create_app()


@pytest.fixture()
def client(app_module):
    from fastapi.testclient import TestClient

    with TestClient(app_module) as test_client:
        yield test_client


@pytest.fixture()
def auth_client(client):
    """A TestClient with a fresh registered user's bearer token attached."""
    email = "user-{0}@example.com".format(uuid.uuid4().hex[:10])
    response = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "display_name": "Test"},
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    client.headers.update({"Authorization": "Bearer {0}".format(token)})
    return client


def make_jpeg(
    width: int = 900, height: int = 1400, colour=(40, 52, 76)
) -> bytes:
    """A synthetic 'outfit' photo: three horizontal bands of distinct colour."""
    image = Image.new("RGB", (width, height), colour)
    top = Image.new("RGB", (width, height // 3), (168, 132, 96))
    shoes = Image.new("RGB", (width, height // 6), (24, 24, 26))
    image.paste(top, (0, 0))
    image.paste(shoes, (0, height - height // 6))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


@pytest.fixture()
def jpeg_bytes() -> bytes:
    return make_jpeg()
