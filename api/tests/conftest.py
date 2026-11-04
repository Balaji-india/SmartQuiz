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


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch):
    """No test may reach Groq or Amoy with the real .env values. Tests that need a chain set their own."""
    from app.chain import service

    settings = get_settings()
    for name in ("gemini_api_key", "groq_api_key", "amoy_rpc_url", "issuer_private_key", "registry_address"):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "chain_optional", True)
    service.reset_chain()
    yield
    service.reset_chain()


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


# Hardhat's well-known account #0. Public test key, worthless on any real chain.
HARDHAT_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
LOCAL_RPC = "http://127.0.0.1:8545"
ARTIFACT = API_DIR.parent / "contracts" / "artifacts" / "contracts" / "SmartQuizRegistry.sol" / "SmartQuizRegistry.json"


@pytest.fixture
def local_chain(monkeypatch):
    """A fresh SmartQuizRegistry on a local Hardhat node, wired into settings. Skips without a node.

    Start one with `npx hardhat node` in contracts/. Never reads REGISTRY_ADDRESS or ISSUER_PRIVATE_KEY.
    """
    import json

    from web3 import Web3

    from app.chain import service

    w3 = Web3(Web3.HTTPProvider(LOCAL_RPC, request_kwargs={"timeout": 2}))
    try:
        w3.eth.chain_id
    except Exception:
        pytest.skip("no Hardhat node on 127.0.0.1:8545 (run `npx hardhat node` in contracts/)")
    if not ARTIFACT.exists():
        pytest.skip("contracts are not compiled (run `npx hardhat compile` in contracts/)")
    artifact = json.loads(ARTIFACT.read_text("utf-8"))
    account = w3.eth.account.from_key(HARDHAT_KEY)
    factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
    tx = factory.constructor(account.address).build_transaction(
        {"from": account.address, "nonce": w3.eth.get_transaction_count(account.address, "pending")}
    )
    signed = account.sign_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))

    settings = get_settings()
    monkeypatch.setattr(settings, "amoy_rpc_url", LOCAL_RPC)
    monkeypatch.setattr(settings, "issuer_private_key", HARDHAT_KEY)
    monkeypatch.setattr(settings, "registry_address", receipt["contractAddress"])
    service.reset_chain()
    return service.get_chain()


@pytest.fixture
def chain_down(monkeypatch):
    """Chain configured but unreachable (nothing listens on port 9)."""
    from app.chain import service

    settings = get_settings()
    monkeypatch.setattr(settings, "amoy_rpc_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "issuer_private_key", HARDHAT_KEY)
    monkeypatch.setattr(settings, "registry_address", "0x" + "11" * 20)
    service.reset_chain()


def signup_headers(client, email="a@b.com") -> dict:
    body = {"email": email, "password": "correct horse battery", "name": "Test"}
    token = client.post("/auth/signup", json=body).json()["token"]
    return {"Authorization": f"Bearer {token}"}
