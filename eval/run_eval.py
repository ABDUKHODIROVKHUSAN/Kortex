"""
Offline retrieval eval for Kortex hybrid search.

Usage (from backend/, with venv active):
  python eval/run_eval.py --pdf ../frontend/public/demo/kortex-sample-ko.pdf

Does not call an LLM — scores retrieval hit-rate only (page + keyword overlap).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pdf",
        type=Path,
        default=ROOT.parent / "frontend" / "public" / "demo" / "kortex-sample-ko.pdf",
    )
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=Path(__file__).with_name("eval_set.json"),
    )
    args = parser.parse_args()

    if not args.pdf.exists():
        raise SystemExit(f"PDF not found: {args.pdf}. Run scripts/generate_demo_pdf.py first.")

    from app.services import embeddings, parser, vector_store
    from app.services.rag import retrieve_context

    with open(args.eval_set, encoding="utf-8") as f:
        suite = json.load(f)

    doc_id = str(uuid.uuid4())
    pages = parser.parse_pdf(str(args.pdf))
    chunks = parser.chunk_text(pages, doc_id, chunk_size=500, overlap=50)
    texts = [c["text"] for c in chunks]
    emb = embeddings.embed_chunks(texts)
    vector_store.add_document(doc_id, chunks, emb)

    hits = 0
    keyword_hits = 0
    rows = []

    try:
        for case in suite["cases"]:
            retrieved, meta = retrieve_context(doc_id, case["question"], top_k=5)
            pages_hit = {
                c.get("metadata", {}).get("page")
                for c in retrieved
                if c.get("metadata", {}).get("page") is not None
            }
            page_ok = case.get("expected_page") in pages_hit
            joined = " ".join(c["text"] for c in retrieved)
            kw_ok = any(k in joined for k in case.get("must_include_any", []))
            if page_ok:
                hits += 1
            if kw_ok:
                keyword_hits += 1
            rows.append(
                {
                    "id": case["id"],
                    "page_hit": page_ok,
                    "keyword_hit": kw_ok,
                    "latency_ms": meta.get("latency_ms"),
                    "top_pages": sorted(p for p in pages_hit if p is not None),
                }
            )
    finally:
        vector_store.delete_document(doc_id)

    n = len(suite["cases"])
    print(f"Cases: {n}")
    print(f"Page hit-rate:     {hits}/{n} ({100 * hits / n:.0f}%)")
    print(f"Keyword hit-rate:  {keyword_hits}/{n} ({100 * keyword_hits / n:.0f}%)")
    for row in rows:
        status = "OK" if row["page_hit"] and row["keyword_hit"] else "MISS"
        print(
            f"  [{status}] {row['id']}  pages={row['top_pages']}  "
            f"latency={row['latency_ms']}ms"
        )


if __name__ == "__main__":
    main()
