from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from adrobot.config import Settings
from adrobot.main import create_app


def test_readiness_requires_migration(database_url: str) -> None:
    app = create_app(Settings(_env_file=None, database_url=database_url))
    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable or migrations not applied"}


def test_readiness_after_migration(migrated_database: str) -> None:
    app = create_app(Settings(_env_file=None, database_url=migrated_database))
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_readiness_requires_editor_migration(database_url: str) -> None:
    command.upgrade(Config("alembic.ini"), "0002")
    app = create_app(Settings(_env_file=None, database_url=database_url))
    with TestClient(app) as client:
        assert client.get("/api/v1/health/ready").status_code == 503
        command.upgrade(Config("alembic.ini"), "head")
        assert client.get("/api/v1/health/ready").status_code == 200
