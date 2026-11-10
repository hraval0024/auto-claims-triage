"""Vision model call with native structured outputs, validation retry and cost accounting.

- Native structured outputs (output_config.format = JSON schema from ModelOutput). Not forced
  tool_choice, which Claude Opus 5.5 / Sonnet 5.5 reject.
- We call messages.create and validate ourselves (rather than messages.parse) so that token
  usage is still recorded when an attempt fails validation.
- No temperature: current Claude models reject sampling parameters. Determinism comes from
  pinned model id, effort, prompt and schema versions (all recorded on every response).
- Transient API errors (429/5xx/timeouts/connection) are retried by the SDK with backoff
  (settings.model_max_retries). Output that fails validation is re-requested up to
  settings.validation_max_retries times.
"""

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
from anthropic.lib._parse._transform import transform_schema  # same transform messages.parse uses
from pydantic import ValidationError

from app.config import MODEL_PRICES_USD_PER_MTOK, PROMPT_VERSION, settings
from app.schemas import ModelOutput

_PROMPT_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPT_DIR / f"{PROMPT_VERSION}.md").read_text().replace(
    "{rubric}", (_PROMPT_DIR / "rubric_v1.md").read_text()
)
OUTPUT_SCHEMA = transform_schema(ModelOutput.model_json_schema())


class LLMError(Exception):
    """Model call failed; the caller must route to a human, never fabricate a result."""

    def __init__(self, message: str, usage: "UsageTally"):
        super().__init__(message)
        self.usage = usage


@dataclass
class UsageTally:
    model_id: str
    input_tokens: int = 0  # uncached
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    validation_errors: list[str] = field(default_factory=list)

    def add(self, usage) -> None:
        self.input_tokens += usage.input_tokens
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.output_tokens += usage.output_tokens

    @property
    def cost_usd(self) -> float:
        p_in, p_out, p_write, p_read = MODEL_PRICES_USD_PER_MTOK[self.model_id]
        return (
            self.input_tokens * p_in
            + self.cache_write_tokens * p_write
            + self.cache_read_tokens * p_read
            + self.output_tokens * p_out
        ) / 1_000_000


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key or None,
            timeout=settings.model_timeout_s,
            max_retries=settings.model_max_retries,
        )
    return _client


def build_user_content(images_jpeg: list[bytes], retry_note: str | None) -> list[dict]:
    content: list[dict] = []
    for i, data in enumerate(images_jpeg):
        content.append({"type": "text", "text": f"Photo {i}:"})
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(data).decode()},
            }
        )
    text = f"These {len(images_jpeg)} photo(s) belong to one claim. Assess them as instructed."
    if retry_note:
        text += f"\n\nA previous attempt returned output that failed validation: {retry_note}. Return corrected output."
    content.append({"type": "text", "text": text})
    return content


def system_blocks() -> list[dict]:
    """Static prefix: instructions + rubric (the schema rides in output_config). Marked for
    caching so repeat requests read it at a fraction of the input price."""
    block = {"type": "text", "text": SYSTEM_PROMPT}
    if settings.prompt_cache:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def semantic_check(out: ModelOutput, n_photos: int) -> None:
    """Checks the JSON schema can't express. Raises ValueError with a model-readable message."""
    indices = [p.photo_index for p in out.photos]
    if sorted(indices) != list(range(n_photos)):
        raise ValueError(f"'photos' must contain exactly one entry per photo index 0..{n_photos - 1}; got {indices}")
    bad = [d.photo_index for d in out.damage if not 0 <= d.photo_index < n_photos]
    if bad:
        raise ValueError(f"damage observations reference photo indices that don't exist: {bad}")
    yr = out.vehicle.year_range
    if yr.start is not None and yr.end is not None and yr.start > yr.end:
        raise ValueError("year_range.start is after year_range.end")


def call_model(
    images_jpeg: list[bytes],
    *,
    model_id: str | None = None,
    effort: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> tuple[ModelOutput, UsageTally]:
    model_id = model_id or settings.model_id
    effort = effort or settings.model_effort
    client = client or get_client()
    tally = UsageTally(model_id=model_id)
    retry_note: str | None = None

    for _ in range(1 + settings.validation_max_retries):
        tally.attempts += 1
        try:
            resp = client.messages.create(
                model=model_id,
                max_tokens=16000,
                system=system_blocks(),
                messages=[{"role": "user", "content": build_user_content(images_jpeg, retry_note)}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            )
        except anthropic.APIStatusError as e:
            raise LLMError(f"Model API error (HTTP {e.status_code}).", tally) from e
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
            raise LLMError("Model API unreachable or timed out.", tally) from e

        tally.add(resp.usage)
        if resp.stop_reason == "refusal":
            # No server-side fallback to another model: a silent model switch would break the
            # audit trail and the per-model eval. A decline goes to a human instead.
            raise LLMError("The model declined to assess these photos.", tally)

        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            if resp.stop_reason == "max_tokens":
                raise ValueError("output was cut off at max_tokens")
            out = ModelOutput.model_validate_json(text)
            semantic_check(out, len(images_jpeg))
            return out, tally
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            retry_note = _short_error(e)
            tally.validation_errors.append(retry_note)

    raise LLMError(f"Model output failed validation after {tally.attempts} attempts.", tally)


def _short_error(e: Exception) -> str:
    if isinstance(e, ValidationError):
        errs = e.errors()[:3]
        return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in errs)
    return str(e)[:300]
