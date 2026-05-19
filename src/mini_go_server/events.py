from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any
import asyncio


@dataclass(frozen=True)
class ServerEvent:
    sequence: int
    type: str
    payload: dict[str, Any]


class EventBus:
    def __init__(self, history_limit: int = 200) -> None:
        self._history: deque[ServerEvent] = deque(maxlen=history_limit)
        self._subscribers: set[object] = set()
        self._sequence = 0

    def publish(self, event_type: str, **payload: Any) -> ServerEvent:
        self._sequence += 1
        event = ServerEvent(self._sequence, event_type, payload)
        self._history.append(event)
        for subscriber in list(self._subscribers):
            subscriber.put_nowait(event)  # type: ignore[attr-defined]
        return event

    def history(self) -> list[ServerEvent]:
        return list(self._history)

    def subscribe(self) -> object:
        queue: asyncio.Queue[ServerEvent] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, subscriber: object) -> None:
        self._subscribers.discard(subscriber)
