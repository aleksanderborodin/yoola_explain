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
    llm_legal_check: bool = True  # cheap LLM confirmation before an expensive generation

    anchor_min_score: float = 85.0
    simhash_max_distance: int = 4

    ip_daily_miss_budget: int = 10
    global_daily_miss_budget: int = 200
    global_daily_fetch_budget: int = 2000  # caps use of the server as a fetch amplifier
    url_ttl_days: int = 7

    # Reports: distinct-IP threshold to mark a summary disputed (a warning, never
    # a paid regeneration — see docs/architecture.md), and a per-IP daily cap.
    dispute_threshold: int = 3
    ip_daily_report_budget: int = 20

    # Deployment: number of trusted reverse-proxy hops in front of uvicorn.
    # 0 = direct (dev). Behind Caddy/nginx set 1 so the real client IP is read
    # from X-Forwarded-For instead of the proxy's address. See docs/gotchas.md.
    trusted_proxy_hops: int = 0
    # CORS origins allowed for browser (website) callers. The extension uses
    # host_permissions and is unaffected by this, so the safe default is empty
    # (no third-party website may drive the API from a visitor's browser).
    allowed_origins: list[str] = []
    report_salt: str = "yoola-dev-salt"  # override in prod; salts reporter-IP hashes
