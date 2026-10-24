"""Test fixtures. Database tests use a throwaway `scanger_test` database on the
Compose PostgreSQL (it must be running). The real database is never touched."""

import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from scanger.config import REPO_ROOT, UploadLimits, database_url

TEST_DB = "scanger_test"


@pytest.fixture(scope="session")
def test_engine():
    assert TEST_DB.endswith("_test")
    admin = create_engine(
        database_url().set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}"'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))

    # Build the schema with the real migrations, pointing Alembic at the test DB.
    previous = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = TEST_DB
    try:
        command.upgrade(Config(str(REPO_ROOT / "alembic.ini")), "head")
    finally:
        if previous is None:
            del os.environ["DB_NAME"]
        else:
            os.environ["DB_NAME"] = previous

    engine = create_engine(database_url().set(database=TEST_DB))
    assert engine.url.database == TEST_DB
    yield engine
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}"'))
    admin.dispose()


@pytest.fixture
def db(test_engine):
    factory = sessionmaker(test_engine, expire_on_commit=False)
    with factory() as session:
        yield session
    with test_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE search_result, search_run, turn, asset, session CASCADE"
            )
        )


@pytest.fixture
def data_root(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def limits():
    return UploadLimits(max_bytes=200_000, max_dimension=512)


@pytest.fixture
def client(test_engine, data_root, limits):
    from scanger import api

    factory = sessionmaker(test_engine, expire_on_commit=False)

    def override_db():
        with factory() as session:
            yield session

    api.app.dependency_overrides[api.get_db] = override_db
    api.app.dependency_overrides[api.get_data_root] = lambda: data_root
    api.app.dependency_overrides[api.get_limits] = lambda: limits
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()
