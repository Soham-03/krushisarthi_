"""Turn PDFs, web pages and text files into knowledge-base documents."""
import io
import json
import os
import re
from urllib.parse import urlparse

import requests

from . import rag

MAX_BYTES = 40 * 1024 * 1024
UA = "KrushiSarthi-KB-Ingest/1.0 (research prototype)"


def _pdf_date(raw):
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?", raw or "")
    if not m:
        return None
    y, mo, d = m.group(1), m.group(2), m.group(3)
    return "-".join(x for x in (y, mo, d) if x)


def extract_pdf(data: bytes):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [(i + 1, (p.extract_text() or "")) for i, p in enumerate(reader.pages)]
    md = reader.metadata
    title = (getattr(md, "title", None) or "").strip() if md else ""
    created = _pdf_date(str(md.get("/CreationDate"))) if md and md.get("/CreationDate") else None
    return pages, {"title": title or None, "published": created}


def extract_html(html: str):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else None
    published = None
    for attr, val in (("property", "article:published_time"), ("name", "date"), ("name", "citation_publication_date"), ("itemprop", "datePublished")):
        tag = soup.find("meta", attrs={attr: val})
        if tag and tag.get("content"):
            published = tag["content"][:10]
            break
    for t in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"]):
        t.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = root.get_text("\n")
    text = re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text))
    return [(None, text.strip())], {"title": title, "published": published}


def _finish(meta, pages, found, source_type, url=None, fallback_title=""):
    out = dict(meta)
    out["title"] = out.get("title") or found.get("title") or fallback_title
    out["published"] = out.get("published") or found.get("published")
    out["url"] = out.get("url") or url
    out["source_type"] = source_type
    if not out.get("publisher") and out.get("url"):
        out["publisher"] = urlparse(out["url"]).netloc
    if isinstance(out.get("crops"), str):
        out["crops"] = [c.strip() for c in out["crops"].split(",") if c.strip()]
    return rag.add_document(out, pages)


def ingest_bytes(data: bytes, kind: str, meta: dict, url=None, fallback_title=""):
    if kind == "pdf":
        pages, found = extract_pdf(data)
    elif kind == "html":
        pages, found = extract_html(data.decode("utf-8", errors="replace"))
    else:
        pages, found = [(None, data.decode("utf-8", errors="replace"))], {}
    return _finish(meta, pages, found, {"pdf": "pdf", "html": "web"}.get(kind, "text"), url, fallback_title)


def ingest_url(url: str, meta: dict | None = None):
    meta = dict(meta or {})
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("Only http and https links can be ingested")
    r = requests.get(url, headers={"User-Agent": UA}, timeout=45, stream=True)
    r.raise_for_status()
    data = r.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(data) > MAX_BYTES:
        raise ValueError("File is larger than 40 MB")
    ctype = (r.headers.get("content-type") or "").lower()
    kind = "pdf" if ("pdf" in ctype or url.lower().split("?")[0].endswith(".pdf") or data[:4] == b"%PDF") else ("html" if "html" in ctype or b"<html" in data[:2000].lower() else "text")
    meta.setdefault("url", url)
    return ingest_bytes(data, kind, meta, url, fallback_title=os.path.basename(urlparse(url).path) or url)


def ingest_file(path: str, meta: dict | None = None):
    meta = dict(meta or {})
    ext = os.path.splitext(path)[1].lower()
    kind = {".pdf": "pdf", ".html": "html", ".htm": "html"}.get(ext, "text")
    with open(path, "rb") as f:
        data = f.read()
    return ingest_bytes(data, kind, meta, meta.get("url"), fallback_title=os.path.splitext(os.path.basename(path))[0])


def ingest_manifest(path: str):
    """A JSON list. Each item needs "url" or "path", and should include title, publisher, published and crops."""
    items = json.load(open(path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(path))
    results = []
    for it in items:
        it = dict(it)
        src_url, src_path = it.pop("url", None), it.pop("path", None)
        try:
            if src_url:
                res = ingest_url(src_url, it)
            elif src_path:
                res = ingest_file(src_path if os.path.isabs(src_path) else os.path.join(base, src_path), it)
            else:
                raise ValueError("Item needs a url or a path")
            results.append({"source": src_url or src_path, **res})
        except Exception as exc:  # noqa: BLE001
            results.append({"source": src_url or src_path, "status": "failed", "error": str(exc)[:200]})
    return results
