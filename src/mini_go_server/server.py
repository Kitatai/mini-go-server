from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field

from mini_go_common.protocol import MAX_LINE_BYTES, Command, format_message, parse_command
from .rules import Color, GameState, board_to_text, parse_color

LOGGER = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 37373
    board_size: int = 15
    move_time: float = 3.0
    handshake_time: float = 5.0
    pie_time: float = 10.0
    manual_opener_selection: bool = False


@dataclass
class Client:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    slot: int
    name: str = field(default="")
    protocol: str = field(default="")
    last_score: str | None = None
    last_comment: str | None = None

    async def send(self, name: str, *args: object, **fields: object) -> None:
        line = format_message(name, *args, **fields)
        self.writer.write((line + "\n").encode("utf-8"))
        await self.writer.drain()

    async def read_command(self, timeout: float) -> Command:
        try:
            data = await asyncio.wait_for(self.reader.readline(), timeout=timeout)
        except TimeoutError as exc:
            raise ClientTimeout from exc
        if data == b"":
            raise ClientDisconnected
        if len(data) > MAX_LINE_BYTES:
            raise ProtocolViolation("line_too_long")
        try:
            line = data.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ProtocolViolation("invalid_utf8") from exc
        try:
            return parse_command(line)
        except ValueError as exc:
            raise ProtocolViolation(str(exc)) from exc

    def close(self) -> None:
        self.writer.close()


class ClientTimeout(Exception):
    pass


class ClientDisconnected(Exception):
    pass


class ProtocolViolation(Exception):
    pass


@dataclass(frozen=True)
class MatchPhase:
    name: str
    actor: Client


class MiniGoServer:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.waiting: asyncio.Queue[Client] = asyncio.Queue()
        self.pairing_lock = asyncio.Lock()
        self.next_slot = 1

    async def start(self) -> None:
        server = await asyncio.start_server(self.handle_connection, self.config.host, self.config.port)
        sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
        LOGGER.info("listening on %s", sockets)
        async with server:
            await server.serve_forever()

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = Client(reader, writer, self.next_slot)
        self.next_slot += 1
        peer = writer.get_extra_info("peername")
        LOGGER.info("client connected: %s", peer)
        try:
            await self.handshake(client)
            await client.send("READY")
            await self.waiting.put(client)
            await self.start_available_matches()
        except Exception as exc:
            LOGGER.info("connection setup failed: %s", exc)
            with contextlib.suppress(Exception):
                await client.send("ERROR", reason=str(exc))
            client.close()

    async def start_available_matches(self) -> None:
        async with self.pairing_lock:
            while self.waiting.qsize() >= 2:
                first = await self.waiting.get()
                second = await self.waiting.get()
                opener, chooser = await self.choose_opener(first, second)
                asyncio.create_task(self.run_match(opener, chooser))

    async def choose_opener(self, first: Client, second: Client) -> tuple[Client, Client]:
        if not self.config.manual_opener_selection:
            return first, second

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

    async def handshake(self, client: Client) -> None:
        await client.send(
            "HELLO",
            "MINIGO",
            version="1",
            board_size=self.config.board_size,
            move_time_ms=int(self.config.move_time * 1000),
            pie_time_ms=int(self.config.pie_time * 1000),
        )
        command = await client.read_command(self.config.handshake_time)
        if command.name != "REGISTER":
            raise ProtocolViolation("expected REGISTER")
        client.name = command.fields.get("name", f"client-{client.slot}")
        client.protocol = command.fields.get("protocol", "1")

    async def run_match(self, opener: Client, chooser: Client) -> None:
        state = GameState.new(self.config.board_size)
        players: dict[Color, Client] = {}
        clients = [opener, chooser]
        phase = MatchPhase("setup", opener)
        try:
            match_id = int(time.time() * 1000)
            LOGGER.info(
                "match %s start: open=%s choose=%s N=%s move_time=%.3fs pie_time=%.3fs",
                match_id,
                opener.name,
                chooser.name,
                state.size,
                self.config.move_time,
                self.config.pie_time,
            )
            await opener.send("MATCH", id=match_id, you="OPEN", opponent=chooser.name, board_size=state.size)
            await chooser.send("MATCH", id=match_id, you="CHOOSE", opponent=opener.name, board_size=state.size)
            await opener.send("ROLE", "OPEN")
            await chooser.send("ROLE", "CHOOSE")

            phase = MatchPhase("pie_open", opener)
            opening_move = await self.request_move(opener, state, phase="PIE_OPEN")
            result = state.apply_move(opening_move)
            if not result.legal:
                await self.forfeit(clients, loser=opener, reason=f"illegal_opening:{result.reason}", match_id=match_id)
                return
            LOGGER.info(
                "match %s opening: %s plays BLACK %s board=%s",
                match_id,
                opener.name,
                opening_move,
                board_to_text(state.board),
            )
            await self.broadcast_state(clients, state, last_move=opening_move, phase="PIE_CHOOSE")

            phase = MatchPhase("pie_choose", chooser)
            chooser_takes = await self.request_pie_choice(chooser)
            if chooser_takes is Color.BLACK:
                players[Color.BLACK] = chooser
                players[Color.WHITE] = opener
            else:
                players[Color.BLACK] = opener
                players[Color.WHITE] = chooser
            await players[Color.BLACK].send("COLOR", "BLACK")
            await players[Color.WHITE].send("COLOR", "WHITE")
            await self.broadcast(clients, "PIE", black=players[Color.BLACK].name, white=players[Color.WHITE].name)
            LOGGER.info(
                "match %s pie: %s takes %s; BLACK=%s WHITE=%s",
                match_id,
                chooser.name,
                chooser_takes.protocol_name,
                players[Color.BLACK].name,
                players[Color.WHITE].name,
            )

            if state.status is not state.status.ONGOING:
                await self.finish_by_state(clients, state, players, match_id=match_id)
                return

            move_number = 2
            while state.winner is None:
                color = state.turn
                current = players[color]
                phase = MatchPhase("play", current)
                move = await self.request_move(current, state, phase="PLAY")
                result = state.apply_move(move)
                if not result.legal:
                    await self.forfeit(clients, loser=current, reason=f"illegal_move:{result.reason}", match_id=match_id)
                    return
                LOGGER.info(
                    "match %s move %s: %s(%s) plays %s capture=%s board=%s next=%s",
                    match_id,
                    move_number,
                    current.name,
                    color.protocol_name,
                    move,
                    result.capture,
                    board_to_text(state.board),
                    state.turn.protocol_name if state.winner is None else "GAME_OVER",
                )
                await self.broadcast_state(clients, state, last_move=move, phase="PLAY")
                move_number += 1
            await self.finish_by_state(clients, state, players, match_id=match_id)
        except ClientTimeout:
            await self.forfeit(clients, loser=phase.actor, reason=f"timeout:{phase.name}", match_id=locals().get("match_id"))
        except ClientDisconnected:
            await self.forfeit(clients, loser=phase.actor, reason=f"disconnect:{phase.name}", match_id=locals().get("match_id"))
        except ProtocolViolation as exc:
            await self.forfeit(
                clients,
                loser=phase.actor,
                reason=f"protocol:{phase.name}:{exc}",
                match_id=locals().get("match_id"),
            )
        finally:
            for client in clients:
                client.close()

    async def request_move(self, client: Client, state: GameState, phase: str) -> int:
        deadline = time.monotonic() + self.config.move_time
        await client.send(
            "REQUEST",
            "MOVE",
            phase=phase,
            color=state.turn.protocol_name,
            board=board_to_text(state.board),
            legal=",".join(str(move) for move in state.legal_moves()),
            timeout_ms=int(self.config.move_time * 1000),
        )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ClientTimeout
            command = await client.read_command(remaining)
            if command.name == "INFO":
                client.last_score = command.fields.get("score", client.last_score)
                client.last_comment = command.fields.get("comment", client.last_comment)
                continue
            if command.name != "MOVE" or len(command.args) != 1:
                raise ProtocolViolation("expected MOVE <index>")
            try:
                return int(command.args[0])
            except ValueError as exc:
                raise ProtocolViolation("move_index_not_integer") from exc

    async def request_pie_choice(self, chooser: Client) -> Color:
        await chooser.send("REQUEST", "PIE", choices="BLACK,WHITE", timeout_ms=int(self.config.pie_time * 1000))
        command = await chooser.read_command(self.config.pie_time)
        if command.name != "TAKE" or len(command.args) != 1:
            raise ProtocolViolation("expected TAKE BLACK|WHITE")
        try:
            return parse_color(command.args[0])
        except ValueError as exc:
            raise ProtocolViolation("unknown_pie_color") from exc

    async def broadcast_state(self, clients: list[Client], state: GameState, last_move: int, phase: str) -> None:
        await self.broadcast(
            clients,
            "STATE",
            phase=phase,
            board=board_to_text(state.board),
            turn=state.turn.protocol_name,
            last_move=last_move,
            status=state.status.value,
        )

    async def finish_by_state(
        self,
        clients: list[Client],
        state: GameState,
        players: dict[Color, Client],
        match_id: int | None,
    ) -> None:
        assert state.winner is not None
        winner_client = players[state.winner]
        loser_color = state.winner.opponent
        loser_client = players[loser_color]
        LOGGER.info(
            "match %s result: winner=%s(%s) loser=%s(%s) reason=%s board=%s",
            match_id,
            winner_client.name,
            state.winner.protocol_name,
            loser_client.name,
            loser_color.protocol_name,
            state.win_reason,
            board_to_text(state.board),
        )
        await self.broadcast(
            clients,
            "RESULT",
            winner=state.winner.protocol_name,
            winner_name=winner_client.name,
            loser=loser_color.protocol_name,
            loser_name=loser_client.name,
            reason=state.win_reason,
            board=board_to_text(state.board),
        )

    async def forfeit(self, clients: list[Client], loser: Client, reason: str, match_id: int | None) -> None:
        winner = next((client for client in clients if client is not loser), None)
        LOGGER.info(
            "match %s forfeit: winner=%s loser=%s reason=%s",
            match_id,
            winner.name if winner else "",
            loser.name,
            reason,
        )
        await self.broadcast(
            clients,
            "RESULT",
            winner_name=winner.name if winner else "",
            loser_name=loser.name,
            reason=reason,
        )

    async def broadcast(self, clients: list[Client], name: str, *args: object, **fields: object) -> None:
        for client in clients:
            await client.send(name, *args, **fields)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Mini-Go TCP match server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=37373)
    parser.add_argument("--board-size", "-n", type=int, default=15)
    parser.add_argument("--move-time", type=float, default=3.0, help="seconds per move")
    parser.add_argument("--handshake-time", type=float, default=5.0, help="seconds for REGISTER")
    parser.add_argument("--pie-time", type=float, default=10.0, help="seconds for TAKE BLACK|WHITE")
    parser.add_argument(
        "--manual-opener-selection",
        action="store_true",
        help="pairing 時にサーバー端末で OPEN 側を手動選択する",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true", help="suppress match progress logs")
    return parser


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
        manual_opener_selection=args.manual_opener_selection,
    )
    try:
        asyncio.run(MiniGoServer(config).start())
    except KeyboardInterrupt:
        LOGGER.info("server stopped")
