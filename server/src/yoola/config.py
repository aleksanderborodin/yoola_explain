"""Runtime settings. Env vars use the YOOLA_ prefix (YOOLA_DB_PATH=...);
the provider key is also read as MODELGATE_API_KEY / OPENROUTER_API_KEY.
The inference endpoint is any OpenAI-compatible /v1 base URL."""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

DISCLAIMER = "AI-generated summary. Not legal advice. Verify against the original."


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="YOOLA_", env_file=".env", extra="ignore")

    db_path: str = "yoola.db"
    taxonomy_path: str = str(REPO_ROOT / "shared" / "taxonomy.json")

    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "YOOLA_LLM_API_KEY", "MODELGATE_API_KEY", "OPENROUTER_API_KEY"
        ),
    )
    llm_base_url: str = "https://api.modelgate.ru/v1"
    generator_model: str = "gemma-4-31b"
    verifier_model: str = "gemma-4-31b"

    fetch_timeout_s: float = 20.0
    fetch_max_bytes: int = 3_000_000
    content_max_chars: int = 300_000
    min_words: int = 120
    plausibility_min_density: float = 2.0  # legal markers per 1000 words

    anchor_min_score: float = 85.0
    simhash_max_distance: int = 4

    ip_daily_miss_budget: int = 10
    global_daily_miss_budget: int = 200
    flag_demote_threshold: int = 3
    url_ttl_days: int = 7
