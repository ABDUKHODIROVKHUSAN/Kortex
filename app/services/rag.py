def retrieve_context(doc_id: str, query: str, top_k: int = 5) -> list[dict]:
    from app.services import embeddings, vector_store

    query_embedding = embeddings.embed_query(query)
    return vector_store.search(doc_id, query_embedding, top_k=top_k)


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
