import logging
from collections.abc import AsyncGenerator

from app.config import settings
from app.support.system_prompt import SUPPORT_CHAT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

SUPPORT_MODEL = "claude-sonnet-4-6"
FALLBACK_ERROR = "Something went wrong, please try again."
NOT_CONFIGURED = (
    "Support chat is temporarily unavailable — no AI provider is configured on this server."
)


def _get_async_client():
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


def _claude_support_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "credit balance is too low" in text:
        return (
            "Support chat couldn't reach Claude — your Anthropic API credits are depleted. "
            "Trying an alternate provider if available."
        )
    if "invalid x-api-key" in text or "authentication" in text:
        return "Support chat couldn't authenticate with Claude. Check ANTHROPIC_API_KEY in backend/.env."
    return FALLBACK_ERROR


async def _stream_claude_support(
    user_message: str,
    history: list[dict[str, str]],
) -> AsyncGenerator[str, None]:
    messages = [
        *[{"role": m["role"], "content": m["content"]} for m in history[-12:]],
        {"role": "user", "content": user_message},
    ]

    client = _get_async_client()
    async with client.messages.stream(
        model=SUPPORT_MODEL,
        max_tokens=512,
        system=SUPPORT_CHAT_SYSTEM_PROMPT,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def _stream_gemini_support(
    user_message: str,
    history: list[dict[str, str]],
) -> AsyncGenerator[str, None]:
    from app.services.gemini_llm import _gemini_error_message, stream_gemini_support

    try:
        async for text in stream_gemini_support(
            user_message, history, SUPPORT_CHAT_SYSTEM_PROMPT
        ):
            yield text
    except Exception as exc:
        logger.exception("Support chat Gemini API error")
        yield _gemini_error_message(exc).replace("**", "")


async def stream_support_reply(
    user_message: str,
    history: list[dict[str, str]],
) -> AsyncGenerator[str, None]:
    if not settings.claude_enabled and not settings.gemini_enabled:
        yield NOT_CONFIGURED
        return

    if settings.claude_enabled:
        try:
            got_text = False
            async for text in _stream_claude_support(user_message, history):
                got_text = True
                yield text
            if got_text:
                return
        except Exception as exc:
            logger.warning("Support chat Claude unavailable: %s", exc)
            if not settings.gemini_enabled:
                yield _claude_support_error(exc)
                return

    if settings.gemini_enabled:
        async for text in _stream_gemini_support(user_message, history):
            yield text
        return

    yield NOT_CONFIGURED
