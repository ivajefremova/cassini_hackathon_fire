"""
AquaFire API — Real Sentinel-2 data edition
Corinthia wildfire, 29 September 2024

Run sentinel_pipeline.py FIRST, then:
    uvicorn api:app --reload --port 8000

Endpoints:
    GET  /                          health check
    GET  /lakes                     lake metadata + satellite stats
    GET  /api/forecast/stymfalia    6-month forecast, Lake Stymfalia
    GET  /api/forecast/doxa         6-month forecast, Lake Doxa
    GET  /api/compare               side-by-side both lakes
    GET  /api/demo                  full pitch demo output
    POST /api/contamination-forecast  generic forecast endpoint
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from engine.forecast import forecast_lake, load_lake_stats
from config import (
    IGNITION_DATE, FIRE_NAME, FIRE_REGION,
    FIRE_TOTAL_HA, COPERNICUS_REF,
)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AquaFire API",
    description=(
        "Post-fire water contamination risk forecasting using real Sentinel-2 satellite data. "
        f"Pilot: {FIRE_NAME}, {IGNITION_DATE}, {FIRE_REGION}. "
        "Burned area computed from dNBR (differenced Normalised Burn Ratio) via openEO / Copernicus Data Space."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request models ────────────────────────────────────────────────────────────

class ForecastRequest(BaseModel):
    lake_key: str = Field(
        ...,
        example="stymfalia",
        description="Lake identifier: 'stymfalia' or 'doxa'"
    )
    forecast_months: int = Field(
        6, ge=1, le=24,
        description="Number of months to forecast (1–24)"
    )


# ── Startup check ─────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup_check():
    """Warn clearly if the satellite pipeline hasn't been run."""
    try:
        load_lake_stats()
        print("✓ lake_upstream_stats.json found — using real Sentinel-2 data")
    except FileNotFoundError:
        print("⚠ WARNING: lake_upstream_stats.json not found.")
        print("  Run: python sentinel_pipeline.py")
        print("  The API will return errors until the pipeline has run.")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    """Health check and quick start guide."""
    try:
        stats = load_lake_stats()
        data_source = stats.get("stymfalia", {}).get("data_source", "unknown")
        pipeline_status = "ready"
    except FileNotFoundError:
        data_source = "not_available"
        pipeline_status = "pipeline_not_run — execute: python sentinel_pipeline.py"

    return {
        "service":         "AquaFire API",
        "version":         "2.0.0",
        "status":          "online",
        "pipeline_status": pipeline_status,
        "data_source":     data_source,
        "fire": {
            "name":           FIRE_NAME,
            "ignition_date":  IGNITION_DATE,
            "region":         FIRE_REGION,
            "total_ha":       FIRE_TOTAL_HA,
            "copernicus_ref": COPERNICUS_REF,
        },
        "endpoints": {
            "stymfalia_forecast": "GET /api/forecast/stymfalia",
            "doxa_forecast":      "GET /api/forecast/doxa",
            "compare":            "GET /api/compare",
            "demo":               "GET /api/demo",
            "docs":               "/docs",
        },
    }


@app.get("/lakes", tags=["Info"])
def list_lakes():
    """
    List both lakes with their Sentinel-2 derived statistics.
    Shows the real burned area computed from dNBR raster.
    """
    try:
        stats = load_lake_stats()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "fire": {
            "name":           FIRE_NAME,
            "ignition_date":  IGNITION_DATE,
            "total_ha":       FIRE_TOTAL_HA,
            "copernicus_ref": COPERNICUS_REF,
        },
        "lakes": [
            {
                "key":                  key,
                "name":                 lake["name"],
                "coordinates":          {"lon": lake["lon"], "lat": lake["lat"]},
                "elevation_m":          lake["elevation_m"],
                "type":                 lake["type"],
                "protected":            lake["protected"],
                "primary_use":          lake["primary_use"],
                "sentinel2_stats": {
                    "data_source":          lake.get("data_source"),
                    "catchment_total_ha":   lake.get("catchment_total_ha"),
                    "catchment_burned_ha":  lake.get("catchment_burned_ha"),
                    "burned_fraction_pct":  round(lake.get("burned_fraction", 0) * 100, 1),
                    "mean_dnbr":            lake.get("mean_dnbr"),
                    "mean_severity_class":  lake.get("mean_severity_class"),
                    "severity_breakdown_ha": lake.get("severity_breakdown_ha"),
                },
                "upstream_burned_categories": list(lake.get("upstream_burned", {}).keys()),
            }
            for key, lake in stats.items()
        ],
    }


@app.get("/api/forecast/stymfalia", tags=["Forecast"])
def forecast_stymfalia(
    months: int = Query(6, ge=1, le=24, description="Forecast horizon in months")
):
    """
    Monthly contamination forecast for Lake Stymfalia.

    Natural wetland (Natura 2000), 626m altitude.
    Upstream burned area computed from Sentinel-2 dNBR raster.
    Primary risk: PAHs and dissolved organic carbon from burned pine forest.
    """
    try:
        return forecast_lake("stymfalia", forecast_months=months)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/forecast/doxa", tags=["Forecast"])
def forecast_doxa(
    months: int = Query(6, ge=1, le=24, description="Forecast horizon in months")
):
    """
    Monthly contamination forecast for Lake Doxa (Feneos reservoir).

    Artificial irrigation reservoir, 900m altitude.
    Upstream burned area computed from Sentinel-2 dNBR raster.
    Different profile: agricultural land contributes pesticide residues
    and fertiliser metals (Cu, Zn) not present in Stymfalia.
    """
    try:
        return forecast_lake("doxa", forecast_months=months)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/compare", tags=["Forecast"])
def compare_lakes(
    months: int = Query(6, ge=1, le=24, description="Forecast horizon in months")
):
    """
    Side-by-side comparison of both lakes.
    Same fire, two different contamination risk profiles.
    This is the core demo endpoint.
    """
    try:
        s = forecast_lake("stymfalia", forecast_months=months)
        d = forecast_lake("doxa",      forecast_months=months)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Monthly comparison table
    comparison = []
    for i in range(months):
        sm = s["monthly_forecast"][i]
        dm = d["monthly_forecast"][i]
        comparison.append({
            "month":              i + 1,
            "label":              sm["label"],
            "stymfalia_kg":       sm["total_load_kg"],
            "doxa_kg":            dm["total_load_kg"],
            "stymfalia_dominant": sm["dominant_contaminant"],
            "doxa_dominant":      dm["dominant_contaminant"],
            "stymfalia_risk_summary": _risk_summary(sm),
            "doxa_risk_summary":      _risk_summary(dm),
        })

    s_contams = set(s["high_risk_contaminants"])
    d_contams = set(d["high_risk_contaminants"])

    return {
        "fire_event": {
            "name":           FIRE_NAME,
            "ignition_date":  IGNITION_DATE,
            "region":         FIRE_REGION,
            "total_ha":       FIRE_TOTAL_HA,
            "copernicus_ref": COPERNICUS_REF,
        },
        "summary": {
            "stymfalia": {
                "name":                   s["location"],
                "status":                 s["status"],
                "upstream_burned_ha":     s["fire_event"]["upstream_burned_ha"],
                "catchment_burned_ha":    s["satellite_data"]["catchment_burned_ha"],
                "mean_dnbr":              s["satellite_data"]["mean_dnbr"],
                "peak_month":             s["peak_risk_label"],
                "safe_after_month":       s["safe_after_month"],
                "high_risk_contaminants": s["high_risk_contaminants"],
            },
            "doxa": {
                "name":                   d["location"],
                "status":                 d["status"],
                "upstream_burned_ha":     d["fire_event"]["upstream_burned_ha"],
                "catchment_burned_ha":    d["satellite_data"]["catchment_burned_ha"],
                "mean_dnbr":              d["satellite_data"]["mean_dnbr"],
                "peak_month":             d["peak_risk_label"],
                "safe_after_month":       d["safe_after_month"],
                "high_risk_contaminants": d["high_risk_contaminants"],
            },
        },
        "key_differences": {
            "only_in_stymfalia":  sorted(s_contams - d_contams),
            "only_in_doxa":       sorted(d_contams - s_contams),
            "shared_high_risk":   sorted(s_contams & d_contams),
            "narrative": (
                f"Stymfalia has {s['satellite_data']['catchment_burned_ha']:,} ha burned "
                f"in its catchment (mean dNBR {s['satellite_data']['mean_dnbr']}) — "
                f"mostly pine forest, driving high organic contamination. "
                f"Doxa has {d['satellite_data']['catchment_burned_ha']:,} ha burned "
                f"(mean dNBR {d['satellite_data']['mean_dnbr']}) — "
                f"more agricultural land, adding pesticide residues and metals "
                f"absent in Stymfalia. Different fire exposure, different risk, "
                f"different intervention required."
            ),
        },
        "monthly_comparison": comparison,
        "stymfalia_full": s,
        "doxa_full":      d,
    }


@app.get("/api/demo", tags=["Demo"])
def full_demo():
    """
    Full pitch demo. Both lakes, 6-month forecast, pre-written narrative.
    Use this endpoint during the presentation.
    """
    try:
        s = forecast_lake("stymfalia", forecast_months=6)
        d = forecast_lake("doxa",      forecast_months=6)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "title":     "AquaFire — Post-Fire Water Contamination Forecast",
        "subtitle":  f"{FIRE_NAME}, {IGNITION_DATE}",
        "generated": datetime.utcnow().strftime("%d %B %Y, %H:%M UTC"),
        "fire": {
            "name":           FIRE_NAME,
            "ignition_date":  IGNITION_DATE,
            "total_ha":       FIRE_TOTAL_HA,
            "region":         FIRE_REGION,
            "copernicus_ref": COPERNICUS_REF,
        },
        "data_pipeline": {
            "satellite":    "Sentinel-2 L2A (ESA Copernicus)",
            "index":        "dNBR — differenced Normalised Burn Ratio",
            "pre_fire":     "July 1 – September 20, 2024 (median composite)",
            "post_fire":    "October 1–25, 2024 (median composite)",
            "land_use":     "CORINE land cover 2018 (EEA)",
            "model":        "Emission factors × severity multiplier × exponential decay",
        },
        "lakes": {
            "stymfalia": s,
            "doxa":      d,
        },
        "pitch_narrative": {
            "hook": (
                f"On {IGNITION_DATE} a wildfire burned {FIRE_TOTAL_HA:,} hectares in Corinthia. "
                "Two lakes sit downstream. Both face contamination — but from different sources, "
                "at different intensities. AquaFire computes this from satellite data automatically."
            ),
            "stymfalia_story": (
                f"Lake Stymfalia — protected Natura 2000 wetland — has "
                f"{s['satellite_data']['catchment_burned_ha']:,} ha burned in its catchment "
                f"(mean dNBR {s['satellite_data']['mean_dnbr']}, "
                f"{s['satellite_data']['mean_severity_class']} severity). "
                f"Month 1 load: {s['monthly_forecast'][0]['total_load_kg']:.0f} kg, "
                f"dominated by dissolved organic carbon and PAHs. "
                f"Risk clears by month {s['safe_after_month']}."
            ),
            "doxa_story": (
                f"Lake Doxa — the Feneos irrigation reservoir — has "
                f"{d['satellite_data']['catchment_burned_ha']:,} ha burned upstream "
                f"(mean dNBR {d['satellite_data']['mean_dnbr']}). "
                f"Month 1 load: {d['monthly_forecast'][0]['total_load_kg']:.0f} kg. "
                "Uniquely carries pesticide residues and copper/zinc from burned farmland — "
                "a signature absent in Stymfalia. Farmers drawing from Doxa face a different "
                "risk from the ecological managers of Stymfalia."
            ),
            "client_value": (
                "An insurer underwriting farms around Doxa can price this risk today. "
                "The water utility drawing from Stymfalia knows to prepare carbon filtration "
                "before the first October rain. A farmer knows which month to suspend irrigation. "
                "One API call. Real satellite data. Actionable output."
            ),
        },
    }


@app.post("/api/contamination-forecast", tags=["Forecast"])
def contamination_forecast(request: ForecastRequest):
    """
    Generic forecast endpoint. Takes lake_key and forecast_months.
    Returns full monthly contamination profile based on Sentinel-2 data.
    """
    try:
        return forecast_lake(request.lake_key, forecast_months=request.forecast_months)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _risk_summary(month_entry: dict) -> str:
    """One-line risk summary for a month entry."""
    contams = month_entry["contaminants"]
    high    = [n for n, v in contams.items() if v["risk"] == "high"]
    mod     = [n for n, v in contams.items() if v["risk"] == "moderate"]
    if high:    return f"HIGH — {', '.join(high[:2])}"
    elif mod:   return f"MODERATE — {', '.join(mod[:2])}"
    else:       return "LOW"
