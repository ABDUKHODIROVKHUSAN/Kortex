"""Hybrid retrieval: dense (vector) + sparse (BM25) fused with Reciprocal Rank Fusion."""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[가-힣]+|[a-zA-Z0-9]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Tokenize for BM25 — works for Korean Hangul runs and Latin/numeric tokens."""
    return _TOKEN_RE.findall(text.lower())


def reciprocal_rank_fusion(
    ranked_id_lists: list[list[str]], k: int = 60
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranked_ids in ranked_id_lists:
        for rank, doc_id in enumerate(ranked_ids):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def bm25_rank(
    query: str, documents: list[str], ids: list[str], top_k: int
) -> list[str]:
    from rank_bm25 import BM25Okapi

    if not documents:
        return []

    corpus = [tokenize(doc) for doc in documents]
    # Empty docs break BM25 — give them a placeholder token
    corpus = [tokens if tokens else ["_"] for tokens in corpus]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(tokenize(query) or ["_"])
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return [ids[i] for i in ranked[:top_k]]


def hybrid_search(
    *,
    query: str,
    query_embedding: list[float],
    collection: Any,
    top_k: int = 5,
    candidate_k: int | None = None,
) -> list[dict]:
    """
    Run vector search + BM25 over the collection, fuse with RRF, return top_k chunks.
    Each result includes text, metadata, distance (vector if available), and rrf_score.
    """
    fetch_k = candidate_k or max(top_k * 4, 20)

    try:
        all_data = collection.get(include=["documents", "metadatas"])
    except Exception:
        return []

    ids: list[str] = all_data.get("ids") or []
    documents: list[str] = all_data.get("documents") or []
    metadatas: list[dict] = all_data.get("metadatas") or []

    if not ids:
        return []

    id_to_payload = {
        ids[i]: {
            "text": documents[i] if i < len(documents) else "",
            "metadata": metadatas[i] if i < len(metadatas) else {},
        }
        for i in range(len(ids))
    }

    # Dense retrieval
    vector_ids: list[str] = []
    vector_distance: dict[str, float] = {}
    try:
        n_results = min(fetch_k, len(ids))
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        if results.get("ids") and results["ids"][0]:
            for i, vid in enumerate(results["ids"][0]):
                vector_ids.append(vid)
                if results.get("distances") and results["distances"][0]:
                    vector_distance[vid] = results["distances"][0][i]
    except Exception:
        vector_ids = []

    # Sparse retrieval
    sparse_ids = bm25_rank(query, documents, ids, top_k=min(fetch_k, len(ids)))

    fused = reciprocal_rank_fusion([vector_ids, sparse_ids])
    top = fused[:top_k]

    chunks: list[dict] = []
    for doc_id, rrf_score in top:
        payload = id_to_payload.get(doc_id)
        if not payload:
            continue
        chunks.append(
            {
                "text": payload["text"],
                "metadata": payload["metadata"],
                "distance": vector_distance.get(doc_id),
                "rrf_score": rrf_score,
                "retrieval_method": "hybrid",
            }
        )

    return chunks
