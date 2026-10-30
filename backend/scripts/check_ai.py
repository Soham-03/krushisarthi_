"""Live check of YOUR AI setup. Run from the backend folder:   python scripts/check_ai.py
It makes real calls with the keys in your .env file, so it needs internet and uses a little API credit."""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())  # a throwaway database, your real farms are untouched

from app import assistant, llm, rag, services, tools  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import init_db, one, run  # noqa: E402

ok_all = True


def line(ok, text):
    global ok_all
    ok_all &= ok
    print(("PASS  " if ok else "FAIL  ") + text)


init_db()
print(f"Provider: {settings.llm_provider}   Model: {settings.llm_model}   Embeddings: {'on' if settings.embeddings_enabled else 'off'}\n")
if not settings.assistant_enabled:
    print("FAIL  No AI provider is configured. Fill the LLM or ANTHROPIC settings in .env first.")
    sys.exit(1)

try:
    p = llm.get_provider()
    r = p.complete("Reply with one short sentence.", [{"role": "user", "content": "Say hello to a farmer."}], [], 60)
    line(bool(r.text), f"Model reachable. Reply: {r.text[:80]!r}")
except llm.LLMError as e:
    line(False, f"Model call failed ({e.kind}): {llm.user_message(e)}  [{e.message[:100]}]")
    sys.exit(1)

if settings.embeddings_enabled:
    try:
        v = rag.embed_texts(["pink bollworm"])[0]
        line(len(v) > 8, f"Embedding service reachable ({len(v)} dimensions)")
    except rag.EmbeddingError as e:
        line(False, f"Embedding service: {e}")

# photo features: a plain green test picture, so this checks the connection and the reply format, not accuracy
import io  # noqa: E402

from PIL import Image  # noqa: E402

from app import vision  # noqa: E402

buf = io.BytesIO()
Image.new("RGB", (640, 480), (50, 140, 60)).save(buf, "JPEG")
res = vision.analyze_leaf(buf.getvalue(), "cotton", triage=True)
line(res.get("status") in ("healthy", "issue", "unclear") and not res.get("demo"),
     f"Photo analysis (weekly-checkup model {settings.triage_model_name}): status={res.get('status')} {res.get('message', '')}")

sow = (services.today_ist() - datetime.timedelta(days=50)).isoformat()
poly = '{"type":"Polygon","coordinates":[[[75.0,19.0],[75.003,19.0],[75.003,19.002],[75.0,19.002],[75.0,19.0]]]}'
fid = run("INSERT INTO farms(user_id,name,crop,sowing_date,geojson,lat,lng,area_ha,scenario,reminder_day,created_at) "
          "VALUES('check','Check farm','cotton',?,?,19.001,75.0015,6.0,'healthy',6,'now')", (sow, poly))
ctx = tools.ToolContext("check", one("SELECT * FROM farms WHERE id=?", (fid,)))
try:
    out = assistant.run_agent(ctx, "My cotton is 50 days old. How do I manage pink bollworm, and what is the weather doing?", [], "en")
    print("\nAnswer:", out["reply"], "\n")
    print("Tools used:", [(t["label"], "ok" if t["ok"] else "FAILED: " + t["summary"]) for t in out["tools"]])
    print("Sources:", [(s["id"], s["title"], "cited" if s["cited"] else "not used") for s in out["sources"]] or "none")
    line(bool(out["reply"]), "Agent produced an answer")
    line(any(t["name"] == "search_agri_knowledge" for t in out["tools"]), "Model used the knowledge-base search tool")
    st = rag.stats()
    print(f"\nKnowledge base in this check: {st['documents']} documents, {st['chunks']} passages.")
    print("NOTE  This check uses an empty temporary database. Set DATA_DIR to your real data folder to test with your documents.")
except llm.LLMError as e:
    line(False, f"Agent run failed ({e.kind}): {llm.user_message(e)}  [{e.message[:100]}]")
print("\nAll checks passed." if ok_all else "\nSome checks failed. See above.")
