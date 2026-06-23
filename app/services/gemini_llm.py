import json
from collections.abc import AsyncGenerator

import httpx

from app.config import settings

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _gemini_error_message(exc: Exception) -> str:
    text = str(exc).lower()
    if "api key not valid" in text or "api_key_invalid" in text:
        return (
            "**Invalid Gemini API key**\n\n"
            "Check `GEMINI_API_KEY` in `backend/.env` and restart the backend."
        )
    if "limit: 0" in text:
        return (
            "**Gemini free quota not available for this model**\n\n"
            f"Your key works, but `{settings.GEMINI_MODEL}` has **no free-tier quota** "
            "on your account (Google reports limit: 0).\n\n"
            "In `backend/.env`, change to:\n"
            "`GEMINI_MODEL=gemini-2.5-flash-lite`\n\n"
            "Then restart the backend and try again."
        )
    if "quota" in text or "rate limit" in text or "resource_exhausted" in text:
        return (
            "**Gemini quota limit reached**\n\n"
            "You may have hit the free tier daily/minute cap. Wait a bit, try "
            "`GEMINI_MODEL=gemini-2.5-flash-lite`, or check "
            "https://aistudio.google.com/"
        )
    return f"**Gemini request failed:** {exc}"


def _build_contents(
    context: str, query: str, history: list[dict] | None
) -> list[dict]:
    contents: list[dict] = []
    if history:
        for msg in history[-10:]:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        f"Document context:\n{context}\n\n"
                        f"User question: {query}\n\n"
                        "Answer based on the context above. Cite pages or sections."
                    )
                }
            ],
        }
    )
    return contents


def _build_support_contents(query: str, history: list[dict] | None) -> list[dict]:
    contents: list[dict] = []
    if history:
        for msg in history[-10:]:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": query}]})
    return contents


async def stream_gemini_support(
    query: str,
    history: list[dict] | None,
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    url = (
        f"{GEMINI_API_BASE}/models/{settings.GEMINI_MODEL}:streamGenerateContent"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": _build_support_contents(query, history),
        "generationConfig": {"maxOutputTokens": 512},
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            url,
            params={"key": settings.GEMINI_API_KEY, "alt": "sse"},
            json=payload,
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                try:
                    detail = json.loads(body).get("error", {}).get("message", body.decode())
                except json.JSONDecodeError:
                    detail = body.decode(errors="replace")
                raise RuntimeError(detail)

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                for candidate in data.get("candidates", []):
                    content = candidate.get("content", {})
                    for part in content.get("parts", []):
                        text = part.get("text")
                        if text:
                            yield text


async def stream_gemini_chat(
    context: str,
    query: str,
    history: list[dict] | None,
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    url = (
        f"{GEMINI_API_BASE}/models/{settings.GEMINI_MODEL}:streamGenerateContent"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": _build_contents(context, query, history),
        "generationConfig": {"maxOutputTokens": 4096},
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            url,
            params={"key": settings.GEMINI_API_KEY, "alt": "sse"},
            json=payload,
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                try:
                    detail = json.loads(body).get("error", {}).get("message", body.decode())
                except json.JSONDecodeError:
                    detail = body.decode(errors="replace")
                raise RuntimeError(detail)

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                for candidate in data.get("candidates", []):
                    content = candidate.get("content", {})
                    for part in content.get("parts", []):
                        text = part.get("text")
                        if text:
                            yield text
