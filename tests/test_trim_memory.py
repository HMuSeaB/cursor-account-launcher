"""tasklist parse and working-set trim helpers."""

import os
import sys
from pathlib import Path

from launcher.cursor_process import (
    _empty_working_set,
    _win_pids_named,
    _working_set_kb,
    is_cursor_running,
    list_cursor_processes,
    parse_tasklist_csv,
)
from launcher.hidden_proc import CREATE_NO_WINDOW, _win_kwargs


def test_parse_tasklist_csv_handles_comma_memory():
    raw = '"Cursor.exe","28456","Console","1","2,145,320 K"\r\n"notepad.exe","1","Console","1","12 K"\r\n'
    rows = parse_tasklist_csv(raw)
    assert len(rows) == 1
    assert rows[0]["pid"] == 28456
    assert rows[0]["wsKb"] == 2145320
    assert rows[0]["wsMb"] == round(2145320 / 1024, 1)


def test_parse_tasklist_ignores_info_line():
    assert parse_tasklist_csv("INFO: No tasks are running which match the specified criteria.") == []


def test_empty_working_set_on_self():
    assert _empty_working_set(os.getpid()) is True


def test_hidden_run_sets_no_window_flag():
    kw = _win_kwargs({})
    assert kw["creationflags"] & CREATE_NO_WINDOW
    assert kw["startupinfo"].dwFlags & 1
    assert kw["startupinfo"].wShowWindow == 0


def test_list_cursor_processes_returns_list():
    rows = list_cursor_processes()
    assert isinstance(rows, list)
    assert isinstance(is_cursor_running(), bool)
    for row in rows:
        assert row["name"].lower() == "cursor.exe"
        assert row["pid"] > 0


def test_win_pid_enum_finds_self():
    if sys.platform != "win32":
        return
    name = Path(sys.executable).name
    pids = _win_pids_named(name)
    assert os.getpid() in pids
    assert _working_set_kb(os.getpid()) > 0
