from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .connection import Client, ClientDisconnected, ClientTimeout, ProtocolViolation
from .events import EventBus
from .rules import Color, GameState, board_to_text, parse_color

LOGGER = logging.getLogger(__name__)

OpenerSelector = Callable[[Client, Client], Awaitable[tuple[Client, Client]]]


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 37373
    board_size: int = 15
    move_time: float = 3.0
    handshake_time: float = 5.0
    pie_time: float = 10.0


@dataclass(frozen=True)
class MatchPhase:
    name: str
    actor: Client


class MiniGoServer:
    def __init__(
        self,
        config: ServerConfig,
        *,
        events: EventBus | None = None,
        opener_selector: OpenerSelector | None = None,
    ) -> None:
        self.config = config
        self.events = events or EventBus()
        self.opener_selector = opener_selector or default_opener_selector
        self.waiting: asyncio.Queue[Client] = asyncio.Queue()
        self.pairing_lock = asyncio.Lock()
        self.next_slot = 1

    async def start(self) -> None:
        server = await asyncio.start_server(self.handle_connection, self.config.host, self.config.port)
        sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
        LOGGER.info("listening on %s", sockets)
        self.events.publish("server_started", sockets=sockets, host=self.config.host, port=self.config.port)
        async with server:
            await server.serve_forever()

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = Client(reader, writer, self.next_slot)
        self.next_slot += 1
        peer = writer.get_extra_info("peername")
        LOGGER.info("client connected: %s", peer)
        try:
            await self.handshake(client)
            self.events.publish("client_ready", name=client.name, slot=client.slot, peer=str(peer))
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
                opener, chooser = await self.opener_selector(first, second)
                asyncio.create_task(self.run_match(opener, chooser))

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
            self.events.publish(
                "match_started",
                match_id=match_id,
                opener=opener.name,
                chooser=chooser.name,
                board_size=state.size,
                move_time=self.config.move_time,
                pie_time=self.config.pie_time,
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
            self.events.publish(
                "opening_move",
                match_id=match_id,
                player=opener.name,
                color=Color.BLACK.protocol_name,
                move=opening_move,
                board=board_to_text(state.board),
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
            self.events.publish(
                "pie_selected",
                match_id=match_id,
                chooser=chooser.name,
                takes=chooser_takes.protocol_name,
                black=players[Color.BLACK].name,
                white=players[Color.WHITE].name,
                board=board_to_text(state.board),
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
                next_turn = state.turn.protocol_name if state.winner is None else "GAME_OVER"
                LOGGER.info(
                    "match %s move %s: %s(%s) plays %s capture=%s board=%s next=%s",
                    match_id,
                    move_number,
                    current.name,
                    color.protocol_name,
                    move,
                    result.capture,
                    board_to_text(state.board),
                    next_turn,
                )
                self.events.publish(
                    "move_played",
                    match_id=match_id,
                    move_number=move_number,
                    player=current.name,
                    color=color.protocol_name,
                    move=move,
                    capture=result.capture,
                    board=board_to_text(state.board),
                    next_turn=next_turn,
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
        board = board_to_text(state.board)
        LOGGER.info(
            "match %s result: winner=%s(%s) loser=%s(%s) reason=%s board=%s",
            match_id,
            winner_client.name,
            state.winner.protocol_name,
            loser_client.name,
            loser_color.protocol_name,
            state.win_reason,
            board,
        )
        self.events.publish(
            "match_finished",
            match_id=match_id,
            winner=state.winner.protocol_name,
            winner_name=winner_client.name,
            loser=loser_color.protocol_name,
            loser_name=loser_client.name,
            reason=state.win_reason,
            board=board,
        )
        await self.broadcast(
            clients,
            "RESULT",
            winner=state.winner.protocol_name,
            winner_name=winner_client.name,
            loser=loser_color.protocol_name,
            loser_name=loser_client.name,
            reason=state.win_reason,
            board=board,
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
        self.events.publish(
            "match_forfeited",
            match_id=match_id,
            winner_name=winner.name if winner else "",
            loser_name=loser.name,
            reason=reason,
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


async def default_opener_selector(first: Client, second: Client) -> tuple[Client, Client]:
    return first, second
