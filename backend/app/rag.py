"""Knowledge base: chunking, storage and retrieval (keyword search, plus optional semantic search).

Keyword search uses SQLite FTS5 (BM25) and needs no extra service. If an OpenAI-compatible
embeddings API is configured, passages also get vectors and the two rankings are fused.
A relevance gate drops weak matches, so "no relevant source" is a real answer, not a guess.
"""
import hashlib
import json
import logging
import math
import re
import threading

import numpy as np
import requests

from .config import settings
from .db import conn, dumps, loads, now_iso, one, q

log = logging.getLogger("rag")
_lock = threading.Lock()

STOP = set("""a an the of in on for to and or but my me i it its with at by from this that these those be been is are was were am
do does did have has had there their they them he she we you your our any some about into over under than then so if as not no
can could should would will shall may might must also very more most much many such what when where why which who whom how
tell give help please get got let us use using used need needs want like make makes made one two""".split())
GENERIC = set("""crop crops plant plants farm farms farmer farmers field fields best good better grow growing grown time per year season
problem issue question answer information info advice tips tip suggest recommend recommended recommendation""".split())


# ------------------------------------------------------------------ text helpers
def tokens(text: str):
    return [t for t in re.findall(r"\w+", (text or "").lower()) if len(t) >= 2]


def stem(t: str) -> str:
    if t.isascii() and len(t) > 4:
        for suf in ("ing", "ed", "es", "ly", "s"):
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                return t[: -len(suf)]
    return t


def informative_terms(query: str):
    seen, out = set(), []
    for t in tokens(query):
        if t in STOP or t in GENERIC or t.isdigit():
            continue
        s = stem(t)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def chunk_text(text: str, size: int = 900, overlap: int = 120):
    """Paragraph-aware chunks of about `size` characters with a small overlap."""
    text = re.sub(r"[ \t]+", " ", text or "")
    paras = [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if p.strip()]
    pieces = []
    for p in paras:
        p = re.sub(r"\s*\n\s*", " ", p)
        if len(p) <= size:
            pieces.append(p)
        else:
            sents = re.split(r"(?<=[.!?।])\s+", p)
            cur = ""
            for s in sents:
                while len(s) > size:  # one huge sentence: hard split on spaces
                    cut = s.rfind(" ", 0, size) or size
                    pieces.append((cur + " " + s[:cut]).strip()) if cur else pieces.append(s[:cut])
                    cur, s = "", s[cut:].strip()
                if len(cur) + len(s) + 1 > size and cur:
                    pieces.append(cur.strip())
                    cur = s
                else:
                    cur = (cur + " " + s).strip()
            if cur:
                pieces.append(cur.strip())
    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) + 1 > size:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = (tail.split(" ", 1)[-1] + " " + p).strip() if tail else p
        else:
            cur = (cur + " " + p).strip() if cur else p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if len(c) >= 30]


def fts_available() -> bool:
    return bool(one("SELECT name FROM sqlite_master WHERE type='table' AND name='kb_fts'"))


# ------------------------------------------------------------------ embeddings (optional)
class EmbeddingError(RuntimeError):
    pass


def embed_texts(texts, input_type=None):
    if not settings.embeddings_enabled:
        raise EmbeddingError("Embeddings are not configured")
    out = []
    headers = {"Content-Type": "application/json"}
    if settings.embedding_api_key:
        headers["Authorization"] = "Bearer " + settings.embedding_api_key
    for i in range(0, len(texts), 32):
        batch = texts[i:i + 32]
        try:
            r = requests.post(settings.embedding_base_url + "/embeddings", headers=headers, timeout=60,
                              json={"model": settings.embedding_model, "input": batch})
        except requests.RequestException as exc:
            raise EmbeddingError(f"Embedding service unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise EmbeddingError(f"Embedding service error {r.status_code}: {r.text[:160]}")
        data = sorted(r.json().get("data", []), key=lambda d: d.get("index", 0))
        if len(data) != len(batch):
            raise EmbeddingError("Embedding service returned the wrong number of vectors")
        out.extend(d["embedding"] for d in data)
    return out


def _to_blob(vec) -> bytes:
    v = np.asarray(vec, dtype=np.float32)
    n = np.linalg.norm(v)
    return (v / n if n else v).tobytes()


_matrix = None  # (signature, ids, matrix)


def _load_matrix():
    global _matrix
    rows = q("SELECT c.id, c.embedding, d.crops FROM kb_chunks c JOIN kb_documents d ON d.id=c.doc_id WHERE c.embedding IS NOT NULL")
    sig = (len(rows), rows[-1]["id"] if rows else 0)
    if _matrix and _matrix[0] == sig:
        return _matrix
    if not rows:
        _matrix = (sig, [], None, [])
        return _matrix
    dims = {len(r["embedding"]) for r in rows}
    if len(dims) != 1:
        log.warning("Mixed embedding sizes in the knowledge base; re-ingest after changing the embedding model")
        rows = [r for r in rows if len(r["embedding"]) == max(dims)]
    mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    _matrix = (sig, [r["id"] for r in rows], mat, [loads(r["crops"], []) for r in rows])
    return _matrix


# ------------------------------------------------------------------ ingest
def add_document(meta: dict, pages):
    """pages: list of (page_number or None, text). Returns {"id", "status", "chunks", "warning"?}."""
    if not fts_available():
        raise RuntimeError("This SQLite build has no FTS5 support, so the knowledge base is unavailable")
    title = (meta.get("title") or "").strip()
    if not title:
        raise ValueError("A document needs a title")
    full = "\n\n".join(t for _, t in pages if t)
    if len(full.strip()) < 50:
        raise ValueError("The document has almost no readable text (scanned PDF? try OCR first)")
    h = hashlib.sha256(full.encode("utf-8")).hexdigest()
    dup = one("SELECT id FROM kb_documents WHERE content_hash=?", (h,))
    if dup:
        return {"id": dup["id"], "status": "duplicate", "chunks": 0}
    chunks = []
    for page, text in pages:
        for c in chunk_text(text):
            chunks.append((page, c))
    if not chunks:
        raise ValueError("No usable passages found in the document")
    vectors, warning = None, None
    if settings.embeddings_enabled:
        try:
            vectors = embed_texts([c for _, c in chunks])
        except EmbeddingError as exc:
            warning = f"Stored for keyword search only: {exc}"
            log.warning(warning)
    crops = [c.strip().lower() for c in (meta.get("crops") or []) if c.strip()]
    with _lock, conn() as c:
        cur = c.execute(
            "INSERT INTO kb_documents(title,publisher,url,published,language,crops,source_type,license_note,content_hash,added_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (title, meta.get("publisher"), meta.get("url"), meta.get("published"), meta.get("language") or "en", dumps(crops),
             meta.get("source_type"), meta.get("license_note"), h, now_iso()))
        doc_id = cur.lastrowid
        for i, (page, text) in enumerate(chunks):
            emb = _to_blob(vectors[i]) if vectors else None
            cc = c.execute("INSERT INTO kb_chunks(doc_id,idx,page,text,embedding) VALUES(?,?,?,?,?)", (doc_id, i, page, text, emb))
            c.execute("INSERT INTO kb_fts(rowid,text,title) VALUES(?,?,?)", (cc.lastrowid, text, title))
    global _matrix
    _matrix = None
    out = {"id": doc_id, "status": "added", "chunks": len(chunks)}
    if warning:
        out["warning"] = warning
    return out


def delete_document(doc_id: int):
    with _lock, conn() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM kb_chunks WHERE doc_id=?", (doc_id,)).fetchall()]
        for cid in ids:
            c.execute("DELETE FROM kb_fts WHERE rowid=?", (cid,))
        c.execute("DELETE FROM kb_chunks WHERE doc_id=?", (doc_id,))
        c.execute("DELETE FROM kb_documents WHERE id=?", (doc_id,))
    global _matrix
    _matrix = None
    return len(ids)


# ------------------------------------------------------------------ search
def _doc_ok(crops, crop):
    return not crop or not crops or crop in crops


def _lexical(terms, crop, limit):
    if not terms or not fts_available():
        return []
    match = " OR ".join(f'"{t}"*' if t.isascii() else f'"{t}"' for t in terms)
    try:
        rows = q(
            "SELECT f.rowid AS chunk_id, bm25(kb_fts, 1.0, 2.0) AS bm, c.doc_id, c.page, c.text, d.title, d.publisher, d.url, d.published, d.crops "
            "FROM kb_fts f JOIN kb_chunks c ON c.id=f.rowid JOIN kb_documents d ON d.id=c.doc_id WHERE kb_fts MATCH ? ORDER BY bm LIMIT ?",
            (match, limit * 3))
    except Exception as exc:  # noqa: BLE001
        log.warning("FTS query failed: %s", exc)
        return []
    out = []
    for r in rows:
        if not _doc_ok(loads(r["crops"], []), crop):
            continue
        toks = set(tokens(r["text"] + " " + r["title"]))
        matched = sum(1 for t in terms if any(w == t or w.startswith(t) for w in toks))
        r["matched"], r["lex_score"] = matched, -r["bm"]
        out.append(r)
    return out[:limit]


def _semantic(query, crop, limit):
    if not settings.embeddings_enabled:
        return []
    sig, ids, mat, crops_list = _load_matrix()
    if mat is None:
        return []
    try:
        qv = np.asarray(embed_texts([query])[0], dtype=np.float32)
    except EmbeddingError as exc:
        log.warning("semantic search skipped: %s", exc)
        return []
    qv = qv / (np.linalg.norm(qv) or 1.0)
    if qv.shape[0] != mat.shape[1]:
        return []
    sims = mat @ qv
    order = np.argsort(-sims)[: limit * 3]
    out = []
    for i in order:
        if _doc_ok(crops_list[i], crop):
            out.append((ids[i], float(sims[i])))
        if len(out) >= limit:
            break
    return out


def _hydrate(chunk_ids):
    if not chunk_ids:
        return {}
    marks = ",".join("?" * len(chunk_ids))
    rows = q(f"SELECT c.id AS chunk_id, c.doc_id, c.page, c.text, d.title, d.publisher, d.url, d.published FROM kb_chunks c JOIN kb_documents d ON d.id=c.doc_id WHERE c.id IN ({marks})", tuple(chunk_ids))
    return {r["chunk_id"]: r for r in rows}


def search(query: str, crop: str | None = None, k: int | None = None):
    """Returns up to k relevant passages, or [] when nothing relevant exists."""
    k = k or settings.kb_top_k
    crop = (crop or "").strip().lower() or None
    terms = informative_terms(query)
    lex = _lexical(terms, crop, 30)
    need = min(2, len(terms))
    lex_pass = {r["chunk_id"]: r for r in lex if r["matched"] >= need and (r["matched"] / max(1, len(terms))) >= 0.34}
    sem = _semantic(query, crop, 30)
    sem_pass = {cid: s for cid, s in sem if s >= settings.kb_min_cosine}
    scores = {}
    for rank, r in enumerate([x for x in lex if x["chunk_id"] in lex_pass]):
        scores[r["chunk_id"]] = scores.get(r["chunk_id"], 0) + 1.0 / (60 + rank)
    for rank, (cid, s) in enumerate([x for x in sem if x[0] in sem_pass]):
        scores[cid] = scores.get(cid, 0) + 1.0 / (60 + rank)
    if not scores:
        return []
    top = sorted(scores, key=lambda c: -scores[c])[:k]
    docs = _hydrate(top)
    results = []
    for cid in top:
        d = docs.get(cid)
        if not d:
            continue
        results.append({
            "chunk_id": cid, "doc_id": d["doc_id"], "title": d["title"], "publisher": d["publisher"], "url": d["url"],
            "published": d["published"], "page": d["page"], "text": d["text"][:1200],
            "method": "hybrid" if cid in lex_pass and cid in sem_pass else ("semantic" if cid in sem_pass else "keyword"),
            "score": round(scores[cid], 4),
        })
    return results


def stats():
    if not fts_available():
        return {"available": False, "documents": 0, "chunks": 0, "embedded_chunks": 0, "semantic_search": False,
                "note": "SQLite FTS5 is not available in this Python build"}
    d = one("SELECT COUNT(*) AS n FROM kb_documents")["n"]
    c = one("SELECT COUNT(*) AS n, SUM(embedding IS NOT NULL) AS e FROM kb_chunks")
    return {"available": True, "documents": d, "chunks": c["n"], "embedded_chunks": int(c["e"] or 0),
            "semantic_search": settings.embeddings_enabled}
