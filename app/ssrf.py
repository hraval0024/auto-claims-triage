"""Safe fetch of a user-supplied image URL (SSRF guard).

Defenses:
- Only http/https. No credentials in the URL.
- Every hostname is resolved and EVERY resolved address must be public (no private, loopback,
  link-local, CGNAT, reserved, multicast; IPv4-mapped IPv6 is unwrapped first).
- The check runs at CONNECT time inside the network backend, on the exact IP we connect to,
  so DNS rebinding between "check" and "connect" can't swap in an internal address.
- Redirects are followed manually (capped) and each hop goes through the same checks.
- Content-Type must be image/*, size is capped while streaming, and there's a total deadline.
- Environment proxies are ignored (httpcore doesn't read them), so they can't bypass the guard.
"""

import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpcore

from app.config import settings
from app.intake import IntakeError


class UrlFetchError(IntakeError):
    pass


def ip_allowed(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%", 1)[0])  # drop IPv6 zone id
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise UrlFetchError("Could not resolve the image URL's host.")
    return sorted({info[4][0] for info in infos})


class _GuardedBackend(httpcore.SyncBackend):
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ips = resolve(host, port)
        blocked = [ip for ip in ips if not ip_allowed(ip)]
        if not ips or blocked:
            raise UrlFetchError("That URL points to a private or internal address and was blocked.")
        # TLS SNI and certificate checks still use the original hostname (set by httpcore).
        return super().connect_tcp(ips[0], port, timeout, local_address, socket_options)


def redact_url(url: str) -> str:
    """For logs: keep scheme and host only (paths and queries may carry tokens)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname or '?'}/..."


def _validate(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UrlFetchError("Only http and https image URLs are allowed.")
    if not parts.hostname:
        raise UrlFetchError("The image URL has no host.")
    if parts.username or parts.password:
        raise UrlFetchError("URLs with embedded credentials are not allowed.")


DEFAULT_USER_AGENT = "auto-claims-triage-prototype/0.1"


def fetch_image(url: str, user_agent: str = DEFAULT_USER_AGENT) -> bytes:
    deadline = time.monotonic() + settings.url_fetch_timeout_s
    per_op = min(5.0, settings.url_fetch_timeout_s)
    timeouts = {"connect": per_op, "read": per_op, "write": per_op, "pool": per_op}
    headers = [(b"User-Agent", user_agent.encode()), (b"Accept", b"image/*")]
    max_bytes = settings.max_upload_bytes

    with httpcore.ConnectionPool(network_backend=_GuardedBackend(), retries=0) as pool:
        for _hop in range(settings.url_max_redirects + 1):
            _validate(url)
            try:
                with pool.stream("GET", url, headers=headers, extensions={"timeout": timeouts}) as resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        location = _header(resp, b"location")
                        if not location:
                            raise UrlFetchError("Redirect without a Location header.")
                        url = urljoin(url, location)
                        continue
                    if resp.status != 200:
                        raise UrlFetchError(f"The image URL returned HTTP {resp.status}.")
                    ctype = (_header(resp, b"content-type") or "").lower()
                    if not ctype.startswith("image/"):
                        raise UrlFetchError("The URL did not return an image.")
                    length = _header(resp, b"content-length")
                    if length and length.isdigit() and int(length) > max_bytes:
                        raise UrlFetchError("The image at that URL is too large.")
                    body = bytearray()
                    for chunk in resp.iter_stream():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise UrlFetchError("The image at that URL is too large.")
                        if time.monotonic() > deadline:
                            raise UrlFetchError("Fetching the image URL timed out.")
                    return bytes(body)
            except UrlFetchError:
                raise
            except httpcore.TimeoutException:
                raise UrlFetchError("Fetching the image URL timed out.")
            except (httpcore.NetworkError, httpcore.ProtocolError, httpcore.UnsupportedProtocol):
                raise UrlFetchError("Could not connect to the image URL.")
            if time.monotonic() > deadline:
                raise UrlFetchError("Fetching the image URL timed out.")
    raise UrlFetchError("Too many redirects.")


def _header(resp: httpcore.Response, name: bytes) -> str | None:
    for k, v in resp.headers:
        if k.lower() == name:
            return v.decode("latin-1")
    return None
