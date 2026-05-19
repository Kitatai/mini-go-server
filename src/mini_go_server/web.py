from __future__ import annotations

import asyncio
import json
import logging
from importlib import resources
from typing import Any

from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError

from .events import EventBus, ServerEvent

LOGGER = logging.getLogger(__name__)


class WebViewer:
    def __init__(self, events: EventBus, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.events = events
        self.host = host
        self.port = port

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/index.html", self.index)
        app.router.add_get("/static/style.css", self.style)
        app.router.add_get("/static/viewer.js", self.script)
        app.router.add_get("/events", self.event_stream)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        LOGGER.info("web viewer listening on http://%s:%s/", self.host, self.port)
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()

    async def index(self, _request: web.Request) -> web.Response:
        return web.Response(text=read_static_text("index.html"), content_type="text/html")

    async def style(self, _request: web.Request) -> web.Response:
        return web.Response(text=read_static_text("style.css"), content_type="text/css")

    async def script(self, _request: web.Request) -> web.Response:
        return web.Response(text=read_static_text("viewer.js"), content_type="application/javascript")

    async def event_stream(self, _request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(_request)

        subscription = self.events.subscribe()
        try:
            for event in self.events.history():
                await response.write(format_sse(event))
            await response.drain()

            while True:
                event = await subscription.get()  # type: ignore[attr-defined]
                await response.write(format_sse(event))
                await response.drain()
        except (ClientConnectionResetError, ConnectionResetError, asyncio.CancelledError):
            LOGGER.debug("web viewer client disconnected")
        finally:
            self.events.unsubscribe(subscription)
        return response


def format_sse(event: ServerEvent) -> bytes:
    data: dict[str, Any] = {"sequence": event.sequence, "type": event.type, **event.payload}
    event_name = event.type.replace("\n", "")
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def read_static_text(filename: str) -> str:
    return resources.files("mini_go_server.static").joinpath(filename).read_text(encoding="utf-8")


