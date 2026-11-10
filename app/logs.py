"""Structured JSON logs (one object per line, to stdout), with a request id on every event.

Never logged: images or image bytes, the API key, the access code, full URLs (only scheme +
host via app.ssrf.redact_url), raw client IPs (a salted hash instead). As a second line of
defense, every record is scrubbed for the key, the code and base64 image data before output.
"""

import hashlib
import json
import logging
import re
import secrets
import sys
from datetime import datetime, timezone

from app.config import settings

_SALT = secrets.token_bytes(16)  # per process: hashes correlate within a run, not across
_B64_IMAGE = re.compile(r"(/9j/|iVBORw0KGgo|UklGR)[A-Za-z0-9+/=]{20,}")  # JPEG / PNG / WebP base64
_SK = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")

logger = logging.getLogger("claims")


def ip_hash(ip: str) -> str:
    return hashlib.sha256(_SALT + ip.encode()).hexdigest()[:12]


def scrub(text: str) -> str:
    for secret in (settings.anthropic_api_key, settings.app_access_code):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = _SK.sub("[REDACTED]", text)
    return _B64_IMAGE.sub("[IMAGE-DATA-REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "level": record.levelname,
                 "event": record.getMessage()}
        event.update(getattr(record, "fields", {}))
        return scrub(json.dumps(event, default=str))


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for noisy in ("httpx", "httpcore", "anthropic"):  # never let library debug logs dump request bodies
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})
