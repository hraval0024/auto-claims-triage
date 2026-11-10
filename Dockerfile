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

# Application code and the entrypoint only (tests, eval, docs, data are excluded by .dockerignore).
COPY app ./app
COPY docker/entrypoint.py ./docker/entrypoint.py

# Unprivileged app user with a fixed uid/gid (the entrypoint drops to these).
RUN groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid 10001 --no-create-home appuser \
    && mkdir -p /data && chown 10001:10001 /data

# Defaults for Railway; override with service variables. Secrets are NOT set here.
ENV PORT=8000 \
    DATA_DIR=/data \
    TRUST_PROXY_HOPS=1

EXPOSE 8000
# Starts as root ONLY so docker/entrypoint.py can hand the (root-owned) Railway volume at
# DATA_DIR to uid 10001; it then drops privileges for good and execs uvicorn as PID 1
# (--no-access-log, --no-server-header). The app never runs as root.
CMD ["/app/.venv/bin/python", "/app/docker/entrypoint.py"]
