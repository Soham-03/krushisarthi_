import copy
import json
import os
import sys
import tempfile
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

# isolated database and no real keys, set before the app is imported
os.environ["DATA_DIR"] = tempfile.mkdtemp()
for k in ("CLERK_PUBLISHABLE_KEY", "ANTHROPIC_API_KEY", "EE_PROJECT", "LLM_API_KEY", "LLM_BASE_URL", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL"):
    os.environ[k] = ""
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app import llm, ratelimit, services  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import q, run  # noqa: E402
from app.main import app  # noqa: E402


class Scripted:
    """Stands in for the model API only. Everything around it (tools, retrieval, parsing) is real."""

    name = "scripted"

    def __init__(self, steps):
        self.steps, self.calls = list(steps), []

    def complete(self, system, messages, tools, max_tokens):
        self.calls.append({"system": system, "messages": copy.deepcopy(messages), "tools": tools})
        step = self.steps.pop(0) if self.steps else llm.LLMResult(text="(no more scripted steps)")
        if isinstance(step, Exception):
            raise step
        return step(messages) if callable(step) else step


def R(text="", calls=None):
    return llm.LLMResult(text=text, tool_calls=calls or [])


def call(name, args=None, cid="c1"):
    return {"id": cid, "name": name, "args": args or {}}


def last_tool_json(messages, name=None):
    for m in reversed(messages):
        if m["role"] == "tool" and (name is None or m["name"] == name):
            return json.loads(m["content"])
    return None


class FakeServer:
    def __init__(self, handler):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "json": json.loads(body or b"{}")})
                code, payload = handler(self.path, outer.requests[-1])
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    ratelimit._hits.clear()
    for t in ("kb_fts",):
        run(f"DELETE FROM {t}")
    run("DELETE FROM kb_chunks")
    run("DELETE FROM kb_documents")
    from app import rag
    rag._matrix = None
    yield


@pytest.fixture()
def farm(client):
    sow = (services.today_ist() - timedelta(days=50)).isoformat()
    poly = {"type": "Polygon", "coordinates": [[[75.0, 19.0], [75.003, 19.0], [75.003, 19.002], [75.0, 19.002], [75.0, 19.0]]]}
    r = client.post("/api/farms", json={"name": "Test farm", "crop": "cotton", "sowing_date": sow, "geometry": poly, "scenario": "nitrogen"})
    assert r.status_code == 200, r.text
    yield r.json()
    client.delete(f"/api/farms/{r.json()['id']}")


@pytest.fixture()
def farm_row(farm):
    from app.main import own_farm
    return own_farm("demo-user", farm["id"])


@pytest.fixture()
def ctx(farm_row):
    from app.tools import ToolContext
    return ToolContext("demo-user", farm_row)


def make_pdf(lines):
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    content = "BT /F1 11 Tf 50 780 Td 14 TL\n" + "\n".join(f"({esc(l)}) '" for l in lines) + "\nET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream".encode(), b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


COTTON_DOC = """Pink bollworm is a major pest of cotton. Larvae feed inside the bolls and flowers show rosette shaped blooms.

Pheromone traps help monitor moth catches each week. Destroy crop residue after the last picking to reduce carry over to the next season.

Whitefly transmits leaf curl virus in cotton. Yellow sticky traps and removing weed hosts reduce the population."""
