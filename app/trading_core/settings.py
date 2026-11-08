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


class StoreSettings(BaseSettings):
    """What Core's `Store` needs: the Postgres connection. A product worker builds a product view
    on this base (below) instead of the whole `Settings`, so Core-only values never enter its
    process (docs/AEGIS_WORKER_ENVIRONMENT.md). One `.env`, read for fewer names."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    postgres_host: str = "127.0.0.1"
    # Published below Windows' dynamic port range (49152 up), which the networking stack carves
    # blocks out of at boot (docs/CORE_DEPENDENCY_PORTS_AFTER_REBOOT.md, Option A, 2026-11-07).
    postgres_port: int = 15432
    postgres_db: str = "triad"
    postgres_user: str = "triad_admin"
    postgres_password: SecretStr


class Settings(StoreSettings):
    """Core's whole configuration: the gateway, the supervisor and the tools build this."""

    neo4j_uri: str = "bolt://127.0.0.1:17687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    local_model_enabled: bool = False
    triad_operator_token: SecretStr = SecretStr("")
    # Mission 14: a product worker's key for its read-only reasoning route; never the operator token.
    aegis_product_key: SecretStr = SecretStr("")


class AegisSettings(StoreSettings):
    """The Aegis worker's view: its work-item store and its own product key, nothing of Core's
    alone (no operator token, no Neo4j, no Ollama)."""

    aegis_product_key: SecretStr = SecretStr("")
