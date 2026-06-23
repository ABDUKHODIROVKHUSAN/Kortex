import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from app.config import settings

SYSTEM_PROMPT = """You are KORTEX, an expert AI document analyst. You help users understand their documents thoroughly and accurately.

When answering:
1. Always base your answer on the retrieved document context provided
2. Cite specific sections using [Page X] or [Section Y] references
3. If the answer is not in the document, clearly say so
4. Be concise but thorough
5. Format your answers with clear structure when appropriate"""


def _get_client() -> Any:
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def search_document(query: str, doc_id: str) -> list[dict]:
    from app.services import rag

    return rag.retrieve_context(doc_id, query)


def summarize_document(doc_id: str, n_chunks: int = 8) -> str:
    from app.services import rag, vector_store
    from app.services.embeddings import embed_query

    chunks = vector_store.search(doc_id, embed_query("summary overview main points"), top_k=n_chunks)
    context = rag.format_context(chunks)
    client = _get_client()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Summarize this document based on the following excerpts:\n\n{context}",
            }
        ],
    )
    return response.content[0].text


def compare_sections(section_a: str, section_b: str) -> str:
    client = _get_client()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Compare these two sections and highlight similarities and differences:\n\n"
                    f"Section A:\n{section_a}\n\nSection B:\n{section_b}"
                ),
            }
        ],
    )
    return response.content[0].text


TOOLS = [
    {
        "name": "search_document",
        "description": "Search the document vector store for relevant chunks",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "doc_id": {"type": "string", "description": "Document ID"},
            },
            "required": ["query", "doc_id"],
        },
    },
    {
        "name": "summarize_document",
        "description": "Generate a summary of the document",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "Document ID"},
            },
            "required": ["doc_id"],
        },
    },
    {
        "name": "compare_sections",
        "description": "Compare two text sections from the document",
        "input_schema": {
            "type": "object",
            "properties": {
                "section_a": {"type": "string"},
                "section_b": {"type": "string"},
            },
            "required": ["section_a", "section_b"],
        },
    },
]


def _run_tool(name: str, tool_input: dict) -> str:
    from app.services import rag

    if name == "search_document":
        chunks = search_document(tool_input["query"], tool_input["doc_id"])
        return rag.format_context(chunks)
    if name == "summarize_document":
        return summarize_document(tool_input["doc_id"])
    if name == "compare_sections":
        return compare_sections(tool_input["section_a"], tool_input["section_b"])
    return "Unknown tool"


def _claude_error_message(exc: Exception) -> str:
    text = str(exc).lower()
    if "credit balance is too low" in text:
        return (
            "**Unable to generate an answer**\n\n"
            "Your Anthropic API key is configured, but your account has "
            "**no API credits**.\n\n"
            "Add credits at https://console.anthropic.com/settings/billing "
            "then ask your question again."
        )
    if "invalid x-api-key" in text or "authentication" in text:
        return (
            "**Invalid Anthropic API key**\n\n"
            "Check `ANTHROPIC_API_KEY` in `backend/.env` and restart the backend."
        )
    return f"**AI request failed:** {exc}"


async def _stream_text_response(
    text: str, sources: list[dict]
) -> AsyncGenerator[tuple[str, list[dict] | None], None]:
    for word in text.split(" "):
        yield word + " ", None
        await asyncio.sleep(0.01)
    yield "", sources


async def _stream_mock_response(
    query: str, chunks: list[dict], sources: list[dict]
) -> AsyncGenerator[tuple[str, list[dict] | None], None]:
    preview = chunks[0]["text"][:120] + "..." if chunks else "No matching chunks found."
    response = (
        "**[Dev mode — no LLM configured]**\n\n"
        f"You asked: *{query}*\n\n"
        "RAG retrieval is working. Here is the top matched excerpt from your document:\n\n"
        f"> {preview}\n\n"
        "Add `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` to `backend/.env` and restart the server."
    )
    for word in response.split(" "):
        yield word + " ", None
        await asyncio.sleep(0.02)
    yield "", sources


async def stream_chat(
    doc_id: str, query: str, history: list[dict] | None = None
) -> AsyncGenerator[tuple[str, list[dict] | None], None]:
    """Yield (token_or_event, sources). Final yield has sources."""
    from app.services import rag

    chunks = rag.retrieve_context(doc_id, query)
    context = rag.format_context(chunks)
    sources = [
        {
            "text": c["text"][:200],
            "page": c.get("metadata", {}).get("page"),
            "paragraph_index": c.get("metadata", {}).get("paragraph_index"),
            "chunk_index": c.get("metadata", {}).get("chunk_index"),
        }
        for c in chunks
    ]

    if not settings.llm_enabled:
        async for item in _stream_mock_response(query, chunks, sources):
            yield item
        return

    if settings.llm_provider == "gemini":
        from app.services.gemini_llm import _gemini_error_message, stream_gemini_chat

        try:
            async for text in stream_gemini_chat(context, query, history, SYSTEM_PROMPT):
                yield text, None
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("Gemini API error")
            async for item in _stream_text_response(_gemini_error_message(exc), sources):
                yield item
            return
        yield "", sources
        return

    messages: list[dict] = []
    if history:
        for msg in history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append(
        {
            "role": "user",
            "content": (
                f"Document context:\n{context}\n\n"
                f"User question: {query}\n\n"
                "Answer based on the context above. Cite pages or sections."
            ),
        }
    )

    client = _get_client()

    try:
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        ) as stream:
            for text in stream.text_stream:
                yield text, None

        final = stream.get_final_message()

        while final.stop_reason == "tool_use":
            tool_results = []
            assistant_content = final.content

            for block in final.content:
                if block.type == "tool_use":
                    result = _run_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})

            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOLS,
            ) as stream:
                for text in stream.text_stream:
                    yield text, None

            final = stream.get_final_message()
    except Exception as exc:
        import logging

        logging.getLogger(__name__).exception("Claude API error")
        async for item in _stream_text_response(_claude_error_message(exc), sources):
            yield item
        return

    yield "", sources
