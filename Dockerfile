# NOT BUILT LOCALLY: Docker is not installed on the dev machine. Railway builds this file
# (railway.json -> builder DOCKERFILE). Line-by-line review: docs/DEPLOY.md.
FROM python:3.12-slim

# uv, pinned to the version used to create uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first (cached layer), exactly as locked; no dev dependencies.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code only (tests, eval, docs, data are excluded by .dockerignore).
COPY app ./app

# Run as an unprivileged user. /data is where Railway mounts the volume.
RUN useradd --system --uid 10001 --no-create-home appuser \
    && mkdir -p /data && chown appuser /data
USER appuser

# Defaults for Railway; override with service variables. Secrets are NOT set here.
ENV PORT=8000 \
    DATA_DIR=/data \
    TRUST_PROXY_HOPS=1

EXPOSE 8000
# exec: uvicorn is PID 1 and gets SIGTERM on redeploy. No access log (the app logs its own
# JSON lines without query strings); no Server header.
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log --no-server-header"]
