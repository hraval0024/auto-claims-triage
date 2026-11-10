"""Access gate, client IP, security headers.

Access: every route except /healthz and /login needs the shared access code, either as the
X-Access-Code header (scripts) or as a session cookie set by POST /login (the UI). The cookie
holds an HMAC token derived from the code, never the code itself, so rotating APP_ACCESS_CODE
invalidates every session. All comparisons are constant-time. The code is never put in a URL.
"""

import hashlib
import hmac

from starlette.requests import Request

from app.config import settings

COOKIE = "claims_session"
EXEMPT = {"/healthz", "/login"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                                "form-action 'self'; object-src 'none'"),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def session_token() -> str:
    return hmac.new(settings.app_access_code.encode(), b"claims-session-v1", hashlib.sha256).hexdigest()


def code_ok(candidate: str | None) -> bool:
    if not candidate or not settings.app_access_code:
        return False
    return hmac.compare_digest(candidate.encode(), settings.app_access_code.encode())


def authorized(request: Request) -> bool:
    if code_ok(request.headers.get("x-access-code")):
        return True
    cookie = request.cookies.get(COOKIE)
    return bool(cookie) and bool(settings.app_access_code) and hmac.compare_digest(cookie.encode(), session_token().encode())


def client_ip(request: Request) -> str:
    """With trust_proxy_hops = N, the client is the Nth address from the RIGHT of
    X-Forwarded-For (entries to its left can be forged by the client). Otherwise the socket peer."""
    hops = settings.trust_proxy_hops
    if hops > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


def is_https(request: Request) -> bool:
    if settings.trust_proxy_hops > 0 and request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https":
        return True
    return request.url.scheme == "https"
