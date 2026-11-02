from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
API_DIR = ROOT_DIR / "api"


class Settings(BaseSettings):
    # The root .env by absolute path, so this works from any working directory.
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    gemini_api_key: str = ""
    generator_base_url: str = ""
    llm_generator_model: str = ""
    groq_api_key: str = ""
    checker_base_url: str = ""
    llm_checker_model: str = ""
    generator_rpm: int = 8
    checker_rpm: int = 25
    checker_tpm: int = 7000

    database_url: str = "postgresql+psycopg://smartquiz:smartquiz@localhost:5432/smartquiz"
    jwt_secret: str = ""

    amoy_rpc_url: str = ""
    issuer_private_key: str = ""
    registry_address: str = ""
    chain_optional: bool = True

    chat_min_sim: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
