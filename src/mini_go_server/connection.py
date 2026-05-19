from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from mini_go_common.protocol import MAX_LINE_BYTES, Command, format_message, parse_command


class ClientTimeout(Exception):
    pass


class ClientDisconnected(Exception):
    pass


class ProtocolViolation(Exception):
    pass


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
