"""Deterministic cost engine: damage items + versioned table -> low / mid / high range.

The LLM never supplies a number here. Inputs are the extracted (or adjuster-corrected) damage
items and vehicle make; every number comes from app/cost_table_v1.yaml (all assumptions,
except the sourced labor rate).
"""

from functools import lru_cache
from pathlib import Path

import yaml

from app.config import settings
from app.schemas import CostEstimate, CostLine, MergedDamageItem

TABLE_PATH = Path(__file__).parent / "cost_table_v1.yaml"
PARTIAL_LABEL = "partial, excludes severity-4 items"


@lru_cache
def load_table(path: Path = TABLE_PATH) -> dict:
    t = yaml.safe_load(path.read_text())
    t["_panel_class"] = {p: cls for cls, panels in t["panel_classes"].items() for p in panels}
    t["_rows"] = {(r["panel_class"], r["severity"]): r for r in t["rows"]}
    return t


def vehicle_class(make: str | None, t: dict) -> str:
    m = (make or "").strip().lower()
    if not m or m == "unknown":
        return "unknown"
    return "luxury_truck" if m in t["luxury_makes"]["makes"] else "mainstream"


def _round10(x: float) -> float:
    return float(round(x / 10) * 10)


def estimate(
    items: list[MergedDamageItem],
    make: str | None,
    region: str | None = None,
    vehicle_class_override: str | None = None,
    table: dict | None = None,
) -> CostEstimate:
    t = table or load_table()
    region = region or t["default_region"]
    rate = settings.labor_rate_usd_per_hour * t["regions"][region]["multiplier"]
    vclass = vehicle_class_override or vehicle_class(make, t)
    classes = t["vehicle_classes"]
    if vclass == "unknown":  # widen instead of guessing
        cls_lo, cls_hi = classes["economy"]["multiplier"], classes["luxury_truck"]["multiplier"]
    else:
        cls_lo = cls_hi = classes[vclass]["multiplier"]
    mat = t["materials_usd_per_refinish_hour"]

    # One priced line per physical part: (panel, side) at the highest severity seen.
    parts: dict[tuple, MergedDamageItem] = {}
    for it in items:
        key = (it.panel, it.side)
        if key not in parts or it.severity > parts[key].severity:
            parts[key] = it

    lines, not_estimable, unpriceable_panels = [], [], []
    lo_sum = hi_sum = 0.0
    any_replace = False
    for (panel, side), it in sorted(parts.items(), key=lambda kv: (-kv[1].severity, kv[0][0])):
        pclass = t["_panel_class"].get(panel.value, "not_estimable")
        if it.severity >= 4 or pclass == "not_estimable":
            why = "severity 4 (structural or safety)" if it.severity >= 4 else f"{panel.value} is never priced from a photo"
            if it.severity < 4:
                unpriceable_panels.append(panel.value)
            not_estimable.append(f"{side.value} {panel.value}: {why}")
            lines.append(CostLine(panel=panel, side=side, severity=it.severity, operation=None,
                                  low_usd=None, high_usd=None, driver=f"Not estimable: {side.value} {panel.value}, {why}. A human must assess."))
            continue
        row = t["_rows"][(pclass, it.severity)]
        (b_lo, b_hi), (r_lo, r_hi), (p_lo, p_hi) = row["body_hours"], row["refinish_hours"], row["parts_usd"]
        lo = (b_lo + r_lo) * rate + r_lo * mat["low"] + p_lo * cls_lo
        hi = (b_hi + r_hi) * rate + r_hi * mat["high"] + p_hi * cls_hi
        any_replace |= it.severity == 3
        lo_sum += lo
        hi_sum += hi
        lines.append(CostLine(
            panel=panel, side=side, severity=it.severity, operation=row["operation"],
            low_usd=_round10(lo), high_usd=_round10(hi),
            driver=(f"{row['operation']} {side.value} {panel.value} (severity {it.severity}): "
                    f"body {b_lo}-{b_hi} h, refinish {r_lo}-{r_hi} h at ${rate:.0f}/h, "
                    f"parts ${p_lo}-{p_hi} x class multiplier {cls_lo}-{cls_hi}"),
        ))

    uplift = t["hidden_damage_uplift"]["high_pct"] / 100 if any_replace else 0.0
    hi_total = hi_sum * (1 + uplift)
    common = dict(lines=lines, vehicle_class=vclass, region=region, labor_rate_usd_per_hour=round(rate, 2),
                  hidden_damage_uplift_applied=bool(uplift), caveats=t["caveats"], cost_table_version=t["version"])

    if not parts:
        return CostEstimate(status="no_damage", low_usd=0.0, mid_usd=0.0, high_usd=0.0,
                            partial_low_usd=None, partial_high_usd=None, partial_label=None,
                            not_estimable_reasons=[], **common)
    if not_estimable:
        # No total: the unpriced part has no upper bound we can defend. The priced part is
        # reported, always labeled as partial.
        label = PARTIAL_LABEL
        if unpriceable_panels:
            label += " and items on panels never priced from a photo (" + ", ".join(sorted(set(unpriceable_panels))) + ")"
        return CostEstimate(status="not_estimable", low_usd=None, mid_usd=None, high_usd=None,
                            partial_low_usd=_round10(lo_sum), partial_high_usd=_round10(hi_total),
                            partial_label=label, not_estimable_reasons=not_estimable, **common)
    floor = t["claim_minimum_usd"]["value"]
    low, high = _round10(lo_sum), _round10(hi_total)
    applied = low < floor
    low = max(low, floor)  # per-claim minimum on the low end
    high = max(high, low)
    return CostEstimate(status="estimated", low_usd=low, mid_usd=_round10((low + high) / 2), high_usd=high,
                        partial_low_usd=None, partial_high_usd=None, partial_label=None,
                        claim_minimum_applied=applied, not_estimable_reasons=[], **common)
