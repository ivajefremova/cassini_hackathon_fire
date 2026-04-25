"""
AquaFire — Forecast Engine
Reads lake_upstream_stats.json (produced by sentinel_pipeline.py)
and computes month-by-month contamination load forecasts.
"""

import os
import json
import math
import sys
from datetime import date
from dateutil.relativedelta import relativedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    CORINE_TO_CATEGORY, DECAY_CONSTANTS, SEVERITY_MULTIPLIER,
    RISK_THRESHOLDS, DEFAULT_THRESHOLD, SEVERITY_LABELS,
    STATS_FILE, IGNITION_DATE, FIRE_NAME, FIRE_REGION,
    FIRE_TOTAL_HA, COPERNICUS_REF,
)


# ── Load lake stats ───────────────────────────────────────────────────────────

def load_lake_stats() -> dict:
    """
    Load lake upstream stats from JSON file produced by sentinel_pipeline.py.
    Raises a clear error if the pipeline hasn't been run yet.
    """
    if not os.path.exists(STATS_FILE):
        raise FileNotFoundError(
            f"Stats file not found: {STATS_FILE}\n"
            "Run the Sentinel pipeline first:\n"
            "    python sentinel_pipeline.py"
        )
    with open(STATS_FILE) as f:
        return json.load(f)


# ── Core math ─────────────────────────────────────────────────────────────────

def _decay(month: int, decay_class: str) -> float:
    """Negative exponential decay. Month 1 = peak (factor = 1.0)."""
    k = DECAY_CONSTANTS[decay_class]
    return math.exp(-k * (month - 1))


def _risk_label(contaminant: str, load_kg: float) -> str:
    t = RISK_THRESHOLDS.get(contaminant, DEFAULT_THRESHOLD)
    if load_kg >= t["high"]:       return "high"
    elif load_kg >= t["moderate"]: return "moderate"
    elif load_kg > 0.001:          return "low"
    return "none"


def _month_label(ignition_str: str, offset: int) -> str:
    """'October 2024' style label for offset months after ignition."""
    d = date.fromisoformat(ignition_str) + relativedelta(months=offset)
    return d.strftime("%B %Y")


def _trigger(m: int) -> str:
    if m == 1:   return "First autumn rain — peak mobilisation of ash and burned soil"
    elif m == 2: return "Secondary runoff — continued leaching from exposed soil"
    elif m <= 4: return "Ongoing leaching — load diminishing as soil stabilises"
    else:        return "Residual contamination — revegetation reducing runoff"


# ── Monthly forecast ──────────────────────────────────────────────────────────

def compute_monthly_forecast(
    upstream_burned: dict,
    ignition_str: str,
    forecast_months: int = 6,
) -> list[dict]:
    """
    Compute month-by-month contaminant load for a lake.

    upstream_burned: {category_key: {"ha": float, "mean_severity": int}}
    Returns list of monthly dicts with contaminant loads and risk labels.
    """
    monthly = []

    for m in range(1, forecast_months + 1):
        contaminants = {}
        total_load = 0.0

        for cat_key, burn_data in upstream_burned.items():
            if cat_key not in CORINE_TO_CATEGORY:
                continue
            cat        = CORINE_TO_CATEGORY[cat_key]
            ha         = burn_data["ha"]
            sev        = burn_data["mean_severity"]
            sev_mult   = SEVERITY_MULTIPLIER.get(sev, 1.0)
            decay_fac  = _decay(m, cat["decay_class"])

            for name, ef in cat["emission_factors"].items():
                load = ha * ef * sev_mult * decay_fac
                if load < 0.001:
                    continue
                contaminants[name] = contaminants.get(name, 0.0) + load
                total_load += load

        # Build output with risk labels, sorted by load
        contaminant_details = {
            name: {
                "load_kg": round(load, 2),
                "risk":    _risk_label(name, load),
            }
            for name, load in sorted(contaminants.items(), key=lambda x: -x[1])
        }

        dominant = next(iter(contaminant_details), None)

        monthly.append({
            "month":                m,
            "label":                _month_label(ignition_str, m),
            "contaminants":         contaminant_details,
            "total_load_kg":        round(total_load, 2),
            "dominant_contaminant": dominant,
            "trigger":              _trigger(m),
        })

    return monthly


def _peak_and_safe(monthly: list[dict]) -> tuple[int, int]:
    """Return (peak_month, safe_after_month) from a monthly forecast list."""
    peak = max(monthly, key=lambda x: x["total_load_kg"])["month"]
    safe = len(monthly)
    for entry in monthly:
        if all(v["risk"] in ("low", "none") for v in entry["contaminants"].values()):
            safe = entry["month"] - 1
            break
    return peak, safe


def _recommendations(
    lake_name: str,
    upstream_burned: dict,
    monthly: list[dict],
    peak_month: int,
    safe_after: int,
) -> list[str]:
    recs = []
    peak = monthly[peak_month - 1]
    recs.append(
        f"Peak contamination load of {peak['total_load_kg']:.0f} kg expected in "
        f"{peak['label']}. Risk diminishes significantly by month {safe_after + 1}."
    )
    if "forest_shrub" in upstream_burned:
        ha = upstream_burned["forest_shrub"]["ha"]
        recs.append(
            f"{ha:,.0f} ha of burned forest/shrubland drains upstream. "
            "PAH and organic carbon peaks in month 1 then decays ~35%/month. "
            "Prepare activated carbon water treatment before first rain."
        )
    if "agricultural" in upstream_burned:
        ha = upstream_burned["agricultural"]["ha"]
        recs.append(
            f"{ha:,.0f} ha of agricultural land burned upstream. "
            "Pesticide residues and elevated nitrates/copper/zinc expected months 1–3. "
            f"Suspend irrigation from {lake_name} until water quality is confirmed."
        )
    if "industrial_mining" in upstream_burned:
        ha = upstream_burned["industrial_mining"]["ha"]
        recs.append(
            f"WARNING: {ha:,.0f} ha of industrial/mining land burned upstream. "
            "Heavy metal contamination (As, Pb, Cd) is persistent — decays ~10%/month. "
            "Do not use this water without laboratory testing."
        )
    if "urban_fringe" in upstream_burned:
        recs.append(
            "Urban fringe material burned upstream. "
            "VOC and benzene load expected — run standard water quality panel."
        )
    recs.append(
        f"Test water at {lake_name} inlet after each rainfall event "
        f"exceeding 15mm during the first {safe_after} months post-fire."
    )
    return recs


# ── Main forecast function ────────────────────────────────────────────────────

def forecast_lake(lake_key: str, forecast_months: int = 6) -> dict:
    """
    Full forecast for a named lake.
    Reads real Sentinel-2 derived stats from lake_upstream_stats.json.

    Parameters
    ----------
    lake_key : str
        'stymfalia' or 'doxa'
    forecast_months : int
        How many months to project forward (1–24)

    Returns
    -------
    dict — complete API response
    """
    all_stats = load_lake_stats()

    if lake_key not in all_stats:
        raise ValueError(
            f"Unknown lake '{lake_key}'. Available: {list(all_stats.keys())}"
        )

    lake        = all_stats[lake_key]
    upstream    = lake["upstream_burned"]
    ignition    = lake.get("ignition_date", IGNITION_DATE)

    monthly     = compute_monthly_forecast(upstream, ignition, forecast_months)
    peak_month, safe_after = _peak_and_safe(monthly)
    recs        = _recommendations(lake["name"], upstream, monthly, peak_month, safe_after)

    # Upstream summary with labels
    upstream_summary = {}
    total_burned_ha  = 0
    for cat_key, burn_data in upstream.items():
        cat = CORINE_TO_CATEGORY.get(cat_key, {})
        upstream_summary[cat_key] = {
            "label":               cat.get("label", cat_key),
            "ha":                  burn_data["ha"],
            "mean_severity":       SEVERITY_LABELS.get(burn_data["mean_severity"], "unknown"),
            "primary_contaminants": cat.get("contaminants", []),
        }
        total_burned_ha += burn_data["ha"]

    # Overall status
    peak_entry           = monthly[peak_month - 1]
    high_risk_contams    = [
        n for n, v in peak_entry["contaminants"].items() if v["risk"] == "high"
    ]
    status = (
        "high_risk"     if high_risk_contams else
        "moderate_risk" if any(v["risk"] == "moderate"
                               for v in peak_entry["contaminants"].values()) else
        "low_risk"
    )

    return {
        "location":          lake["name"],
        "coordinates":       {"lon": lake["lon"], "lat": lake["lat"]},
        "elevation_m":       lake["elevation_m"],
        "lake_type":         lake["type"],
        "protected_area":    lake["protected"],
        "primary_use":       lake["primary_use"],
        "fire_event": {
            "name":              FIRE_NAME,
            "ignition_date":     ignition,
            "region":            FIRE_REGION,
            "total_fire_ha":     FIRE_TOTAL_HA,
            "copernicus_ref":    COPERNICUS_REF,
            "upstream_burned_ha": total_burned_ha,
        },
        "satellite_data": {
            "source":               "Sentinel-2 L2A",
            "data_source":          lake.get("data_source", "unknown"),
            "catchment_total_ha":   lake.get("catchment_total_ha"),
            "catchment_burned_ha":  lake.get("catchment_burned_ha"),
            "burned_fraction_pct":  round(lake.get("burned_fraction", 0) * 100, 1),
            "mean_dnbr":            lake.get("mean_dnbr"),
            "mean_severity_class":  lake.get("mean_severity_class"),
            "severity_breakdown_ha": lake.get("severity_breakdown_ha"),
        },
        "status":                status,
        "high_risk_contaminants": high_risk_contams,
        "burned_land_upstream":   upstream_summary,
        "monthly_forecast":       monthly,
        "peak_risk_month":        peak_month,
        "peak_risk_label":        monthly[peak_month - 1]["label"],
        "safe_after_month":       safe_after,
        "forecast_months":        forecast_months,
        "recommendations":        recs,
        "generated_at":           __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }
