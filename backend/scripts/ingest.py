"""Add trusted agricultural documents to the assistant's knowledge base.

Examples (run from the backend folder):
  python scripts/ingest.py --url https://example.org/guide.pdf --title "Cotton IPM guide" \
      --publisher "State Agricultural University" --published 2023-06-01 --crops cotton
  python scripts/ingest.py --file kb/my-notes.pdf --title "Soybean package of practices" --publisher "ICAR"
  python scripts/ingest.py --manifest kb/sources.json
  python scripts/ingest.py --list
  python scripts/ingest.py --delete 3
Only add material you are allowed to use. Prefer official open government and university publications.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import ingest, rag  # noqa: E402
from app.db import init_db, q  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--url", help="download this link, or with --file: the link to show as the source"); ap.add_argument("--file"); ap.add_argument("--manifest")
ap.add_argument("--title"); ap.add_argument("--publisher"); ap.add_argument("--published", help="YYYY or YYYY-MM-DD")
ap.add_argument("--crops", help="comma separated, e.g. cotton,soybean. Leave empty if general")
ap.add_argument("--language", default="en"); ap.add_argument("--license-note")
ap.add_argument("--list", action="store_true"); ap.add_argument("--delete", type=int)
a = ap.parse_args()
init_db()

meta = {k: v for k, v in dict(title=a.title, publisher=a.publisher, published=a.published, crops=a.crops, language=a.language, license_note=a.license_note).items() if v}
def main():
    if a.list:
        for d in q("SELECT d.id, d.title, d.publisher, d.published, d.url, (SELECT COUNT(*) FROM kb_chunks c WHERE c.doc_id=d.id) AS chunks FROM kb_documents d ORDER BY d.id"):
            print(f"{d['id']:>4}  {d['title']}  |  {d['publisher']}  |  {d['published']}  |  {d['chunks']} passages  |  {d['url'] or ''}")
        print(rag.stats())
    elif a.delete:
        print("deleted passages:", rag.delete_document(a.delete))
    elif a.manifest:
        for r in ingest.ingest_manifest(a.manifest):
            print(r)
    elif a.file:  # --url here is only the citation link shown to farmers
        meta_f = dict(meta, url=a.url) if a.url else meta
        print(ingest.ingest_file(a.file, meta_f))
    elif a.url:
        print(ingest.ingest_url(a.url, meta))
    else:
        ap.print_help()


try:
    main()
except Exception as exc:  # noqa: BLE001
    print(f"Failed: {exc}")
    sys.exit(1)
