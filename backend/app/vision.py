"""Leaf-photo checks and soil-report reading with the Claude API (or clearly labelled demo results)."""
import hashlib
import io
import json
import re

from PIL import Image, ImageOps

from . import crops, llm
from .config import settings


def prepare(img_bytes: bytes, max_side: int = 1024) -> bytes:
    im = Image.open(io.BytesIO(img_bytes))
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def _json_from(text: str):
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("No JSON in model reply")
    return json.loads(m.group(0))


LEAF_SYSTEM = """You are a plant health assistant for small farmers in India.
You look at one photo of a crop plant and decide if it is healthy or shows a pest, disease, nutrient or weather problem.
Rules:
- Only judge what is visible. If the photo is blurry, dark, far away, or does not show a plant leaf, say status "unclear" and ask for a retake.
- Never give chemical names or doses. Advice must be simple, practical steps a farmer can do today.
- Be honest about uncertainty. Use a confidence from 0 to 1.
- Reply with ONLY one JSON object, no other text."""


def _leaf_prompt(crop_key: str) -> str:
    crop = crops.get(crop_key) or {"name": crop_key}
    known = "\n".join(f'- {k["id"]}: {k["name"]} ({k["type"]}): {k["symptoms"]}' for k in crops.knowledge_for(crop_key))
    return f"""Crop: {crop['name']}
Known common problems for this crop:
{known or '(none listed)'}

Return JSON with exactly these keys:
{{"status": "healthy" | "issue" | "unclear",
 "issue_id": "<one id from the list above, or 'other', or null if healthy/unclear>",
 "issue": "<short name of the problem, or null>",
 "type": "disease" | "pest" | "nutrient" | "weather" | "none",
 "confidence": <0 to 1>,
 "symptoms": ["<what you can see, max 3 short items>"],
 "advice": ["<max 3 short practical steps>"],
 "retake": <true or false>,
 "retake_reason": "<why, or null>"}}"""


def _finish_leaf(result: dict, crop_key: str, demo: bool):
    status = result.get("status")
    if status not in ("healthy", "issue", "unclear"):
        status = "unclear"
    try:
        conf = float(result.get("confidence") or 0)
    except Exception:  # noqa: BLE001
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    issue_id = result.get("issue_id")
    kb = crops.find_issue(crop_key, issue_id) if issue_id and issue_id != "other" else None
    out = {
        "status": status,
        "issue": (kb["name"] if kb else result.get("issue")) if status == "issue" else None,
        "issue_id": issue_id if kb else None,
        "type": (kb["type"] if kb else result.get("type")) if status == "issue" else "none",
        "confidence": round(conf, 2),
        "symptoms": [str(s) for s in (result.get("symptoms") or [])][:3],
        "advice": (kb["actions"] if kb else [str(a) for a in (result.get("advice") or [])][:3]) if status == "issue" else [],
        "severity": kb["severity"] if kb else "moderate",
        "retake": bool(result.get("retake")) or status == "unclear",
        "retake_reason": result.get("retake_reason"),
        "demo": demo,
    }
    if status == "issue" and conf < 0.6:
        out["advice"] = out["advice"] + ["Confidence is low. Show this plant to your Taluka Agriculture Officer before acting."]
    return out


def demo_leaf(data: bytes, crop_key: str, scenario: str):
    h = int(hashlib.md5(data).hexdigest(), 16)
    rate = {"healthy": 0.08, "disease": 0.45, "nitrogen": 0.12, "water": 0.12, "late": 0.10}.get(scenario, 0.1)
    kb = crops.knowledge_for(crop_key)
    if kb and (h % 1000) / 1000.0 < rate:
        k = kb[(h // 1000) % len(kb)]
        return _finish_leaf({"status": "issue", "issue_id": k["id"], "confidence": 0.55 + (h % 35) / 100.0,
                             "symptoms": [k["symptoms"]]}, crop_key, True)
    return _finish_leaf({"status": "healthy", "confidence": 0.7 + (h % 25) / 100.0}, crop_key, True)


def analyze_leaf(img_bytes: bytes, crop_key: str, scenario: str = "healthy", triage: bool = False):
    """triage=True uses the cheaper model, meant for the 30 to 40 weekly checkup photos."""
    data = prepare(img_bytes)
    if not settings.ai_enabled:
        return demo_leaf(data, crop_key, scenario)
    model = settings.triage_model_name if triage else settings.vision_model_name
    try:
        text = llm.get_provider().complete_vision(LEAF_SYSTEM, _leaf_prompt(crop_key), data, 900, model)
        return _finish_leaf(_json_from(text), crop_key, False)
    except llm.LLMError as exc:
        return {"status": "error", "message": llm.user_message(exc), "demo": False}
    except (ValueError, KeyError, TypeError):
        return {"status": "error", "message": "The AI answer could not be read. Please retake the photo.", "demo": False}


SOIL_SYSTEM = """You read Indian soil test reports (including Soil Health Cards) from photos.
Extract only values that are clearly printed. Do not guess. Reply with ONLY one JSON object."""

SOIL_PROMPT = """Return JSON with keys:
{"n": <available nitrogen as number or null>, "p": <available phosphorus or null>, "k": <available potassium or null>,
 "ph": <number or null>, "oc": <organic carbon in percent or null>, "ec": <electrical conductivity or null>,
 "units_note": "<units as printed, e.g. 'N, P, K in kg/ha'>", "needs_review": <true if units or values are unclear>,
 "notes": "<one short sentence>"}"""


def extract_soil(img_bytes: bytes):
    if not settings.ai_enabled:
        return {"error": "Reading reports needs an AI provider. Please type the values in instead."}
    data = prepare(img_bytes, 1600)
    try:
        text = llm.get_provider().complete_vision(SOIL_SYSTEM, SOIL_PROMPT, data, 900, settings.vision_model_name)
        j = _json_from(text)
        out = {}
        for k in ("n", "p", "k", "ph", "oc", "ec"):
            try:
                out[k] = float(j[k]) if j.get(k) is not None else None
            except (TypeError, ValueError):
                out[k] = None
        out["units_note"] = j.get("units_note") or ""
        out["needs_review"] = bool(j.get("needs_review"))
        out["notes"] = j.get("notes") or ""
        return out
    except llm.LLMError as exc:
        return {"error": llm.user_message(exc)}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {"error": "The report could not be read. Try a clearer, straight-on photo, or type the values in."}
