"""Runtime configuration.

Versions that define *behavior* (prompt, schema, cost table) are pinned in code so every
response can be traced to an exact commit. Operational knobs come from env vars / .env.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

# Pinned in code, recorded on every response (auditability).
PROMPT_VERSION = "extract_v0"  # bumped to v1 when the Phase 1 prompt lands
SCHEMA_VERSION = "0.1.0"
COST_TABLE_VERSION = "none"  # set when the Phase 2 table lands


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    # Provisional default: Sonnet 5.5. Final default chosen from Phase 4 eval numbers.
    model_id: str = "claude-sonnet-5-5"

    daily_spend_cap_usd: float = 5.00
    # ASSUMPTION (no source): body-shop labor rate in USD/hour, chosen by the candidate.
    labor_rate_usd_per_hour: float = 68.0


settings = Settings()
