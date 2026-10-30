"""Satellite health series.

Live mode: Sentinel-2 through Google Earth Engine (NDVI, NDMI, NDRE averaged over the farm).
Demo mode: a repeatable made-up series so the whole app works with no keys.
"""
import logging
import random
from datetime import date, timedelta

from . import crops
from .config import settings

log = logging.getLogger("satellite")
_ee = None
_ee_error = None


def mode() -> str:
    return "gee" if (settings.ee_enabled and _ee_error is None) else "demo"


def last_error():
    return _ee_error


def _init_ee():
    global _ee, _ee_error
    if _ee is not None:
        return _ee
    try:
        import ee

        if settings.ee_service_account and settings.ee_key_file:
            creds = ee.ServiceAccountCredentials(settings.ee_service_account, settings.ee_key_file)
            ee.Initialize(credentials=creds, project=settings.ee_project)
        else:
            ee.Initialize(project=settings.ee_project)
        _ee = ee
        _ee_error = None
    except Exception as exc:  # noqa: BLE001
        _ee_error = str(exc)[:300]
        log.warning("Earth Engine not available: %s", exc)
        raise
    return _ee


def _geometry(ee, geojson):
    g = geojson.get("geometry", geojson)
    return ee.Geometry(g)


def fetch_gee(geojson: dict, start: date, end: date):
    """Mean NDVI / NDMI / NDRE per Sentinel-2 date over the farm polygon."""
    ee = _init_ee()
    geom = _geometry(ee, geojson)
    coll = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geom)
        .filterDate(start.isoformat(), (end + timedelta(days=1)).isoformat())
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 70))
        .sort("system:time_start")
        .limit(150)
    )

    def per_image(img):
        scl = img.select("SCL")
        good = scl.eq(4).Or(scl.eq(5))  # vegetation or bare soil: cloud, shadow and water removed
        s = img.updateMask(good).divide(10000)
        stack = (
            s.normalizedDifference(["B8", "B4"]).rename("ndvi")
            .addBands(s.normalizedDifference(["B8", "B11"]).rename("ndmi"))
            .addBands(s.normalizedDifference(["B8", "B5"]).rename("ndre"))
        )
        stats = stack.reduceRegion(ee.Reducer.mean(), geom, 10, maxPixels=1e8, bestEffort=True)
        clear = good.rename("clear").reduceRegion(ee.Reducer.mean(), geom, 20, maxPixels=1e8, bestEffort=True)
        return ee.Feature(None, {
            "date": img.date().format("YYYY-MM-dd"),
            "ndvi": stats.get("ndvi"), "ndmi": stats.get("ndmi"), "ndre": stats.get("ndre"),
            "clear": clear.get("clear"),
        })

    feats = ee.FeatureCollection(coll.map(per_image)).getInfo().get("features", [])
    by_date = {}
    for f in feats:
        p = f.get("properties", {})
        if p.get("ndvi") is None or (p.get("clear") or 0) < 0.4:
            continue
        by_date.setdefault(p["date"], []).append(p)
    obs = []
    for d in sorted(by_date):
        rows = by_date[d]
        avg = lambda k: round(sum(r[k] for r in rows if r.get(k) is not None) / max(1, len([r for r in rows if r.get(k) is not None])), 4)
        obs.append({"date": d, "ndvi": avg("ndvi"), "ndmi": avg("ndmi"), "ndre": avg("ndre")})
    return obs


def low_ndvi_points(geojson: dict, n: int = 4):
    """Pixels with the lowest recent NDVI. Used to mark priority spots for the weekly checkup."""
    try:
        ee = _init_ee()
        geom = _geometry(ee, geojson)
        end = date.today()
        img = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(geom)
            .filterDate((end - timedelta(days=25)).isoformat(), (end + timedelta(days=1)).isoformat())
            .map(lambda i: i.updateMask(i.select("SCL").eq(4).Or(i.select("SCL").eq(5))).divide(10000).normalizedDifference(["B8", "B4"]).rename("ndvi"))
            .median()
        )
        pts = img.sample(region=geom, scale=10, numPixels=400, geometries=True, seed=1).getInfo().get("features", [])
        pts = [p for p in pts if p["properties"].get("ndvi") is not None]
        pts.sort(key=lambda p: p["properties"]["ndvi"])
        return [(p["geometry"]["coordinates"][1], p["geometry"]["coordinates"][0]) for p in pts[:n]]
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- demo data
def _factor(scenario: str, d: int) -> float:
    def ramp(start, end, low):
        if d <= start:
            return 1.0
        if d >= end:
            return low
        return 1.0 - (1.0 - low) * (d - start) / (end - start)

    return {
        "healthy": 1.0,
        "nitrogen": ramp(25, 50, 0.78),
        "water": ramp(30, 55, 0.72),
        "disease": ramp(35, 60, 0.80),
        "late": 0.82,
    }.get(scenario, 1.0)


def demo_series(farm: dict, crop: dict, sowing: date, today: date):
    scenario = farm.get("scenario") or "healthy"
    rnd = random.Random(int(farm["id"]) * 7919 + 13)
    days = (today - sowing).days
    obs = []
    for d in range(3, min(days, crop["duration"] + 20) + 1, 5):
        if rnd.random() < 0.18:  # this pass was cloudy
            continue
        e = crops.expected_ndvi(crop, d)
        f = _factor(scenario, d)
        stress = 1.0 - f
        ndvi = max(0.05, min(0.95, e * f + rnd.gauss(0, 0.015)))
        ndmi_base = 0.08 + 0.38 * (e / 0.85)
        ndmi = ndmi_base - (0.45 * stress if scenario == "water" else 0.10 * stress) + rnd.gauss(0, 0.01)
        ratio = 0.55 - (1.2 * stress if scenario == "nitrogen" else 0.3 * stress)
        ndre = max(0.04, ndvi * ratio + rnd.gauss(0, 0.008))
        obs.append({"date": (sowing + timedelta(days=d)).isoformat(), "ndvi": round(ndvi, 4), "ndmi": round(ndmi, 4), "ndre": round(ndre, 4)})
    return obs


def get_obs(farm: dict, crop: dict, sowing: date, today: date):
    """Returns (source, observations, error)."""
    if settings.ee_enabled and _ee_error is None:
        try:
            start = max(sowing - timedelta(days=5), today - timedelta(days=330))
            if start >= today:
                return "gee", [], None
            return "gee", fetch_gee(farm["geometry"], start, today), None
        except Exception as exc:  # noqa: BLE001
            return "demo", demo_series(farm, crop, sowing, today), f"Earth Engine error: {str(exc)[:160]}"
    err = _ee_error
    return "demo", demo_series(farm, crop, sowing, today), err
