"""Summarize data/runs/latency_exp.jsonl.

Latency: n, p50, p95 (nearest-rank) per arm. Quality: there are no labels for DEV images, so
quality means AGREEMENT WITH THE BASELINE ARM, compared against the baseline's agreement with
itself across repeats (the noise floor). An arm "holds quality" if its agreement with the
baseline is close to that noise floor. This is consistency, not accuracy.
"""

import json
import math
from collections import Counter, defaultdict
from itertools import combinations
from statistics import mean, median

from app.schemas import BLOCKING_GATE_CODES

ROWS = [json.loads(line) for line in open("data/runs/latency_exp.jsonl")]


def p95(xs):
    xs = sorted(xs)
    return xs[max(0, math.ceil(0.95 * len(xs)) - 1)]


def jacc(a, b):
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def blocked(r):
    return any(c in {g.value for g in BLOCKING_GATE_CODES} for c in r["issues"])


def keys(r, level):
    if blocked(r):
        return set()
    if level == "panel":
        return {i[0] for i in r["items"]}
    return {(i[0], i[1], i[2]) for i in r["items"]}  # panel, side, type


def maxsev(r):
    return 0 if blocked(r) else max((i[3] for i in r["items"]), default=0)


ok = [r for r in ROWS if r["ok"]]
by = defaultdict(lambda: defaultdict(list))  # arm -> image -> rows
for r in ok:
    by[r["arm"]][r["image"]].append(r)
arms = list(dict.fromkeys(r["arm"] for r in ROWS))
base = by["baseline"]

print(f"Calls: {len(ROWS)} total, {len(ROWS) - len(ok)} failed. Images: {len(base)} DEV images. Model: claude-sonnet-5-5.\n")
print(f"{'arm':11} {'n':>3} {'p50 s':>6} {'p95 s':>6} {'max s':>6} {'>15s':>5} {'out tok':>8} {'$/call':>7} {'cue wds':>7} "
      f"{'gate=':>6} {'item J':>7} {'panel J':>8} {'maxsev=':>8} {'F1 left':>8}")
for arm in arms:
    rs = [r for img in by[arm].values() for r in img]
    lat = [r["latency_s"] for r in ROWS if r["arm"] == arm]
    gate, ij, pj, ms = [], [], [], []
    for img, rows in by[arm].items():
        brows = base[img]
        bmaj_block = Counter(blocked(b) for b in brows).most_common(1)[0][0]
        bmaj_sev = Counter(maxsev(b) for b in brows).most_common(1)[0][0]
        for r in rows:
            gate.append(blocked(r) == bmaj_block)
            ms.append(maxsev(r) == bmaj_sev)
            # vs every baseline run of the same image, excluding the identical call
            pairs = [b for b in brows if b is not r]
            ij += [jacc(keys(r, "item"), keys(b, "item")) for b in pairs]
            pj += [jacc(keys(r, "panel"), keys(b, "panel")) for b in pairs]
    f1 = by[arm].get("altima_accident", [])
    f1_left = sum(Counter(i[1] for i in r["items"]).most_common(1)[0][0] == "left" for r in f1 if r["items"])
    cues = [w for r in rs for w in r.get("cue_words", [])]
    print(f"{arm:11} {len(lat):>3} {median(lat):>6.1f} {p95(lat):>6.1f} {max(lat):>6.1f} {sum(x > 15 for x in lat):>5} "
          f"{mean(r['out_tok'] for r in rs):>8.0f} {mean(r['cost'] for r in rs):>7.4f} {mean(cues) if cues else 0:>7.1f} "
          f"{mean(gate):>6.0%} {mean(ij):>7.2f} {mean(pj):>8.2f} {mean(ms):>8.0%} {f1_left:>4}/{len(f1)}")

print("\nColumns: gate= / maxsev= : share of calls matching the baseline majority for that image. "
      "item J / panel J : mean Jaccard overlap with the baseline runs of the same image "
      "(items = panel+side+type). For the baseline row these are the baseline vs itself (noise floor). "
      "F1 left: runs on the F1 image whose majority side is 'left' (the correct answer).")
