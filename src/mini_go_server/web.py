from __future__ import annotations

import asyncio
import json
import logging
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
        return web.Response(text=INDEX_HTML, content_type="text/html")

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


INDEX_HTML = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mini-Go Viewer</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #edf0f2;
      color: #171a1f;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 12% 12%, rgba(194, 210, 221, 0.55), transparent 28rem),
        linear-gradient(135deg, #f7f8f7 0%, #e9edf0 45%, #dfe5e7 100%);
    }
    .shell {
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px;
    }
    header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 24px;
    }
    h1 {
      font-size: 30px;
      line-height: 1.1;
      margin: 0 0 8px;
      letter-spacing: 0;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 34px;
      border-radius: 999px;
      padding: 7px 12px;
      border: 1px solid rgba(20, 26, 32, 0.12);
      background: rgba(255, 255, 255, 0.72);
      box-shadow: 0 10px 30px rgba(24, 35, 44, 0.08);
      font-size: 13px;
      color: #3e4752;
      white-space: nowrap;
    }
    .dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #a0a8b2;
    }
    .connected .dot {
      background: #24865a;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 18px;
      align-items: start;
    }
    .surface {
      border: 1px solid rgba(27, 34, 42, 0.12);
      background: rgba(255, 255, 255, 0.82);
      backdrop-filter: blur(18px);
      box-shadow: 0 24px 70px rgba(28, 38, 48, 0.12);
      border-radius: 8px;
    }
    .board-panel {
      padding: 24px;
    }
    .match-line {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 22px;
      color: #4d5966;
      font-size: 14px;
    }
    .result {
      color: #15191e;
      font-weight: 700;
    }
    .players {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 22px;
    }
    .player {
      padding: 14px;
      border: 1px solid rgba(27, 34, 42, 0.1);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.68);
    }
    .player-label {
      display: flex;
      align-items: center;
      gap: 8px;
      color: #64707d;
      font-size: 12px;
      text-transform: uppercase;
    }
    .player-name {
      margin-top: 8px;
      font-size: 18px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .tiny-stone {
      width: 16px;
      height: 16px;
      border-radius: 50%;
      display: inline-block;
      flex: none;
    }
    .tiny-stone.black {
      background: radial-gradient(circle at 32% 28%, #666d75, #15181d 58%, #060708);
      box-shadow: inset -2px -3px 5px rgba(0, 0, 0, 0.45);
    }
    .tiny-stone.white {
      background: radial-gradient(circle at 32% 28%, #ffffff, #f0f1ef 55%, #c7cac5);
      border: 1px solid #b9bdb8;
      box-shadow: inset -2px -3px 5px rgba(105, 109, 104, 0.2);
    }
    .goban-wrap {
      overflow-x: auto;
      padding: 14px 4px 6px;
    }
    .goban {
      --cell-size: 52px;
      --line-color: rgba(72, 58, 39, 0.52);
      position: relative;
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: var(--cell-size);
      min-height: 86px;
      width: max-content;
      padding: 18px 0;
    }
    .goban::before {
      content: "";
      position: absolute;
      left: calc(var(--cell-size) / 2);
      right: calc(var(--cell-size) / 2);
      top: 44px;
      height: 2px;
      background: var(--line-color);
    }
    .point {
      width: var(--cell-size);
      height: 66px;
      display: grid;
      place-items: start center;
      position: relative;
    }
    .point::before {
      content: "";
      position: absolute;
      top: 21px;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: rgba(72, 58, 39, 0.42);
      transform: translateY(-50%);
    }
    .stone {
      position: relative;
      z-index: 1;
      width: 42px;
      height: 42px;
      border-radius: 50%;
      margin-top: 0;
      display: grid;
      place-items: center;
      font-size: 11px;
      font-weight: 700;
    }
    .stone.empty {
      color: #79836f;
      background: transparent;
      margin-top: 23px;
      width: auto;
      height: auto;
    }
    .stone.black {
      background: radial-gradient(circle at 30% 25%, #707881 0%, #1b1f25 58%, #07080a 100%);
      color: transparent;
      box-shadow: inset -6px -8px 12px rgba(0, 0, 0, 0.48), 0 10px 18px rgba(0, 0, 0, 0.22);
    }
    .stone.white {
      background: radial-gradient(circle at 30% 24%, #ffffff 0%, #f4f4f1 52%, #c8ccc5 100%);
      color: transparent;
      border: 1px solid rgba(98, 101, 96, 0.38);
      box-shadow: inset -5px -7px 12px rgba(112, 116, 108, 0.2), 0 10px 18px rgba(58, 65, 70, 0.16);
    }
    .last .stone {
      outline: 3px solid #4e8f7c;
      outline-offset: 3px;
    }
    .index {
      position: absolute;
      top: 52px;
      font-size: 11px;
      color: #76806f;
    }
    .side {
      display: grid;
      gap: 14px;
    }
    .stat-grid {
      display: grid;
      gap: 10px;
      padding: 16px;
    }
    .stat {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid rgba(27, 34, 42, 0.08);
      padding-bottom: 10px;
      color: #5e6874;
      font-size: 13px;
    }
    .stat:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }
    .stat strong {
      color: #171a1f;
      text-align: right;
      overflow-wrap: anywhere;
    }
    details {
      overflow: hidden;
    }
    summary {
      display: flex;
      align-items: center;
      gap: 10px;
      cursor: pointer;
      padding: 16px;
      font-weight: 700;
      list-style: none;
    }
    summary::before {
      content: "›";
      display: grid;
      place-items: center;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      border: 1px solid rgba(27, 34, 42, 0.16);
      background: rgba(255, 255, 255, 0.72);
      color: #4d5966;
      font-size: 18px;
      line-height: 1;
      transition: transform 0.16s ease;
    }
    details[open] summary::before {
      transform: rotate(90deg);
    }
    summary::-webkit-details-marker {
      display: none;
    }
    .log {
      border-top: 1px solid rgba(27, 34, 42, 0.08);
      padding: 14px 16px 16px;
      max-height: 360px;
      overflow: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-wrap;
      color: #303842;
      background: rgba(246, 248, 248, 0.72);
    }
    @media (max-width: 840px) {
      .shell {
        padding: 18px;
      }
      header {
        flex-direction: column;
      }
      .layout {
        grid-template-columns: 1fr;
      }
      .players {
        grid-template-columns: 1fr;
      }
      .goban {
        --cell-size: 46px;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>Mini-Go Viewer</h1>
      </div>
      <div id="connection" class="status-pill"><span class="dot"></span><span>接続中</span></div>
    </header>
    <div class="layout">
      <section class="surface board-panel">
        <div class="match-line">
          <div id="matchTitle">対局待機中</div>
          <div id="result" class="result">進行前</div>
        </div>
        <div class="players">
          <div class="player">
            <div class="player-label"><span class="tiny-stone black"></span>BLACK</div>
            <div id="blackName" class="player-name">-</div>
          </div>
          <div class="player">
            <div class="player-label"><span class="tiny-stone white"></span>WHITE</div>
            <div id="whiteName" class="player-name">-</div>
          </div>
        </div>
        <div class="goban-wrap">
          <div id="board" class="goban"></div>
        </div>
      </section>
      <aside class="side">
        <section class="surface stat-grid">
          <div class="stat"><span>手番</span><strong id="nextTurn">-</strong></div>
          <div class="stat"><span>最終手</span><strong id="lastMove">-</strong></div>
          <div class="stat"><span>OPEN</span><strong id="openPlayer">-</strong></div>
          <div class="stat"><span>初手</span><strong id="openingMove">-</strong></div>
          <div class="stat"><span>イベント</span><strong id="eventCount">0</strong></div>
        </section>
        <details class="surface">
          <summary>イベントログ</summary>
          <div id="log" class="log"></div>
        </details>
      </aside>
    </div>
  </div>
  <script>
    const state = { eventCount: 0, board: "" };
    const ids = {
      connection: document.getElementById("connection"),
      matchTitle: document.getElementById("matchTitle"),
      result: document.getElementById("result"),
      blackName: document.getElementById("blackName"),
      whiteName: document.getElementById("whiteName"),
      nextTurn: document.getElementById("nextTurn"),
      lastMove: document.getElementById("lastMove"),
      openPlayer: document.getElementById("openPlayer"),
      openingMove: document.getElementById("openingMove"),
      eventCount: document.getElementById("eventCount"),
      board: document.getElementById("board"),
      log: document.getElementById("log"),
    };

    function setConnection(text, connected) {
      ids.connection.classList.toggle("connected", connected);
      ids.connection.querySelector("span:last-child").textContent = text;
    }

    function renderBoard(text, lastMove) {
      if (!text) return;
      state.board = text;
      ids.board.innerHTML = "";
      [...text].forEach((cell, index) => {
        const point = document.createElement("div");
        point.className = "point";
        if (index === lastMove) point.classList.add("last");
        const stone = document.createElement("div");
        stone.className = "stone";
        if (cell === "X") stone.classList.add("black");
        if (cell === "O") stone.classList.add("white");
        if (cell === ".") stone.classList.add("empty");
        stone.textContent = cell === "." ? "" : cell;
        const label = document.createElement("div");
        label.className = "index";
        label.textContent = String(index);
        point.append(stone, label);
        ids.board.appendChild(point);
      });
    }

    function appendLog(event) {
      ids.log.textContent += `[${event.sequence}] ${event.type} ${JSON.stringify(event)}\\n`;
      ids.log.scrollTop = ids.log.scrollHeight;
    }

    function applyEvent(event) {
      state.eventCount = event.sequence;
      if (event.match_id !== undefined) {
        state.matchId = event.match_id;
        ids.matchTitle.textContent = `match ${event.match_id}`;
      }
      if (event.black) ids.blackName.textContent = event.black;
      if (event.white) ids.whiteName.textContent = event.white;
      if (event.next_turn) ids.nextTurn.textContent = event.next_turn;
      if (event.move !== undefined) ids.lastMove.textContent = `${event.color ?? ""} ${event.move}`;
      if (event.board) renderBoard(event.board, event.move);
      if (event.type === "match_started") {
        ids.result.textContent = "対局中";
        ids.openPlayer.textContent = event.opener ?? "-";
        ids.openingMove.textContent = "-";
        ids.nextTurn.textContent = "PIE_OPEN";
      }
      if (event.type === "opening_move") {
        ids.openPlayer.textContent = event.player ?? ids.openPlayer.textContent;
        ids.openingMove.textContent = `${event.move}`;
        ids.nextTurn.textContent = "PIE_CHOOSE";
      }
      if (event.type === "pie_selected") {
        ids.nextTurn.textContent = "WHITE";
      }
      if (event.type === "match_finished") {
        ids.result.textContent = `${event.winner_name} (${event.winner}) 勝ち`;
        ids.nextTurn.textContent = "GAME_OVER";
      }
      if (event.type === "match_forfeited") {
        ids.result.textContent = `${event.winner_name || "opponent"} 勝ち`;
        ids.nextTurn.textContent = "GAME_OVER";
      }
      ids.eventCount.textContent = String(state.eventCount);
      appendLog(event);
    }

    renderBoard(".......");
    const source = new EventSource("/events");
    source.onopen = () => setConnection("接続済み", true);
    source.onerror = () => setConnection("再接続中", false);
    ["server_started", "client_ready", "match_started", "opening_move", "pie_selected", "move_played", "match_finished", "match_forfeited"].forEach((name) => {
      source.addEventListener(name, (message) => applyEvent(JSON.parse(message.data)));
    });
  </script>
</body>
</html>
"""
