"""Small geometry helpers (no GIS libraries needed)."""
import math
import random


def _ring(geom: dict):
    g = geom.get("geometry", geom)
    ring = g["coordinates"][0]
    return [(float(x), float(y)) for x, y in ring]  # (lng, lat)


def centroid(geom: dict):
    ring = _ring(geom)
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    lng = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lat, lng


def _project(ring, lat0, lng0):
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    return [((x - lng0) * kx, (y - lat0) * ky) for x, y in ring]


def area_ha(geom: dict) -> float:
    ring = _ring(geom)
    lat0, lng0 = centroid(geom)
    p = _project(ring, lat0, lng0)
    a = 0.0
    for i in range(len(p) - 1):
        a += p[i][0] * p[i + 1][1] - p[i + 1][0] * p[i][1]
    return abs(a) / 2.0 / 10000.0


def _inside(pt, poly):
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def generate_spots(geom: dict, n: int, seed: int = 0):
    """Pick n well-spread points inside the farm and order them as a walking route."""
    rnd = random.Random(seed)
    ring = _ring(geom)
    lat0, lng0 = centroid(geom)
    poly = _project(ring, lat0, lng0)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w, h = max(maxx - minx, 1.0), max(maxy - miny, 1.0)
    step = math.sqrt(w * h / (n * 6.0))
    cands = []
    for _ in range(8):
        cands = []
        y = miny + step / 2
        while y < maxy:
            x = minx + step / 2
            while x < maxx:
                pt = (x + rnd.uniform(-step, step) * 0.25, y + rnd.uniform(-step, step) * 0.25)
                if _inside(pt, poly):
                    cands.append(pt)
                x += step
            y += step
        if len(cands) >= n:
            break
        step *= 0.7
    if not cands:  # degenerate polygon
        cands = [(0.0, 0.0)]
    # farthest-point sampling so spots cover the whole field evenly
    chosen = [min(cands, key=lambda c: c[0] ** 2 + c[1] ** 2)]
    dist = [math.dist(c, chosen[0]) for c in cands]
    while len(chosen) < min(n, len(cands)):
        idx = max(range(len(cands)), key=lambda i: dist[i])
        chosen.append(cands[idx])
        dist = [min(dist[i], math.dist(cands[i], cands[idx])) for i in range(len(cands))]
    while len(chosen) < n:  # tiny field: reuse positions with a small offset
        bx, by = chosen[len(chosen) % len(cands)]
        chosen.append((bx + rnd.uniform(-2, 2), by + rnd.uniform(-2, 2)))
    # walking order: snake through rows (south to north, alternating direction)
    rows = max(2, int(round(math.sqrt(n))))
    chosen.sort(key=lambda c: c[1])
    per = math.ceil(len(chosen) / rows)
    ordered = []
    for r in range(rows):
        band = sorted(chosen[r * per:(r + 1) * per], key=lambda c: c[0], reverse=(r % 2 == 1))
        ordered.extend(band)
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    return [
        {"i": i + 1, "lat": round(lat0 + y / ky, 7), "lng": round(lng0 + x / kx, 7), "priority": False}
        for i, (x, y) in enumerate(ordered)
    ]


def nearest_spots(spots, lat, lng, k):
    ranked = sorted(spots, key=lambda s: (s["lat"] - lat) ** 2 + (s["lng"] - lng) ** 2)
    return [s["i"] for s in ranked[:k]]
