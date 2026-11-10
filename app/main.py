"""FastAPI entrypoint: API + the one-page UI, behind a shared access code.

Request flow: gatekeeper middleware (rate limit, access check, security headers, one JSON log
line per request) -> route. The claims route adds the stricter per-IP claims limit, the
concurrency cap, the image-hash cache, idempotency, and the daily call/spend caps.
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from statistics import median
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import store
from app.config import COST_TABLE_VERSION, PROMPT_VERSION, SCHEMA_VERSION, check_config, settings
from app.guards import CONCURRENCY, LIMITER, MSG_BUSY, MSG_RATE, TRIGGERS, CapError, DailyCapGuard, trigger
from app.intake import IntakeError
from app.logs import ip_hash, log_event, setup_logging
from app.pipeline import run_claim
from app.review import ReviewRequest, ReviewResult, review
from app.schemas import CameraView, ClaimResult, DamageType, Panel, Side
from app.security import COOKIE, EXEMPT, SECURITY_HEADERS, authorized, client_ip, code_ok, is_https, session_token
from app.ssrf import fetch_image, redact_url

APP_DIR = Path(__file__).parent
STATIC = APP_DIR / "static"
LOGIN_HTML = (APP_DIR / "login.html").read_text()
UNAUTHORIZED = {"error": "Unauthorized"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    check_config()  # raises with a clear message (no secret values) if config is incomplete
    store.health_check()
    log_event("startup", model_id=settings.model_id, data_dir=settings.data_dir, daily_call_cap=settings.daily_call_cap,
              daily_spend_cap_usd=settings.daily_spend_cap_usd, max_concurrent_claims=settings.max_concurrent_claims)
    yield


# No CORSMiddleware: cross-origin browser requests get no CORS headers (closed by default).
app = FastAPI(title="Auto Claims Triage", version="0.1.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)  # no public API docs on a paid endpoint
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _login_page(status: int, error: bool = False) -> HTMLResponse:
    body = LOGIN_HTML.replace("<!--ERROR-->", '<p class="err" role="alert">Not authorized.</p>' if error else "")
    return HTMLResponse(body, status_code=status)


@app.middleware("http")
async def gatekeeper(request: Request, call_next):
    t0 = time.monotonic()
    rid = str(uuid.uuid4())
    request.state.request_id = rid
    path, ip = request.url.path, client_ip(request)
    try:
        if path not in EXEMPT and not LIMITER.allow(f"req:{ip}", settings.rate_limit_requests_per_min):
            trigger("rate_limit_requests", ip=ip_hash(ip), path=path)
            response = JSONResponse({"error": MSG_RATE}, status_code=429)
        elif path not in EXEMPT and not authorized(request):
            response = _login_page(401) if (path == "/" and request.method == "GET") else JSONResponse(UNAUTHORIZED, status_code=401)
        else:
            response = await call_next(request)
    except Exception as e:  # never leak a stack trace, a path or a key to the client
        log_event("unhandled_error", logging.ERROR, request_id=rid, path=path, error=type(e).__name__)
        response = JSONResponse({"error": "Internal error. The request was not completed.", "request_id": rid}, status_code=500)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if is_https(request):
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["X-Request-ID"] = rid
    log_event("http_request", request_id=rid, method=request.method, path=path,  # path only: no query string
              status=response.status_code, latency_ms=int((time.monotonic() - t0) * 1000), ip=ip_hash(ip))
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    # Field names only: never echo submitted values back.
    fields = sorted({".".join(str(p) for p in e["loc"] if p not in ("body", "query")) for e in exc.errors()})
    return JSONResponse({"error": "Invalid request.", "fields": fields}, status_code=422)


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException):
    return JSONResponse({"error": exc.detail if isinstance(exc.detail, str) else "Request failed."}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    rid = getattr(request.state, "request_id", None)
    log_event("unhandled_error", logging.ERROR, request_id=rid, path=request.url.path, error=type(exc).__name__)
    return JSONResponse({"error": "Internal error. The request was not completed.", "request_id": rid}, status_code=500)


# ---------- open routes ----------
@app.get("/healthz", include_in_schema=False)
def healthz():
    """Liveness + DB writable. Never calls the model. Reveals nothing about configuration."""
    try:
        store.health_check()
    except Exception as e:
        log_event("healthz_failed", logging.ERROR, error=type(e).__name__)
        return JSONResponse({"status": "error", "db": "not writable"}, status_code=503)
    return {"status": "ok", "db": "writable"}


@app.get("/login", include_in_schema=False)
def login_page():
    return _login_page(200)


@app.post("/login", include_in_schema=False)
def login(request: Request, code: str = Form(default="")):
    ip = client_ip(request)
    if not LIMITER.allow(f"login:{ip}", settings.rate_limit_login_per_min):
        trigger("rate_limit_login", ip=ip_hash(ip))
        return JSONResponse({"error": MSG_RATE}, status_code=429)
    if not code_ok(code):
        log_event("login_failed", ip=ip_hash(ip))
        return _login_page(401, error=True)
    resp = RedirectResponse("/", status_code=303)
    # Session cookie (no Max-Age/Expires): gone when the browser session ends. Holds an HMAC token, not the code.
    resp.set_cookie(COOKIE, session_token(), httponly=True, samesite="strict", secure=is_https(request), path="/")
    return resp


@app.post("/logout", include_in_schema=False)
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE, path="/")
    return resp


# ---------- protected routes ----------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict:
    """Detailed health (behind the access code): versions and whether the key is configured."""
    store.health_check()
    return {"status": "ok", "model_id": settings.model_id, "prompt_version": PROMPT_VERSION, "schema_version": SCHEMA_VERSION,
            "cost_table_version": COST_TABLE_VERSION, "api_key_configured": bool(settings.anthropic_api_key)}


@app.get("/api/vocab")
def vocab() -> dict:
    """Allowed values for the UI's edit controls (single source of truth: the schema)."""
    return {"panels": [p.value for p in Panel], "sides": [s.value for s in Side],
            "damage_types": [d.value for d in DamageType], "camera_views": [c.value for c in CameraView],
            "regions": ["low_cost", "standard", "high_cost"], "severities": [1, 2, 3, 4]}


@app.post("/api/claims", response_model=ClaimResult)
def create_claim(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    urls: list[str] = Form(default=[]),
    region: Literal["low_cost", "standard", "high_cost"] = Form(default="standard"),
    # Eval/debug only. Unset -> the server setting LLM_BASELINE_ENABLED (default off). The UI never sends it.
    include_llm_baseline: bool | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, max_length=200),
):
    """One claim = up to N photos, from uploads and/or URLs. Sync handler: FastAPI runs it in a
    worker thread, so the blocking model call doesn't stall the event loop."""
    rid = request.state.request_id
    ip = client_ip(request)
    if not LIMITER.allow(f"claims:{ip}", settings.rate_limit_claims_per_min):
        trigger("rate_limit_claims", ip=ip_hash(ip), request_id=rid)
        return JSONResponse({"error": MSG_RATE, "request_id": rid}, status_code=429)
    if idempotency_key and (prior := store.idem_get(idempotency_key)) and (stored := store.get_result(prior)):
        log_event("claim_idempotent_replay", request_id=rid, original_request_id=prior)
        return JSONResponse(stored)
    if not CONCURRENCY.try_acquire():
        trigger("concurrency_cap", ip=ip_hash(ip), request_id=rid)
        return JSONResponse({"error": MSG_BUSY, "request_id": rid}, status_code=503)
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
                log_event("url_fetch", request_id=rid, url=redact_url(u))
                images.append(fetch_image(u))
        result = run_claim(images, request_id=rid, region=region, include_llm_baseline=include_llm_baseline,
                           guard=DailyCapGuard(rid), use_cache=True)
    except IntakeError as e:
        log_event("claim_rejected", request_id=rid, reason=str(e))
        return JSONResponse({"request_id": rid, "status": "rejected", "error": str(e)}, status_code=400)
    except CapError as e:
        return JSONResponse({"request_id": rid, "status": "refused", "error": str(e)}, status_code=e.status)
    finally:
        CONCURRENCY.release()
    store.save_result(rid, result.model_dump_json())  # audit log: result only, never image bytes
    if idempotency_key:
        store.idem_put(idempotency_key, rid)
    u = result.usage
    log_event("claim_done", request_id=rid, status=result.status, routing=result.routing.outcome,
              gate_codes=result.gate.codes, flags=result.flags, model_id=result.audit.model_id,
              cost_usd=u.cost_usd if u else 0, cached=u.cached if u else False, latency_ms=result.latency_ms,
              n_photos=len(result.audit.input_hashes))
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


@app.get("/metrics")
def metrics() -> dict:
    """Summary from the audit log: outcomes, failure reasons, latency, spend, cache hits, limit triggers."""
    results = store.all_results()
    lat = sorted(r["latency_ms"] for r in results)
    p95 = lat[max(0, int(0.95 * len(lat) + 0.999) - 1)] if lat else None
    count = lambda key: dict(sorted(_counter(key(r) for r in results).items()))  # noqa: E731
    return {
        "claims_total": len(results),
        "by_status": count(lambda r: [r["status"]]),
        "by_routing": count(lambda r: [r["routing"]["outcome"]]),
        "gate_codes": count(lambda r: r["gate"].get("codes", [])),
        "flags": count(lambda r: r.get("flags", [])),
        "cache_hits": sum(1 for r in results if (r.get("usage") or {}).get("cached")),
        "latency_ms": {"n": len(lat), "p50": median(lat) if lat else None, "p95": p95},
        "model_spend_usd_total": round(sum((r.get("usage") or {}).get("cost_usd", 0) for r in results), 4),
        "usage_today": store.usage_today(),
        "caps": {"daily_call_cap": settings.daily_call_cap, "daily_spend_cap_usd": settings.daily_spend_cap_usd,
                 "max_concurrent_claims": settings.max_concurrent_claims},
        "limits_triggered_since_start": dict(TRIGGERS),
    }


def _counter(lists) -> dict:
    out: dict = {}
    for items in lists:
        for i in items:
            out[i] = out.get(i, 0) + 1
    return out


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)
