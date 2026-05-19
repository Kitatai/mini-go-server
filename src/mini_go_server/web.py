from __future__ import annotations

import asyncio
import json
import logging
from html import escape
from typing import Any

from .events import EventBus, ServerEvent

LOGGER = logging.getLogger(__name__)


class WebViewer:
    def __init__(self, events: EventBus, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.events = events
        self.host = host
        self.port = port

    async def start(self) -> None:
        server = await asyncio.start_server(self.handle_connection, self.host, self.port)
        sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
        LOGGER.info("web viewer listening on %s", sockets)
        async with server:
            await server.serve_forever()

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return
            method, path, _version = request_line.decode("latin-1").strip().split(" ", 2)
            await self.consume_headers(reader)

            if method != "GET":
                await self.send_response(writer, "405 Method Not Allowed", "text/plain; charset=utf-8", b"method not allowed")
            elif path in {"/", "/index.html"}:
                await self.send_response(writer, "200 OK", "text/html; charset=utf-8", INDEX_HTML.encode("utf-8"))
            elif path == "/events":
                await self.handle_events(writer)
                return
            else:
                await self.send_response(writer, "404 Not Found", "text/plain; charset=utf-8", b"not found")
        except Exception as exc:
            LOGGER.debug("web viewer request failed: %s", exc)
        finally:
            writer.close()
            await writer.wait_closed()

    async def consume_headers(self, reader: asyncio.StreamReader) -> None:
        while True:
            line = await reader.readline()
            if line in {b"\r\n", b"\n", b""}:
                return

    async def send_response(self, writer: asyncio.StreamWriter, status: str, content_type: str, body: bytes) -> None:
        headers = [
            f"HTTP/1.1 {status}",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body)}",
            "Cache-Control: no-store",
            "Connection: close",
            "",
            "",
        ]
        writer.write("\r\n".join(headers).encode("ascii") + body)
        await writer.drain()

    async def handle_events(self, writer: asyncio.StreamWriter) -> None:
        headers = [
            "HTTP/1.1 200 OK",
            "Content-Type: text/event-stream; charset=utf-8",
            "Cache-Control: no-store",
            "Connection: keep-alive",
            "X-Accel-Buffering: no",
            "",
            "",
        ]
        writer.write("\r\n".join(headers).encode("ascii"))
        for event in self.events.history():
            writer.write(format_sse(event))
        await writer.drain()

        subscription = self.events.subscribe()
        try:
            while True:
                event = await subscription.get()  # type: ignore[attr-defined]
                writer.write(format_sse(event))
                await writer.drain()
        finally:
            self.events.unsubscribe(subscription)


def format_sse(event: ServerEvent) -> bytes:
    data = {"sequence": event.sequence, "type": event.type, **event.payload}
    return f"event: {escape(event.type)}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


INDEX_HTML = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mini-Go Viewer</title>
  <style>
    :root {
      color-scheme: light;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #20242a;
    }
    body {
      margin: 0;
    }
    header {
      border-bottom: 1px solid #d9dde3;
      background: #ffffff;
      padding: 16px 24px;
    }
    h1 {
      font-size: 20px;
      margin: 0 0 4px;
    }
    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 24px;
    }
    .status {
      color: #5c6673;
      font-size: 14px;
    }
    .board {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 16px 0;
    }
    .cell {
      width: 40px;
      height: 40px;
      border: 1px solid #b7bec8;
      display: grid;
      place-items: center;
      font-weight: 700;
      background: #ffffff;
    }
    .black {
      background: #20242a;
      color: #ffffff;
    }
    .white {
      background: #ffffff;
      color: #20242a;
      box-shadow: inset 0 0 0 2px #20242a;
    }
    .panel {
      background: #ffffff;
      border: 1px solid #d9dde3;
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
    }
    .meta {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 8px;
      font-size: 14px;
    }
    .log {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      line-height: 1.5;
      white-space: pre-wrap;
      max-height: 420px;
      overflow: auto;
    }
  </style>
</head>
<body>
  <header>
    <h1>Mini-Go Viewer</h1>
    <div id="connection" class="status">接続中</div>
  </header>
  <main>
    <section class="panel">
      <div id="meta" class="meta"></div>
      <div id="board" class="board"></div>
    </section>
    <section class="panel">
      <div id="log" class="log"></div>
    </section>
  </main>
  <script>
    const connection = document.getElementById("connection");
    const meta = document.getElementById("meta");
    const board = document.getElementById("board");
    const log = document.getElementById("log");
    const state = {};

    function renderBoard(text) {
      if (!text) return;
      board.innerHTML = "";
      [...text].forEach((cell, index) => {
        const el = document.createElement("div");
        el.className = "cell";
        if (cell === "X") el.classList.add("black");
        if (cell === "O") el.classList.add("white");
        el.textContent = cell === "." ? String(index) : cell;
        board.appendChild(el);
      });
    }

    function renderMeta() {
      const items = [
        ["match", state.match_id ?? "-"],
        ["BLACK", state.black ?? "-"],
        ["WHITE", state.white ?? "-"],
        ["next", state.next_turn ?? "-"],
        ["result", state.result ?? "-"],
      ];
      meta.innerHTML = items.map(([k, v]) => `<div><strong>${k}</strong>: ${v}</div>`).join("");
    }

    function appendLog(event) {
      const line = `[${event.sequence}] ${event.type} ${JSON.stringify(event)}\\n`;
      log.textContent += line;
      log.scrollTop = log.scrollHeight;
    }

    function applyEvent(event) {
      if (event.match_id !== undefined) state.match_id = event.match_id;
      if (event.black) state.black = event.black;
      if (event.white) state.white = event.white;
      if (event.next_turn) state.next_turn = event.next_turn;
      if (event.board) renderBoard(event.board);
      if (event.type === "match_finished") state.result = `${event.winner_name} (${event.winner}) ${event.reason}`;
      if (event.type === "match_forfeited") state.result = `${event.winner_name} wins by ${event.reason}`;
      renderMeta();
      appendLog(event);
    }

    renderMeta();
    const source = new EventSource("/events");
    source.onopen = () => { connection.textContent = "接続済み"; };
    source.onerror = () => { connection.textContent = "再接続中"; };
    source.onmessage = (message) => applyEvent(JSON.parse(message.data));
    ["server_started", "client_ready", "match_started", "opening_move", "pie_selected", "move_played", "match_finished", "match_forfeited"].forEach((name) => {
      source.addEventListener(name, (message) => applyEvent(JSON.parse(message.data)));
    });
  </script>
</body>
</html>
"""
