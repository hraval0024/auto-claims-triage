"""Phase 5 live checks against a deployed URL. Reads LIVE_URL and APP_ACCESS_CODE from the
environment; never prints the code. Uses DEV sample images only (never the eval set).
Writes runs/phase5/live_<mode>_<timestamp>.json (no secrets).

Modes:
  main       healthz, 401 without code, upload claim, URL claim, gate refusal, 5 timed claims,
             a review correction (persistence marker), claims rate-limit demo, header/error leak check
  persist    after a restart/redeploy: time until /healthz is up (run it right after triggering the
             redeploy), the marker correction and claim count survived, first claim after restart
  spendcap   after temporarily lowering DAILY_CALL_CAP in Railway: one claim must be refused

Usage: LIVE_URL=https://... APP_ACCESS_CODE=... uv run python -m scripts.live_check main
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import httpx

URL = os.environ.get("LIVE_URL", "").rstrip("/")
CODE = os.environ.get("APP_ACCESS_CODE", "")
S = Path("data/samples")
OUT = Path("runs/phase5")
PACE_S = 11  # stay under the default 6 claims/min/IP so the rate limit only fires when we test it
LEAK_MARKERS = ["sk-ant-", "Traceback", "/Users/", "/app/app/", "site-packages", "ANTHROPIC_API_KEY"]


def leak_check(r: httpx.Response, found: list) -> None:
    blob = json.dumps(dict(r.headers)) + r.text
    for m in LEAK_MARKERS + ([CODE] if CODE else []):
        if m and m in blob:
            found.append(f"{r.request.method} {r.request.url.path} -> {r.status_code}: contains {'the access code' if m == CODE else repr(m)}")
    if "server" in {k.lower() for k in r.headers}:
        found.append(f"{r.request.url.path}: Server header present ({r.headers.get('server')})")


def claim(c: httpx.Client, files=None, urls=None):
    t = time.monotonic()
    r = c.post("/api/claims", files=files or [], data={"urls": urls} if urls else {})
    return r, round(time.monotonic() - t, 2)


def summarize(r: httpx.Response) -> dict:
    try:
        b = r.json()
    except ValueError:
        return {"http": r.status_code}
    out = {"http": r.status_code, "status": b.get("status"), "error": b.get("error")}
    if "routing" in b:
        u = b.get("usage") or {}
        out |= {"routing": b["routing"]["outcome"], "request_id": b["audit"]["request_id"], "server_latency_ms": b["latency_ms"],
                "cost_usd": u.get("cost_usd"), "cached": u.get("cached"), "gate_codes": b["gate"].get("codes")}
    return out


def save(mode: str, report: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"live_{mode}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"\nSaved {path}")


def main(mode: str) -> int:
    if not URL or not CODE:
        print("Set LIVE_URL and APP_ACCESS_CODE in the environment.")
        return 2
    leaks: list = []
    report: dict = {"mode": mode, "url": URL, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    anon = httpx.Client(base_url=URL, timeout=90)
    c = httpx.Client(base_url=URL, timeout=90, headers={"X-Access-Code": CODE})

    if mode == "main":
        r = anon.get("/healthz"); leak_check(r, leaks)
        report["healthz"] = {"http": r.status_code, "body": r.json()}
        r = anon.get("/api/vocab"); leak_check(r, leaks)
        report["no_code"] = {"http": r.status_code, "body": r.json()}
        r = anon.get("/api/vocab", headers={"X-Access-Code": "wrong-code-123456"}); leak_check(r, leaks)
        report["wrong_code"] = {"http": r.status_code, "body": r.json()}
        r = c.get("/"); leak_check(r, leaks)
        report["security_headers"] = {k: r.headers.get(k) for k in ("content-security-policy", "strict-transport-security",
                                                                     "x-frame-options", "x-content-type-options", "referrer-policy")}
        r = c.get("/nonexistent"); leak_check(r, leaks)
        report["unknown_route"] = {"http": r.status_code, "body": r.text[:200]}

        r, t = claim(c, files=[("files", open(S / "case1_clean_cirrus.jpg", "rb"))]); leak_check(r, leaks)
        report["upload_claim"] = summarize(r) | {"client_s": t}
        time.sleep(PACE_S)
        manifest = {e["id"]: e for e in json.load(open("samples/manifest.json"))["samples"]}
        r, t = claim(c, urls=manifest["case3_multidamage_starex"]["image_url"]); leak_check(r, leaks)
        report["url_claim"] = summarize(r) | {"client_s": t, "source": "Commons URL of DEV sample case3_multidamage_starex"}
        time.sleep(PACE_S)
        r, t = claim(c, files=[("files", open(S / "case5a_noncar_obvious.jpg", "rb"))]); leak_check(r, leaks)
        report["gate_refusal"] = summarize(r) | {"client_s": t}

        timed = []
        for f in ["case2_hard_pohang.jpg", "case4_night_crash.jpg", "case5b_noncar_borderline.jpg",
                  "case6_injection_cirrus.jpg", "case8_multiphoto_mercedes_a.jpg"]:
            time.sleep(PACE_S)
            r, t = claim(c, files=[("files", open(S / f, "rb"))]); leak_check(r, leaks)
            timed.append(summarize(r) | {"image": f, "client_s": t})
        lat = sorted(x["client_s"] for x in timed)
        report["timed_runs"] = timed
        report["latency_client_s"] = {"n": len(lat), "p50": median(lat), "p95_nearest_rank": lat[-1], "note": "n=5: p95 is the max"}
        costs = [x["cost_usd"] for x in [report["upload_claim"], report["url_claim"], report["gate_refusal"], *timed] if x.get("cost_usd")]
        report["cost_per_claim_usd"] = {"n": len(costs), "mean": round(sum(costs) / len(costs), 5) if costs else None,
                                        "min": min(costs) if costs else None, "max": max(costs) if costs else None}

        rid = report["upload_claim"].get("request_id")
        if rid:
            r = c.post(f"/api/claims/{rid}/review", json={"decision": "reject"}); leak_check(r, leaks)
            report["persistence_marker"] = {"request_id": rid, "review_http": r.status_code}
        m = c.get("/metrics").json()
        report["metrics"] = {k: m[k] for k in ("claims_total", "cache_hits", "latency_ms", "model_spend_usd_total", "usage_today",
                                               "by_routing", "limits_triggered_since_start")}

        time.sleep(61)  # fresh rate-limit window, then burst cheap empty requests (no model call)
        codes = [c.post("/api/claims").status_code for _ in range(8)]
        report["rate_limit_demo"] = {"burst_statuses": codes, "first_429_at": codes.index(429) + 1 if 429 in codes else None}
        r = c.post("/api/claims"); leak_check(r, leaks)
        report["rate_limit_message"] = r.json().get("error")

    elif mode == "persist":
        t0, up = time.monotonic(), None
        while time.monotonic() - t0 < 600:
            try:
                if anon.get("/healthz", timeout=5).status_code == 200:
                    up = round(time.monotonic() - t0, 1)
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        report["seconds_until_healthz_ok"] = up
        prior = sorted(OUT.glob("live_main_*.json"))
        marker = json.loads(prior[-1].read_text()).get("persistence_marker", {}).get("request_id") if prior else None
        corr = c.get("/api/corrections").json()
        report["marker_review_survived"] = bool(marker) and any(rv["request_id"] == marker for rv in corr["reviews"])
        report["claims_total_after_restart"] = c.get("/metrics").json()["claims_total"]
        r, t = claim(c, files=[("files", open(S / "case8_multiphoto_mercedes_b.jpg", "rb"))]); leak_check(r, leaks)
        report["first_claim_after_restart"] = summarize(r) | {"client_s": t}

    elif mode == "spendcap":
        r, t = claim(c, files=[("files", open(S / "case7c_screenshot_cc.png", "rb"))]); leak_check(r, leaks)
        report["capped_claim"] = summarize(r) | {"client_s": t}
        report["usage_today"] = c.get("/metrics").json()["usage_today"]
    else:
        print(f"unknown mode {mode}")
        return 2

    report["leaks_found"] = leaks
    save(mode, report)
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "main"))
