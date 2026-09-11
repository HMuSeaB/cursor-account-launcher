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


def test_stale_cached_email_does_not_outrank_jwt_user():
    rows = [
        {"id": "user_pro", "email": "pro@x.com"},
        {"id": "user_free", "email": "free@x.com"},
    ]
    out = sort_account_rows(rows, local_user_id="user_free", local_email="pro@x.com")
    assert [r["id"] for r in out] == ["user_free", "user_pro"]


def test_email_match_when_id_missing():
    rows = [{"id": "other", "email": "me@x.com"}, {"id": "x", "email": "z@x.com"}]
    out = sort_account_rows(rows, local_email="me@x.com")
    assert out[0]["email"] == "me@x.com"


def test_error_accounts_sink_to_bottom():
    rows = [
        {"id": "user_err1", "email": "err1@x.com", "err": "登录失效"},
        {"id": "user_ok1", "email": "ok1@x.com"},
        {"id": "user_err2", "email": "err2@x.com", "err": "HTTP 401"},
        {"id": "user_ok2", "email": "ok2@x.com"},
    ]
    out = sort_account_rows(rows)
    # 正常账号在前且保持相对顺序，失效账号在后且保持相对顺序
    assert [r["id"] for r in out] == ["user_ok1", "user_ok2", "user_err1", "user_err2"]


def test_local_account_ranks_first_among_normals_and_error_sinks():
    rows = [
        {"id": "user_err", "email": "err@x.com", "err": "登录失效"},
        {"id": "user_normal", "email": "normal@x.com"},
        {"id": "user_local", "email": "local@x.com"},
    ]
    out = sort_account_rows(rows, local_user_id="user_local")
    # user_local 作为本机正常账号排在第一，正常账号 user_normal 在第二，user_err 沉底在最后
    assert [r["id"] for r in out] == ["user_local", "user_normal", "user_err"]


def test_account_store_reorder_and_sink(tmp_path, monkeypatch):
    store_file = tmp_path / "accounts.json"
    monkeypatch.setattr("launcher.accounts._accounts_path", lambda: str(store_file))
    monkeypatch.setattr("launcher.account_store._accounts_path", lambda: str(store_file))
    from launcher.account_store import AccountStore

    store = AccountStore()
    store._items = {
        "id1": {"id": "id1", "label": "1@x.com", "token": "t1", "err": "失效"},
        "id2": {"id": "id2", "label": "2@x.com", "token": "t2"},
        "id3": {"id": "id3", "label": "3@x.com", "token": "t3"},
    }
    store.reorder(["id3", "id2", "id1"])
    assert list(store._items.keys()) == ["id3", "id2", "id1"]

    store.reorder(["id1", "id3", "id2"])
    assert list(store._items.keys()) == ["id1", "id3", "id2"]
    store.sink_errors()
    assert list(store._items.keys()) == ["id3", "id2", "id1"]




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
