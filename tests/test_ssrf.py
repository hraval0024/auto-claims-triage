import io
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PIL import Image

from app import ssrf
from app.ssrf import UrlFetchError, fetch_image, ip_allowed


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.1", "172.16.5.4", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
     "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "224.0.0.1"],
)
def test_internal_ips_blocked(ip):
    assert not ip_allowed(ip)


@pytest.mark.parametrize("ip", ["8.8.8.8", "151.101.1.69", "2606:4700:4700::1111"])
def test_public_ips_allowed(ip):
    assert ip_allowed(ip)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x.jpg",
        "http://localhost/x.jpg",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "http://10.0.0.5/x.jpg",
        "http://[::1]/x.jpg",
        "http://2130706433/x.jpg",  # decimal-encoded 127.0.0.1
        "http://0x7f.0.0.1/x.jpg",  # hex-encoded loopback
    ],
)
def test_direct_internal_urls_blocked(url):
    with pytest.raises(UrlFetchError, match="private or internal|resolve"):
        fetch_image(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x.jpg", "gopher://example.com/", "http://user:pw@example.com/x.jpg"])
def test_bad_schemes_and_credentials_blocked(url):
    with pytest.raises(UrlFetchError):
        fetch_image(url)


# ---- Redirect tests: a local server plays the "public" host; redirect targets are internal. ----

def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(buf, format="JPEG")
    return buf.getvalue()


class _Handler(BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):
        status, headers, body = self.routes.get(self.path, (404, {}, b""))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    _Handler.routes = {
        "/ok.jpg": (200, {"Content-Type": "image/jpeg"}, _jpeg()),
        "/html": (200, {"Content-Type": "text/html"}, b"<html></html>"),
        "/to-metadata": (302, {"Location": "http://169.254.169.254/latest/meta-data/"}, b""),
        "/to-private": (301, {"Location": "http://10.0.0.5/x.jpg"}, b""),
        "/to-ipv6-loopback": (307, {"Location": "http://[::1]/x.jpg"}, b""),
        "/to-file": (302, {"Location": "file:///etc/passwd"}, b""),
        "/loop": (302, {"Location": "/loop"}, b""),
    }
    # Treat exactly 127.0.0.1 as "public" so the test server is reachable; the real rule
    # still applies to every other address, including redirect targets.
    real = ssrf.ip_allowed
    monkeypatch.setattr(ssrf, "ip_allowed", lambda ip: ip == "127.0.0.1" or real(ip))
    yield base
    srv.shutdown()


def test_allowed_fetch_returns_image(server):
    assert fetch_image(server + "/ok.jpg") == _jpeg()


@pytest.mark.parametrize("path", ["/to-metadata", "/to-private", "/to-ipv6-loopback"])
def test_redirect_to_internal_address_blocked(server, path):
    with pytest.raises(UrlFetchError, match="private or internal"):
        fetch_image(server + path)


def test_redirect_to_file_scheme_blocked(server):
    with pytest.raises(UrlFetchError, match="Only http and https"):
        fetch_image(server + "/to-file")


def test_redirect_cap(server):
    with pytest.raises(UrlFetchError, match="Too many redirects"):
        fetch_image(server + "/loop")


def test_non_image_content_type_rejected(server):
    with pytest.raises(UrlFetchError, match="did not return an image"):
        fetch_image(server + "/html")


def test_size_cap_enforced(server, monkeypatch):
    monkeypatch.setattr(ssrf.settings, "max_upload_bytes", 100)
    with pytest.raises(UrlFetchError, match="too large"):
        fetch_image(server + "/ok.jpg")


def test_redact_url_drops_path_and_query():
    assert ssrf.redact_url("https://cdn.example.com/a/b.jpg?token=SECRET") == "https://cdn.example.com/..."
