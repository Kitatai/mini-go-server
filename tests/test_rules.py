from mini_go_server.rules import Color, GameState, evaluate_move, legal_moves


def test_first_move_at_edge_is_suicide_on_size_three() -> None:
    board = (0, 0, 0)
    result = evaluate_move(board, 0, Color.BLACK)
    assert result.legal
    assert not result.capture


def test_occupied_move_is_illegal() -> None:
    board = (Color.BLACK.value, 0, 0)
    result = evaluate_move(board, 0, Color.WHITE)
    assert not result.legal
    assert result.reason == "occupied"


def test_capture_wins_immediately() -> None:
    state = GameState.new(3)
    assert state.apply_move(0).legal
    assert state.apply_move(2).legal
    result = state.apply_move(1)
    assert result.legal
    assert result.capture
    assert state.winner is Color.BLACK
    assert state.win_reason == "capture"


def test_suicide_without_capture_is_illegal() -> None:
    board = (0, Color.WHITE.value, 0, Color.BLACK.value)
    result = evaluate_move(board, 2, Color.BLACK)
    assert not result.legal
    assert result.reason == "suicide"


def test_legal_moves_are_reported() -> None:
    board = (Color.BLACK.value, 0, 0, Color.WHITE.value)
    assert legal_moves(board, Color.BLACK) == [1, 2]
