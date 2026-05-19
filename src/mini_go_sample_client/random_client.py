from __future__ import annotations

import argparse
import random
import socket

from mini_go_common.protocol import parse_command


def main() -> None:
    parser = argparse.ArgumentParser(description="Tiny random Mini-Go client for smoke tests.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=37373)
    parser.add_argument("--name", default="random")
    args = parser.parse_args()

    with socket.create_connection((args.host, args.port)) as sock:
        file = sock.makefile("rw", encoding="utf-8", newline="\n")
        for line in file:
            command = parse_command(line.strip())
            if command.name == "HELLO":
                file.write(f'REGISTER name="{args.name}" protocol=1\n')
                file.flush()
            elif command.name == "REQUEST" and command.args[:1] == ("MOVE",):
                legal = [int(value) for value in command.fields.get("legal", "").split(",") if value]
                move = random.choice(legal)
                file.write(f"MOVE {move}\n")
                file.flush()
            elif command.name == "REQUEST" and command.args[:1] == ("PIE",):
                file.write(f"TAKE {random.choice(['BLACK', 'WHITE'])}\n")
                file.flush()
            elif command.name in {"RESULT", "ERROR"}:
                print(line.strip())
                break
