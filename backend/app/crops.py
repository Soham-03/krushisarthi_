import json
from pathlib import Path

_D = Path(__file__).parent / "data"
CROPS = json.loads((_D / "crops.json").read_text(encoding="utf-8"))
KNOWLEDGE = json.loads((_D / "knowledge.json").read_text(encoding="utf-8"))


def get(key: str):
    return CROPS.get(key)


def expected_ndvi(crop: dict, day: float) -> float:
    pts = crop["curve"]
    if day <= pts[0][0]:
        return pts[0][1]
    if day >= pts[-1][0]:
        return pts[-1][1]
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        if d0 <= day <= d1:
            t = (day - d0) / (d1 - d0)
            return v0 + (v1 - v0) * t
    return pts[-1][1]


def stage_for(crop: dict, day: int):
    stages = crop["stages"]
    for i, s in enumerate(stages):
        if s["from"] <= day < s["to"]:
            return {**s, "index": i, "count": len(stages)}
    if day < 0:
        return {**stages[0], "index": 0, "count": len(stages), "name": "Not sown yet"}
    last = stages[-1]
    return {**last, "index": len(stages) - 1, "count": len(stages)}


def knowledge_for(crop_key: str):
    return KNOWLEDGE.get(crop_key, [])


def find_issue(crop_key: str, issue_id: str):
    for k in KNOWLEDGE.get(crop_key, []):
        if k["id"] == issue_id:
            return k
    return None


def public_list():
    return [
        {"key": k, "name": v["name"], "hi": v["hi"], "mr": v["mr"], "season": v["season"], "duration": v["duration"]}
        for k, v in CROPS.items()
    ]
