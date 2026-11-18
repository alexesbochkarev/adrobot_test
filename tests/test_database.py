import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from adrobot.db import create_db_engine
from adrobot.models import Campaign


def test_migration_round_trip(migrated_database: str) -> None:
    config = Config("alembic.ini")
    command.check(config)
    command.downgrade(config, "base")
    engine = create_db_engine(migrated_database)
    try:
        assert "campaigns" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        assert "campaigns" in inspect(engine).get_table_names()
        command.check(config)
    finally:
        engine.dispose()


def test_campaign_persistence_and_rollback(migrated_database: str) -> None:
    engine = create_db_engine(migrated_database)
    try:
        with Session(engine) as session:
            session.add(Campaign(keitaro_id=123, name="Test"))
            session.commit()
        with Session(engine) as session:
            campaign = session.scalar(select(Campaign))
            assert campaign is not None
            assert campaign.keitaro_id == 123
            assert campaign.created_at is not None
            session.add(Campaign(keitaro_id=456, name="Uncommitted"))
            session.flush()
        with Session(engine) as session:
            assert list(session.scalars(select(Campaign.keitaro_id))) == [123]
            assert session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("keitaro_id", [123, 0, -1])
def test_campaign_constraints(migrated_database: str, keitaro_id: int) -> None:
    engine = create_db_engine(migrated_database)
    try:
        with Session(engine) as session:
            session.add(Campaign(keitaro_id=123, name="Existing"))
            session.commit()
            session.add(Campaign(keitaro_id=keitaro_id, name="Invalid"))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        engine.dispose()
