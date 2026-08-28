"""Account sort and window geometry helpers."""

from launcher.account_store import sort_account_rows
from launcher.window_state import DEFAULT_HEIGHT, DEFAULT_WIDTH, MIN_HEIGHT, MIN_WIDTH, geom_visible, parse_window_geom


def test_local_account_sorts_first():
    rows = [
        {"id": "user_b", "email": "b@x.com"},
        {"id": "user_a", "email": "a@x.com"},
        {"id": "user_c", "email": "c@x.com"},
    ]
    out = sort_account_rows(rows, local_user_id="user_c", local_email="c@x.com")
    assert [r["id"] for r in out] == ["user_c", "user_b", "user_a"]


def test_last_switched_sorts_after_local():
    rows = [
        {"id": "user_b", "email": "b@x.com"},
        {"id": "user_a", "email": "a@x.com"},
        {"id": "user_c", "email": "c@x.com"},
    ]
    out = sort_account_rows(rows, local_user_id="user_a", last_id="user_c")
    assert [r["id"] for r in out] == ["user_a", "user_c", "user_b"]


def test_email_match_when_id_missing():
    rows = [{"id": "other", "email": "me@x.com"}, {"id": "x", "email": "z@x.com"}]
    out = sort_account_rows(rows, local_email="me@x.com")
    assert out[0]["email"] == "me@x.com"


def test_parse_window_geom_defaults_and_min_size():
    geom = parse_window_geom({})
    assert geom["width"] == DEFAULT_WIDTH
    assert geom["height"] == DEFAULT_HEIGHT
    assert geom["x"] is None
    assert geom["y"] is None
    assert geom["maximized"] is False
    small = parse_window_geom({"windowWidth": 100, "windowHeight": 50})
    assert small["width"] == MIN_WIDTH
    assert small["height"] == MIN_HEIGHT


def test_parse_window_geom_drops_offscreen_position():
    screen = (0, 0, 1920, 1080)
    geom = parse_window_geom(
        {"windowWidth": 1000, "windowHeight": 700, "windowX": 8000, "windowY": 20},
        screen,
    )
    assert geom["x"] is None
    assert geom["y"] is None
    assert geom_visible(100, 100, 1000, 700, screen) is True
    assert geom_visible(9000, 0, 1000, 700, screen) is False
