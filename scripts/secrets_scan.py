"""Scan the working tree and the FULL git history for secrets, images and data files.

- Every blob ever committed (all branches, all versions) and every tracked or untracked-but-
  not-ignored file in the working tree is scanned for known key formats and high-entropy tokens.
- Every path ever committed is checked for images, data/ content and .env files.
- .env must be untracked and ignored.
Writes docs/secrets_scan.txt with the scanned commit hash. Prints matches masked (first 8 chars).

Usage: uv run python -m scripts.secrets_scan
"""

import math
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PATTERNS = {
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "key_assignment": re.compile(r"(?i)(api[_-]?key|secret|access[_-]?code|password|token)\s*[=:]\s*['\"]([^'\"\s]{16,})['\"]"),
}
TOKEN = re.compile(r"[A-Za-z0-9+/_\-=.]{20,}")
SEGMENT = re.compile(r"[/_\-.=]")
ENTROPY_MIN = 4.5  # whole tokens with no separators; hex digests max out at 4.0
SEG_LEN, SEG_ENTROPY = 16, 3.5  # a long, mixed-character, high-entropy run inside a token
IMAGE_EXT = re.compile(r"\.(jpe?g|png|webp|heic|gif|bmp|tiff?)$", re.I)
# Known fakes in tests (all zeros / obviously fake). Listed in the report, never hidden.
ALLOW = {"sk-ant-test-0000000000000000", "test-access-code-0123456789"}


def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def entropy(s: str) -> float:
    c = Counter(s)
    return -sum(n / len(s) * math.log2(n / len(s)) for n in c.values())


def scan_text(text: str) -> list[tuple[str, str]]:
    hits = []
    for name, rx in PATTERNS.items():
        for m in rx.finditer(text):
            val = m.group(2) if name == "key_assignment" else m.group(0)
            hits.append((name, val))
    for m in TOKEN.finditer(text):
        t = m.group(0)
        if suspicious(t):
            hits.append(("high_entropy", t))
    return hits


def suspicious(t: str) -> bool:
    """URL paths, file names and identifiers are made of words or hex; a secret is a run of
    mixed letters and digits with high entropy."""
    def mixed(x: str) -> bool:
        return bool(re.search(r"[A-Za-z]", x)) and bool(re.search(r"[0-9]", x))

    def hexonly(x: str) -> bool:
        return bool(re.fullmatch(r"[0-9a-fA-F]+", x))

    # 1) Tokens without dots (URLs and dotted names have them; base64 and URL-safe secrets don't):
    #    score the whole token, unless it is mostly real words (a file name such as
    #    Car_accident_on_Airways_Blvd). 4.5 bits/char is above ordinary English text.
    if "." not in t and len(t) >= 32 and not hexonly(t):
        parts = re.split(r"[_\-=/+]", t)
        # words, short numbers and hex digests (e.g. a package hash inside a path) are not secret material
        wordy = sum(len(p) for p in parts if re.fullmatch(r"[A-Z]?[a-z]{2,}|[A-Z]{2,}|[0-9]{1,4}|[0-9a-f]{8,}", p))
        if entropy(t) >= ENTROPY_MIN and wordy < 0.5 * len(t):
            return True
    # 2) Inside paths and dotted names: any long mixed segment with high entropy.
    for seg in SEGMENT.split(t):
        # random secrets mix upper and lower case or carry several digits; archive identifiers
        # such as catalogueofbronz00brit (lowercase words + 2 digits) do not
        varied = (bool(re.search(r"[a-z]", seg)) and bool(re.search(r"[A-Z]", seg))) or len(re.findall(r"[0-9]", seg)) >= 3
        if len(seg) >= SEG_LEN and mixed(seg) and varied and entropy(seg) >= SEG_ENTROPY and not hexonly(seg):
            return True
    return False


def self_test() -> None:
    """The rule must catch realistic secrets. Deterministic (seeded); nothing is stored."""
    import random
    import string

    rng = random.Random(20261110)
    urlsafe = string.ascii_letters + string.digits + "-_"
    b64 = string.ascii_letters + string.digits + "+/"
    gen = lambda alphabet, n: "".join(rng.choice(alphabet) for _ in range(n))  # noqa: E731
    fakes = [gen(urlsafe, 43) for _ in range(150)] + [gen(b64, 40) for _ in range(100)]
    fakes += ["sk-ant-api03-" + gen(urlsafe, 40) for _ in range(20)]
    fakes += ["AKIA" + gen(string.ascii_uppercase + "234567", 16) for _ in range(15)]
    fakes += ["ghp_" + gen(string.ascii_letters + string.digits, 36) for _ in range(15)]
    missed = [f[:6] for f in fakes if not scan_text(f"value = {f}")]
    assert not missed, f"detector missed {len(missed)} of {len(fakes)} generated secrets"
    for benign in ("Car_accident_on_Airways_Blvd_Memphis_TN_2013-05-02", "Image.DecompressionBombWarning",
                   "org/packages/10/bf/d1f6b81709538f831ebe1c42f50fb89db3dfda06f9e9b1ea24e90fc69209/pydantic_core-2"):
        assert not suspicious(benign), benign
    assert not scan_text("Identifier: triumphswonderso01boyd (find matches)")


def mask(v: str) -> str:
    return v[:8] + "…" + f"(len {len(v)})"


def main() -> None:
    self_test()
    head = git("rev-parse", "HEAD").strip()
    findings, allowed = [], set()

    # 1) every blob ever committed
    objs = [line.split(" ", 1) for line in git("rev-list", "--objects", "--all").splitlines() if " " in line]
    blobs = {sha: path for sha, path in objs}
    for sha, path in blobs.items():
        if git("cat-file", "-t", sha).strip() != "blob":
            continue
        data = git("cat-file", "-p", sha, binary=True)
        if b"\x00" in data[:8000]:
            continue  # binary blob: covered by the path check below
        for kind, val in scan_text(data.decode("utf-8", "replace")):
            (allowed.add((kind, val, path)) if val in ALLOW else findings.append(("history", kind, path, val)))

    # 2) working tree: tracked + untracked-but-not-ignored
    files = git("ls-files").splitlines() + git("ls-files", "--others", "--exclude-standard").splitlines()
    for f in files:
        p = Path(f)
        if not p.is_file():
            continue
        data = p.read_bytes()
        if b"\x00" in data[:8000]:
            continue
        for kind, val in scan_text(data.decode("utf-8", "replace")):
            (allowed.add((kind, val, f)) if val in ALLOW else findings.append(("worktree", kind, f, val)))

    # 3) paths ever committed
    paths = sorted({p for p in git("log", "--all", "--name-only", "--pretty=format:").splitlines() if p})
    bad_paths = [p for p in paths if IMAGE_EXT.search(p) or p.startswith("data/") or re.search(r"(^|/)\.env($|\.)", p)
                 and not p.endswith(".env.example")]

    # 4) .env status
    env_tracked = bool(git("ls-files", ".env").strip())
    env_ignored = subprocess.run(["git", "check-ignore", "-q", ".env"]).returncode == 0
    env_ever = [p for p in paths if p == ".env"]

    commits = len(git("rev-list", "--all").split())
    ok = not findings and not bad_paths and not env_tracked and env_ignored and not env_ever
    lines = [
        f"Secrets scan: {'CLEAN' if ok else 'FINDINGS - see below'}",
        f"Scanned commit (HEAD): {head}",
        f"Scanned at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"History: {commits} commits, {len(blobs)} objects ({sum(1 for _ in blobs)} paths/versions) - every text blob ever committed",
        f"Working tree: {len(files)} files (tracked + untracked-not-ignored)",
        "Patterns: " + ", ".join(PATTERNS) + f", high-entropy secrets (dot-free tokens >= 32 chars, "
        f">= {ENTROPY_MIN} bits/char, not mostly words; segments of paths/dotted names >= {SEG_LEN} chars mixing letters "
        f"and digits, >= {SEG_ENTROPY} bits/char; hex digests excluded)",
        "Self-test (seeded, 300 generated secrets: 150 URL-safe, 100 base64 with '/', 20 Anthropic-format, 15 AWS, 15 GitHub): all caught; known benign shapes not flagged.",
        "First pass (2026-11-10, whole-token entropy rule): 73 distinct high-entropy hits, all reviewed by hand and all non-secret:",
        "  50 PyPI package URLs (uv.lock), 19 Wikimedia URL paths (manifests), 3 image file names, 1 code identifier.",
        "  Second pass flagged 11 code identifiers (Image.DecompressionBombWarning, httpcore.ConnectionPool/TimeoutException,",
        "  and the scanner's own alphabet literal). The rule now scores separator-delimited segments that mix letters and",
        "  digits, and scores dot-free tokens whole unless mostly words. A seeded self-test of 300 generated secrets found 2",
        "  misses in an intermediate version (base64 split by '/', a digit-free token); both shapes are now caught.",
        "  A fourth pass flagged 2 Internet Archive identifiers in eval/candidates_raw.json (catalogueofbronz00brit,",
        "  triumphswonderso01boyd); segments must now mix upper and lower case or carry 3+ digits. This report is the final scan.",
        "",
        f"Key/secret findings: {len(findings)}",
        *[f"  - [{where}] {kind} in {path}: {mask(val)}" for where, kind, path, val in findings],
        f"Image, data/ or .env paths ever committed: {len(bad_paths)}",
        *[f"  - {p}" for p in bad_paths],
        f".env tracked now: {env_tracked}; .env ignored: {env_ignored}; .env ever committed: {bool(env_ever)}",
        "",
        "Known test fakes (matched a pattern, deliberately allowed, listed for transparency):",
        *sorted({f"  - {kind} in {path}: {val}" for kind, val, path in allowed}),
    ]
    Path("docs/secrets_scan.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
