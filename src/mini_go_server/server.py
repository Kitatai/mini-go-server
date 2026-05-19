from __future__ import annotations

import argparse
import asyncio
import logging

from .connection import Client
from .core import MiniGoServer, ServerConfig
from .events import EventBus
from .web import WebViewer

LOGGER = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Mini-Go TCP match server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=37373)
    parser.add_argument("--board-size", "-n", type=int, default=15)
    parser.add_argument("--move-time", type=float, default=3.0, help="seconds per move")
    parser.add_argument("--handshake-time", type=float, default=5.0, help="seconds for REGISTER")
    parser.add_argument("--pie-time", type=float, default=10.0, help="seconds for TAKE BLACK|WHITE")
    parser.add_argument("--manual-opener-selection", action="store_true", help="pairing 時にサーバー端末で OPEN 側を手動選択する")
    parser.add_argument("--web", action="store_true", help="観戦用 Web サーバーを同時起動する")
    parser.add_argument("--web-host", default="127.0.0.1", help="観戦用 Web サーバーの host")
    parser.add_argument("--web-port", type=int, default=8080, help="観戦用 Web サーバーの port")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true", help="suppress match progress logs")
    return parser


async def choose_opener_interactively(first: Client, second: Client) -> tuple[Client, Client]:
    print("")
    print("OPEN 側を選択してください。")
    print(f"  1: {first.name}  slot={first.slot}")
    print(f"  2: {second.name}  slot={second.slot}")

    while True:
        try:
            answer = await asyncio.to_thread(input, "OPEN にする番号 [1/2]: ")
        except EOFError:
            LOGGER.warning("manual opener selection received EOF; defaulting to %s", first.name)
            return first, second

        normalized = answer.strip()
        if normalized == "1":
            LOGGER.info("manual opener selection: open=%s choose=%s", first.name, second.name)
            return first, second
        if normalized == "2":
            LOGGER.info("manual opener selection: open=%s choose=%s", second.name, first.name)
            return second, first
        print("1 または 2 を入力してください。")


def run_from_args(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    log_level = logging.WARNING if args.quiet else logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s %(message)s")
    config = ServerConfig(
        host=args.host,
        port=args.port,
        board_size=args.board_size,
        move_time=args.move_time,
        handshake_time=args.handshake_time,
        pie_time=args.pie_time,
    )
    opener_selector = choose_opener_interactively if args.manual_opener_selection else None
    events = EventBus()
    server = MiniGoServer(config, events=events, opener_selector=opener_selector)
    try:
        asyncio.run(run_services(server, events, web_enabled=args.web, web_host=args.web_host, web_port=args.web_port))
    except KeyboardInterrupt:
        LOGGER.info("server stopped")


async def run_services(
    server: MiniGoServer,
    events: EventBus,
    *,
    web_enabled: bool,
    web_host: str,
    web_port: int,
) -> None:
    tasks = [asyncio.create_task(server.start())]
    if web_enabled:
        tasks.append(asyncio.create_task(WebViewer(events, host=web_host, port=web_port).start()))
    await asyncio.gather(*tasks)
