from __future__ import annotations

import argparse
import random
import socket
import time

from mini_go_common.protocol import parse_command


def wait_until_deadline(timeout_ms: str | None, margin_ms: int) -> None:
    if timeout_ms is None:
        return
    try:
        timeout_seconds = max(0.0, int(timeout_ms) / 1000)
    except ValueError:
        return
    margin_seconds = max(0.0, margin_ms / 1000)
    time.sleep(max(0.0, timeout_seconds - margin_seconds))


def main() -> None:
    parser = argparse.ArgumentParser(description="Tiny random Mini-Go client for smoke tests.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=37373)
    parser.add_argument("--name", default="random")
    parser.add_argument(
        "--wait-until-deadline",
        action="store_true",
        help="制限時間ぎりぎりまで待ってから MOVE/TAKE を返す",
    )
    parser.add_argument(
        "--deadline-margin-ms",
        type=int,
        default=50,
        help="--wait-until-deadline 時に制限時間から残す余裕ミリ秒",
    )
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
                if args.wait_until_deadline:
                    wait_until_deadline(command.fields.get("timeout_ms"), args.deadline_margin_ms)
                file.write(f"MOVE {move}\n")
                file.flush()
            elif command.name == "REQUEST" and command.args[:1] == ("PIE",):
                if args.wait_until_deadline:
                    wait_until_deadline(command.fields.get("timeout_ms"), args.deadline_margin_ms)
                file.write(f"TAKE {random.choice(['BLACK', 'WHITE'])}\n")
                file.flush()
            elif command.name in {"RESULT", "ERROR"}:
                print(line.strip())
                break
