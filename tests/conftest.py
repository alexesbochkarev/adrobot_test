from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


@pytest.fixture
def migrated_database(database_url: str) -> str:
    command.upgrade(Config("alembic.ini"), "head")
    return database_url
