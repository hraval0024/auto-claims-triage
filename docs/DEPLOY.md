# Deploy (Railway)

Railway builds the `Dockerfile` (selected by `railway.json`), runs 1 replica, and health-checks
`/healthz`. The app refuses to start if `ANTHROPIC_API_KEY` or `APP_ACCESS_CODE` is missing or
`DATA_DIR` is not writable; the error is in the deploy logs.

## Environment variables (Railway service → Variables)

| Variable | Required | Value |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Paste in Railway only. Never in the repo or chat. |
| `APP_ACCESS_CODE` | yes | At least 12 characters. Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `DATA_DIR` | yes | `/data` (the volume mount; also the image default) |
| `DAILY_CALL_CAP` | yes | Model calls per UTC day across all users, e.g. `150` |
| `DAILY_SPEND_CAP_USD` | no | Default `5.00`. Fails closed like the call cap. |
| `TRUST_PROXY_HOPS` | no | Default `1` in the image (Railway's edge proxy). See untested items. |
| `MAX_CONCURRENT_CLAIMS`, `RATE_LIMIT_CLAIMS_PER_MIN`, `RATE_LIMIT_LOGIN_PER_MIN`, `RATE_LIMIT_REQUESTS_PER_MIN` | no | Defaults 3 / 6 / 10 / 120 |
| `MODEL_ID`, `MODEL_EFFORT`, `CLAIM_DEADLINE_S` | no | Defaults `claude-sonnet-5-5` / `medium` / `60` |
| `URL_FETCH_USER_AGENT` | no | Set if an image host blocks generic clients (Wikimedia asks for contact details). |
| `LLM_BASELINE_ENABLED` | no | Leave unset (off) in production. |

## Volume

Mount a volume at `/data`. It holds `app.db`: request audit log, corrections, daily usage ledger,
model-output cache, idempotency keys. No images are ever written. Without the volume, all of this
resets on every redeploy, including the daily caps.

Railway mounts the volume root-owned. The container therefore starts as root ONLY to run
`docker/entrypoint.py`, which hands `DATA_DIR` to uid/gid 10001 (never following symlinks),
permanently drops privileges, refuses to continue if still root, and execs uvicorn. The app
process never runs as root. `DATA_DIR` must be the absolute path `/data` (a relative `data`
resolves to `/app/data`, which the app user can't create).

## Redeploy

Push to `main` (if auto-deploy is on) or press **Redeploy** in the service. The volume survives;
in-memory rate-limit counters reset.

## Rotate the access code

Change `APP_ACCESS_CODE` and redeploy. Session cookies are an HMAC of the code, so every existing
session stops working at once; users re-enter the new code.

## Rotate the API key

1. Create a new key in the Anthropic Console.
2. Set `ANTHROPIC_API_KEY` in Railway to the new key; redeploy; check `/healthz` and one claim.
3. Revoke the old key in the Console.

## Versions to expect

Every claim's audit details record the versions it ran with. Current: `schema_version` **1.3.0**,
`routing.rules_version` **routing_v1.1** (adds secondary `routing.notes`, e.g. "Better photos of the
right wheel and right fender would help", without changing any outcome), `prompt_version`
extract_v2, `cost_table_version` cost_table_v1. After a deploy, one claim's audit details confirm
which code is live.

## Check a deployment

`LIVE_URL=https://<domain> APP_ACCESS_CODE=<code> uv run python -m scripts.live_check main`
(also `persist` right after a redeploy, and `spendcap` after temporarily lowering `DAILY_CALL_CAP`).
Results go to `runs/phase5/`; the code is never printed or saved.

## Dockerfile review (not built locally: Docker is not installed)

| Line | What it does | Risk / status |
|---|---|---|
| `FROM python:3.12-slim` | Debian slim, Python 3.12 (matches `.python-version`) | Untested: tag resolves at build time (not digest-pinned). Pillow and uvloop install as manylinux wheels, so no compiler needed. |
| `COPY --from=ghcr.io/astral-sh/uv:0.11.7` | Pinned uv, same as the one that wrote `uv.lock` | Untested pull from ghcr.io on Railway. |
| `ENV ... UV_PYTHON_DOWNLOADS=never, UV_PROJECT_ENVIRONMENT=/app/.venv` | Use the image's Python; venv at a fixed path | Replayed locally (same flags). |
| `COPY pyproject.toml uv.lock .python-version` + `uv sync --frozen --no-dev --no-install-project` | Exact locked runtime deps, cached layer | Replayed locally: syncs, no pytest in the runtime env. |
| `COPY app ./app` | Only the app; `.dockerignore` drops tests, eval, data, images, docs, `.git`, `.env*` | Replayed: `app/` imports nothing outside itself. |
| `groupadd/useradd ... 10001` | Unprivileged app user with a fixed uid/gid | No `USER` line: the entrypoint drops to 10001 after fixing volume ownership. |
| `COPY docker/entrypoint.py` | Root -> chown DATA_DIR -> drop to 10001 -> exec uvicorn | Root path unit-tested with recorded OS calls (no sudo/Docker here); non-root path run for real. |
| `ENV PORT=8000 DATA_DIR=/data TRUST_PROXY_HOPS=1` | Defaults; Railway injects `PORT` | No secrets in the image. |
| `CMD python docker/entrypoint.py` | Entrypoint reads `PORT`, execs uvicorn as PID 1 (`--no-access-log --no-server-header`) | Replayed locally via the entrypoint: `/healthz` writable, startup logged. |
