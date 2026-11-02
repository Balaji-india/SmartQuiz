"""Database tests run against smartquiz_test, recreated each session. The dev database is never written to."""
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker

from app.config import API_DIR, get_settings
from app.db import get_db
from app.main import app

TEST_DB_NAME = "smartquiz_test"


@pytest.fixture(scope="session")
def test_db_url() -> str:
    dev_url = make_url(get_settings().database_url)
    admin = create_engine(dev_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin.dispose()
    return dev_url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def alembic_cfg(test_db_url) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_db_url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def test_engine(test_db_url):
    engine = create_engine(test_db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def client(alembic_cfg, test_engine, monkeypatch):
    command.upgrade(alembic_cfg, "head")
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE users CASCADE"))
    monkeypatch.setattr(get_settings(), "jwt_secret", "test-secret-that-is-long-enough-for-hs256")
    testing_session = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
