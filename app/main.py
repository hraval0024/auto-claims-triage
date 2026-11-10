"""FastAPI entrypoint."""

import uuid
from typing import Literal

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.config import COST_TABLE_VERSION, PROMPT_VERSION, SCHEMA_VERSION, settings
from app.intake import IntakeError
from app.pipeline import run_claim
from app.schemas import ClaimResult
from app.ssrf import fetch_image

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


@app.post("/api/claims", response_model=ClaimResult)
def create_claim(
    files: list[UploadFile] = File(default=[]),
    urls: list[str] = Form(default=[]),
    region: Literal["low_cost", "standard", "high_cost"] = Form(default="standard"),
    include_llm_baseline: bool = Form(default=False),  # eval/debug only; the main UI never sets it
):
    """One claim = up to N photos, from uploads and/or URLs. Sync handler: FastAPI runs it in a
    worker thread, so the blocking model call doesn't stall the event loop."""
    request_id = str(uuid.uuid4())
    try:
        images = []
        for f in files:
            data = f.file.read(settings.max_upload_bytes + 1)  # read at most cap+1 bytes
            if len(data) > settings.max_upload_bytes:
                raise IntakeError(f"File too large (max {settings.max_upload_bytes // (1024 * 1024)} MB).")
            images.append(data)
        for u in (u.strip() for u in urls):
            if u:
                images.append(fetch_image(u))
        return run_claim(images, request_id=request_id, region=region, include_llm_baseline=include_llm_baseline)
    except IntakeError as e:
        return JSONResponse(status_code=400, content={"request_id": request_id, "status": "rejected", "error": str(e)})
