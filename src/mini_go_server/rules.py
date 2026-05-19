from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Color(Enum):
    BLACK = 1
    WHITE = -1

    @property
    def opponent(self) -> "Color":
        return Color.BLACK if self is Color.WHITE else Color.WHITE

    @property
    def protocol_name(self) -> str:
        return "BLACK" if self is Color.BLACK else "WHITE"

    @property
    def stone(self) -> str:
        return "X" if self is Color.BLACK else "O"


class GameStatus(Enum):
    ONGOING = "ongoing"
    BLACK_WIN = "black_win"
    WHITE_WIN = "white_win"


@dataclass(frozen=True)
class MoveResult:
    legal: bool
    capture: bool
    board_after: tuple[int, ...]
    reason: str = ""


@dataclass
class GameState:
    size: int
    board: tuple[int, ...]
    turn: Color
    status: GameStatus = GameStatus.ONGOING
    winner: Color | None = None
    win_reason: str | None = None

    @classmethod
    def new(cls, size: int) -> "GameState":
        if size < 3 or size > 99:
            raise ValueError("board size must be between 3 and 99")
        return cls(size=size, board=(0,) * size, turn=Color.BLACK)

    def apply_move(self, index: int) -> MoveResult:
        if self.status is not GameStatus.ONGOING:
            return MoveResult(False, False, self.board, "game is already finished")

        result = evaluate_move(self.board, index, self.turn)
        if not result.legal:
            return result

        mover = self.turn
        self.board = result.board_after
        if result.capture:
            self._finish(mover, "capture")
            return result

        self.turn = self.turn.opponent
        if not has_any_legal_move(self.board, self.turn):
            self._finish(mover, "no_legal_move")
        return result

    def legal_moves(self) -> list[int]:
        return legal_moves(self.board, self.turn)

    def _finish(self, winner: Color, reason: str) -> None:
        self.winner = winner
        self.win_reason = reason
        self.status = GameStatus.BLACK_WIN if winner is Color.BLACK else GameStatus.WHITE_WIN


def parse_color(name: str) -> Color:
    upper = name.upper()
    if upper == "BLACK":
        return Color.BLACK
    if upper == "WHITE":
        return Color.WHITE
    raise ValueError(f"unknown color: {name}")


def board_to_text(board: tuple[int, ...]) -> str:
    chars = []
    for cell in board:
        if cell == Color.BLACK.value:
            chars.append("X")
        elif cell == Color.WHITE.value:
            chars.append("O")
        else:
            chars.append(".")
    return "".join(chars)


def get_group_range(board: tuple[int, ...], index: int) -> tuple[int, int, int] | None:
    color = board[index]
    if color == 0:
        return None

    left = index
    right = index
    while left - 1 >= 0 and board[left - 1] == color:
        left -= 1
    while right + 1 < len(board) and board[right + 1] == color:
        right += 1
    return left, right, color


def count_liberties(board: tuple[int, ...], group: tuple[int, int, int]) -> int:
    left, right, _color = group
    liberties = 0
    if left - 1 >= 0 and board[left - 1] == 0:
        liberties += 1
    if right + 1 < len(board) and board[right + 1] == 0:
        liberties += 1
    return liberties


def is_capture_move(board_after: tuple[int, ...], move_index: int, player: Color) -> bool:
    enemy = player.opponent.value
    for neighbor in (move_index - 1, move_index + 1):
        if neighbor < 0 or neighbor >= len(board_after):
            continue
        if board_after[neighbor] != enemy:
            continue
        enemy_group = get_group_range(board_after, neighbor)
        if enemy_group is not None and count_liberties(board_after, enemy_group) == 0:
            return True
    return False


def evaluate_move(board: tuple[int, ...], move_index: int, player: Color) -> MoveResult:
    if move_index < 0 or move_index >= len(board):
        return MoveResult(False, False, board, "out_of_range")
    if board[move_index] != 0:
        return MoveResult(False, False, board, "occupied")

    next_board = list(board)
    next_board[move_index] = player.value
    board_after = tuple(next_board)

    capture = is_capture_move(board_after, move_index, player)
    if not capture:
        my_group = get_group_range(board_after, move_index)
        if my_group is None or count_liberties(board_after, my_group) == 0:
            return MoveResult(False, False, board, "suicide")

    return MoveResult(True, capture, board_after)


def has_any_legal_move(board: tuple[int, ...], player: Color) -> bool:
    return any(evaluate_move(board, index, player).legal for index, cell in enumerate(board) if cell == 0)


def legal_moves(board: tuple[int, ...], player: Color) -> list[int]:
    return [index for index, cell in enumerate(board) if cell == 0 and evaluate_move(board, index, player).legal]
