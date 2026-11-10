"""Runtime configuration.

Versions that define *behavior* (prompt, schema, cost table) are pinned in code so every
response can be traced to an exact commit. Operational knobs come from env vars / .env.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

# Pinned in code, recorded on every response (auditability).
PROMPT_VERSION = "extract_v2"  # v2: camera_view before side (F1 fix)
SCHEMA_VERSION = "1.1.0"  # 1.1: PhotoAssessment.camera_view
COST_TABLE_VERSION = "cost_table_v1"
LLM_BASELINE_PROMPT_VERSION = "llm_baseline_v1"

# USD per million tokens: (input, output, cache_write_5min, cache_read). Source: Anthropic list
# prices as cached in the claude-api reference on 2026-11-03 (cache write = 1.25x input; cache
# read = 0.05x on Opus/Sonnet 5.5, 0.1x on Haiku 5.5). Verify against
# https://www.anthropic.com/pricing before quoting externally. Thinking is billed as output.
MODEL_PRICES_USD_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),  # prompts <= 100K tokens; ours are far smaller
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    # Provisional default: Sonnet 5.5 (Opus 5.5 thinking is always on, which risks the
    # p95 < 15 s demo target). Final default chosen from Phase 4 eval numbers.
    model_id: str = "claude-sonnet-5-5"
    # Effort level sent to the model. Recorded on every response. Tuned from measurements.
    model_effort: str = "medium"
    # Cache the static prefix (instructions + rubric + schema) across requests.
    prompt_cache: bool = True
    model_timeout_s: float = 40.0
    model_max_retries: int = 2  # SDK retries 408/409/429/5xx/connection errors with backoff
    validation_max_retries: int = 2  # re-ask when output fails our validation

    # Image handling
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 40_000_000  # decompression-bomb guard
    max_image_side_px: int = 12_000
    model_image_long_side_px: int = 1568  # resize cap before sending (latency/token control)
    max_photos_per_claim: int = 5

    # URL fetch (SSRF guard)
    url_fetch_timeout_s: float = 10.0
    url_max_redirects: int = 3

    # LLM free-guess cost baseline: a SEPARATE call, for eval comparison only. Off by default;
    # its number never feeds the cost table or routing.
    llm_baseline_enabled: bool = False

    daily_spend_cap_usd: float = 5.00

    # Body-shop labor rate, USD/hour. Source: 2026 "Who Pays for What?" survey, median
    # non-DRP body labor rate (~$68/h). Rates vary a lot by state; regional tiers that
    # adjust this (Phase 2) are ASSUMPTIONS with no source. Do not substitute the
    # ~$120-159/h general mechanical repair rate.
    labor_rate_usd_per_hour: float = 68.0


settings = Settings()
