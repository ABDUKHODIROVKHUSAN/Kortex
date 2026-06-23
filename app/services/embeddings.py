from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_model: Any = None


def load_embedding_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def embed_chunks(chunks: list[str]) -> list[list[float]]:
    model = load_embedding_model()
    embeddings = model.encode(chunks, show_progress_bar=False)
    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    model = load_embedding_model()
    embedding = model.encode(query, show_progress_bar=False)
    return embedding.tolist()
