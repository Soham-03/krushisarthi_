import io
import json

import pytest

from app import ingest, rag
from app.config import settings
from .conftest import COTTON_DOC, FakeServer, make_pdf


META = {"title": "Cotton pest guide", "publisher": "Test University", "url": "https://example.test/cotton.pdf", "published": "2024-05-01", "crops": ["cotton"]}


def test_chunking_keeps_text_and_sizes():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 80 for i in range(12))
    chunks = rag.chunk_text(text, size=600, overlap=80)
    assert len(chunks) > 3
    assert all(len(c) <= 760 for c in chunks)
    assert "Paragraph 0" in chunks[0] and "Paragraph 11" in chunks[-1]


def test_ingest_search_returns_metadata_and_dedupes():
    first = rag.add_document(META, [(3, COTTON_DOC)])
    assert first["status"] == "added" and first["chunks"] >= 1
    assert rag.add_document(META, [(3, COTTON_DOC)])["status"] == "duplicate"
    hits = rag.search("How do I control pink bollworm in cotton?")
    assert hits and hits[0]["title"] == "Cotton pest guide"
    h = hits[0]
    assert (h["publisher"], h["published"], h["url"], h["page"]) == ("Test University", "2024-05-01", "https://example.test/cotton.pdf", 3)
    assert "pheromone" in h["text"].lower()


def test_unrelated_and_weak_queries_return_nothing():
    rag.add_document(META, [(1, COTTON_DOC)])
    assert rag.search("what is the capital of France") == []
    assert rag.search("wheat yellow rust fungicide") == []
    assert rag.search("the crop") == []          # only generic words
    assert rag.search("") == []


def test_crop_filter_excludes_documents_about_other_crops():
    rag.add_document(META, [(1, COTTON_DOC)])
    assert rag.search("pink bollworm larvae", crop="wheat") == []
    assert rag.search("pink bollworm larvae", crop="cotton")


def test_devanagari_terms_are_searchable():
    rag.add_document({"title": "मराठी मार्गदर्शक", "publisher": "कृषी विभाग", "language": "mr"},
                     [(None, "सोयाबीन पिकावर पिवळा मोझॅक रोग पांढरी माशी मुळे पसरतो. बाधित झाडे लवकर काढून टाकावीत. शेतात पिवळे चिकट सापळे लावावेत.")])
    hits = rag.search("पिवळा मोझॅक रोग सोयाबीन")
    assert hits and hits[0]["publisher"] == "कृषी विभाग"


def test_pdf_extraction_page_and_metadata():
    pdf = make_pdf(["Soybean yellow mosaic virus is spread by whitefly.", "Remove infected plants early and keep the field edges weed free.",
                    "Use yellow sticky traps to monitor whitefly numbers in the crop."])
    res = ingest.ingest_bytes(pdf, "pdf", {"title": "Soybean notes", "publisher": "Dept of Agriculture"}, "https://example.test/s.pdf")
    assert res["status"] == "added"
    hit = rag.search("whitefly yellow mosaic soybean")[0]
    assert hit["page"] == 1 and hit["url"] == "https://example.test/s.pdf"


def test_html_extraction_strips_navigation_and_reads_date():
    html = ("<html><head><title>Wheat rust</title><meta property='article:published_time' content='2022-11-05T00:00:00'></head>"
            "<body><nav>MENU LOGIN HOME</nav><main><p>Yellow rust of wheat shows yellow stripes on leaves in cool humid weather. "
            "Check the crop weekly and report early to the agriculture officer for advice.</p></main></body></html>")
    res = ingest.ingest_bytes(html.encode(), "html", {"publisher": "Test Dept"}, "https://example.test/rust")
    assert res["status"] == "added"
    doc = rag.q("SELECT title, published FROM kb_documents")[0]
    assert doc["title"] == "Wheat rust" and doc["published"] == "2022-11-05"
    assert rag.search("menu login") == []


def test_scanned_or_empty_documents_are_rejected():
    with pytest.raises(ValueError):
        rag.add_document(META, [(1, "  ")])
    with pytest.raises(ValueError):
        rag.add_document({"title": ""}, [(1, COTTON_DOC)])


def _fake_embed_handler(path, req):
    """Deterministic bag-of-words vectors, so cosine similarity behaves like a real (if crude) embedding model."""
    import hashlib
    vecs = []
    for text in req["json"]["input"]:
        v = [0.0] * 512
        for w in text.lower().split():
            v[int(hashlib.md5(w.strip('.,?').encode()).hexdigest(), 16) % 512] += 1.0
        vecs.append(v)
    return 200, {"data": [{"index": i, "embedding": v} for i, v in enumerate(vecs)]}


def test_semantic_and_hybrid_search_with_embedding_service(monkeypatch):
    srv = FakeServer(_fake_embed_handler)
    try:
        monkeypatch.setattr(settings, "embedding_base_url", srv.url)
        monkeypatch.setattr(settings, "embedding_model", "fake-embed")
        monkeypatch.setattr(settings, "embeddings_enabled", True)
        monkeypatch.setattr(settings, "kb_min_cosine", 0.2)
        res = rag.add_document(META, [(1, COTTON_DOC)])
        assert res["status"] == "added" and "warning" not in res
        assert rag.stats()["embedded_chunks"] >= 1 and rag.stats()["semantic_search"]
        hits = rag.search("pheromone traps monitor moth catches weekly")
        assert hits and hits[0]["method"] in ("hybrid", "semantic")
        assert srv.requests[0]["path"] == "/embeddings" and srv.requests[0]["json"]["model"] == "fake-embed"
        assert rag.search("completely unrelated astronomy telescope galaxy") == []
    finally:
        srv.close()


def test_embedding_failure_falls_back_to_keyword_search(monkeypatch):
    srv = FakeServer(lambda p, r: (500, {"error": "down"}))
    try:
        monkeypatch.setattr(settings, "embedding_base_url", srv.url)
        monkeypatch.setattr(settings, "embedding_model", "fake-embed")
        monkeypatch.setattr(settings, "embeddings_enabled", True)
        res = rag.add_document(META, [(1, COTTON_DOC)])
        assert res["status"] == "added" and "keyword search only" in res["warning"]
        assert rag.search("pink bollworm cotton")           # keyword path still works, semantic is skipped quietly
    finally:
        srv.close()


def test_delete_document_removes_passages():
    d = rag.add_document(META, [(1, COTTON_DOC)])
    assert rag.delete_document(d["id"]) >= 1
    assert rag.search("pink bollworm") == [] and rag.stats()["documents"] == 0
