from __future__ import annotations

import shlex
from dataclasses import dataclass


MAX_LINE_BYTES = 4096


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...]
    fields: dict[str, str]


def parse_command(line: str) -> Command:
    try:
        parts = shlex.split(line, posix=True)
    except ValueError as exc:
        raise ValueError(f"invalid quoting: {exc}") from exc

    if not parts:
        raise ValueError("empty command")

    fields: dict[str, str] = {}
    args: list[str] = []
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            if not key:
                raise ValueError("empty field name")
            fields[key.lower()] = value
        else:
            args.append(part)

    return Command(parts[0].upper(), tuple(args), fields)


def format_message(name: str, *args: object, **fields: object) -> str:
    parts = [name.upper()]
    parts.extend(_quote(str(arg)) for arg in args)
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_quote(str(value))}")
    return " ".join(parts)


def _quote(value: str) -> str:
    if value == "" or any(char.isspace() for char in value) or '"' in value or "\\" in value:
        return shlex.quote(value)
    return value
