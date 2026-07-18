from typing import Any

from app.config import settings

_client: Any = None


def get_chroma_client() -> Any:
    global _client
    if _client is None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        _client = chromadb.PersistentClient(
            path=settings.CHROMA_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def _collection_name(doc_id: str) -> str:
    return f"kortex_{doc_id.replace('-', '_')}"


def add_document(
    doc_id: str, chunks: list[dict], embeddings: list[list[float]]
) -> None:
    client = get_chroma_client()
    collection = client.get_or_create_collection(name=_collection_name(doc_id))

    ids = [f"{doc_id}_{chunk['metadata']['chunk_index']}" for chunk in chunks]
    documents = [chunk["text"] for chunk in chunks]
    metadatas = [chunk["metadata"] for chunk in chunks]

    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def search(
    doc_id: str, query_embedding: list[float], top_k: int = 5
) -> list[dict]:
    """Dense-only vector search (kept for summarize / tooling)."""
    client = get_chroma_client()
    name = _collection_name(doc_id)

    try:
        collection = client.get_collection(name=name)
    except Exception:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[dict] = []
    if not results["documents"] or not results["documents"][0]:
        return chunks

    for i, doc in enumerate(results["documents"][0]):
        metadata = results["metadatas"][0][i] if results["metadatas"] else {}
        distance = results["distances"][0][i] if results["distances"] else None
        chunks.append(
            {
                "text": doc,
                "metadata": metadata,
                "distance": distance,
                "retrieval_method": "vector",
            }
        )

    return chunks


def hybrid_search(
    doc_id: str,
    query: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    """Dense + BM25 hybrid search with RRF fusion."""
    from app.services.hybrid_search import hybrid_search as _hybrid

    client = get_chroma_client()
    name = _collection_name(doc_id)

    try:
        collection = client.get_collection(name=name)
    except Exception:
        return []

    return _hybrid(
        query=query,
        query_embedding=query_embedding,
        collection=collection,
        top_k=top_k,
    )


def delete_document(doc_id: str) -> None:
    client = get_chroma_client()
    name = _collection_name(doc_id)
    try:
        client.delete_collection(name=name)
    except Exception:
        pass
