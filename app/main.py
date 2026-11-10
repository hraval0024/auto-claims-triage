"""FastAPI entrypoint: API + the one-page UI (served from app/static by the same app)."""

import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import store
from app.config import COST_TABLE_VERSION, PROMPT_VERSION, SCHEMA_VERSION, settings
from app.intake import IntakeError
from app.pipeline import run_claim
from app.review import ReviewRequest, ReviewResult, review
from app.schemas import CameraView, ClaimResult, DamageType, Panel, Side
from app.ssrf import fetch_image

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Auto Claims Triage", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


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


@app.get("/api/vocab")
def vocab() -> dict:
    """Allowed values for the UI's edit controls (single source of truth: the schema)."""
    return {
        "panels": [p.value for p in Panel], "sides": [s.value for s in Side],
        "damage_types": [d.value for d in DamageType], "camera_views": [c.value for c in CameraView],
        "regions": ["low_cost", "standard", "high_cost"], "severities": [1, 2, 3, 4],
    }


@app.post("/api/claims", response_model=ClaimResult)
def create_claim(
    files: list[UploadFile] = File(default=[]),
    urls: list[str] = Form(default=[]),
    region: Literal["low_cost", "standard", "high_cost"] = Form(default="standard"),
    # Eval/debug only. Unset -> the server setting LLM_BASELINE_ENABLED (default off). The UI never sends it.
    include_llm_baseline: bool | None = Form(default=None),
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
            if data:
                images.append(data)
        for u in (u.strip() for u in urls):
            if u:
                images.append(fetch_image(u))
        result = run_claim(images, request_id=request_id, region=region, include_llm_baseline=include_llm_baseline)
    except IntakeError as e:
        return JSONResponse(status_code=400, content={"request_id": request_id, "status": "rejected", "error": str(e)})
    store.save_result(request_id, result.model_dump_json())  # audit log: result only, never image bytes
    return result


@app.post("/api/claims/{request_id}/review", response_model=ReviewResult)
def review_claim(request_id: str, body: ReviewRequest):
    try:
        return review(request_id, body)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown request id.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/corrections")
def corrections(limit: int = 100) -> dict:
    return {"corrections": store.recent_corrections(min(limit, 500)), "reviews": store.recent_reviews(min(limit, 500))}
