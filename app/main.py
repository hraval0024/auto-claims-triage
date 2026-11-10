"""FastAPI entrypoint. Phase 0: health check only."""

from fastapi import FastAPI

from app.config import COST_TABLE_VERSION, PROMPT_VERSION, SCHEMA_VERSION, settings

app = FastAPI(title="Auto Claims Triage", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_id": settings.model_id,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "cost_table_version": COST_TABLE_VERSION,
        "api_key_configured": bool(settings.anthropic_api_key),
    }
