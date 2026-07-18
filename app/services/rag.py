import time


def retrieve_context(
    doc_id: str, query: str, top_k: int = 5
) -> tuple[list[dict], dict]:
    """
    Hybrid retrieve relevant chunks for a document query.
    Returns (chunks, retrieval_meta).
    """
    from app.services import embeddings, vector_store

    started = time.perf_counter()
    query_embedding = embeddings.embed_query(query)
    chunks = vector_store.hybrid_search(doc_id, query, query_embedding, top_k=top_k)
    latency_ms = int((time.perf_counter() - started) * 1000)

    meta = {
        "method": "hybrid",
        "top_k": top_k,
        "chunk_count": len(chunks),
        "latency_ms": latency_ms,
    }
    return chunks, meta


def format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "No relevant context found in the document."

    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk.get("metadata", {})
        ref = ""
        if "page" in meta:
            ref = f"[Page {meta['page']}]"
        elif "paragraph_index" in meta:
            ref = f"[Section {meta['paragraph_index']}]"

        parts.append(f"--- Chunk {i} {ref} ---\n{chunk['text']}")

    return "\n\n".join(parts)
