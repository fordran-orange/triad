import os
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_checkout = Path(__file__).resolve().parents[2]
ROOT = Path(
    os.environ.get(
        "TRADING_HOME", str(_checkout if (_checkout / "pyproject.toml").is_file() else Path.cwd())
    )
).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 55432
    postgres_db: str = "triad"
    postgres_user: str = "triad_admin"
    postgres_password: SecretStr
    neo4j_uri: str = "bolt://127.0.0.1:57687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    local_model_enabled: bool = False
    triad_operator_token: SecretStr = SecretStr("")
