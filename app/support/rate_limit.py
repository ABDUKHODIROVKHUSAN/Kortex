import time
from collections import defaultdict, deque

MAX_MESSAGES_PER_MINUTE = 20
WINDOW_SECONDS = 60


class SupportChatRateLimiter:
    """In-memory sliding-window rate limiter keyed by client IP."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, client_key: str) -> bool:
        now = time.monotonic()
        window_start = now - WINDOW_SECONDS
        events = self._events[client_key]

        while events and events[0] <= window_start:
            events.popleft()

        if len(events) >= MAX_MESSAGES_PER_MINUTE:
            return False

        events.append(now)
        return True


rate_limiter = SupportChatRateLimiter()
