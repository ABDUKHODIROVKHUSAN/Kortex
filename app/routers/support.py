import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.support.rate_limit import rate_limiter
from app.support.stream import FALLBACK_ERROR, stream_support_reply

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_ORIGINS = set(settings.cors_origins_list)


def _client_ip(websocket: WebSocket) -> str:
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if websocket.client:
        return websocket.client.host
    return "unknown"


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    return origin in ALLOWED_ORIGINS


async def _send_json(websocket: WebSocket, payload: dict) -> None:
    await websocket.send_text(json.dumps(payload))


@router.websocket("/ws")
async def support_chat_ws(websocket: WebSocket) -> None:
    if not _origin_allowed(websocket):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    history: list[dict[str, str]] = []

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _send_json(
                    websocket,
                    {"type": "error", "message": "Invalid message format."},
                )
                continue

            if data.get("type") == "ping":
                await _send_json(websocket, {"type": "pong"})
                continue

            if data.get("type") != "message":
                continue

            content = (data.get("content") or "").strip()
            if not content:
                continue

            client_ip = _client_ip(websocket)
            if not rate_limiter.allow(client_ip):
                await _send_json(
                    websocket,
                    {
                        "type": "error",
                        "message": "Too many messages — please wait a moment and try again.",
                    },
                )
                continue

            history.append({"role": "user", "content": content})

            try:
                got_token = False
                assistant_parts: list[str] = []

                async for token in stream_support_reply(content, history[:-1]):
                    if not token:
                        continue
                    got_token = True
                    assistant_parts.append(token)
                    await _send_json(websocket, {"type": "token", "content": token})

                assistant_text = "".join(assistant_parts).strip()
                if assistant_text:
                    history.append({"role": "assistant", "content": assistant_text})

                if not got_token:
                    await _send_json(
                        websocket,
                        {"type": "error", "message": FALLBACK_ERROR},
                    )

                await _send_json(websocket, {"type": "done"})
            except Exception:
                logger.exception("Support chat stream failed")
                await _send_json(
                    websocket,
                    {"type": "error", "message": FALLBACK_ERROR},
                )
                await _send_json(websocket, {"type": "done"})

    except WebSocketDisconnect:
        logger.debug("Support chat WebSocket disconnected")
    except Exception:
        logger.exception("Support chat WebSocket error")
        try:
            await _send_json(
                websocket,
                {"type": "error", "message": FALLBACK_ERROR},
            )
        except Exception:
            pass
