"""账号绑定的机器码：列表只给短码，详情才给全量。"""

from __future__ import annotations

import base64
import json

from launcher.account_store import AccountStore, canonical_machine_id, short_machine_id
from launcher.local_cursor import peek_local_machine_short


def _b64url(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def fake_jwt(sub: str) -> str:
    return f"{_b64url({'alg': 'HS256', 'typ': 'JWT'})}.{_b64url({'sub': sub})}.fakesigxxxxxx"


def test_short_id_strips_hyphens_and_braces():
    ids = {
        "serviceMachineId": "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}",
        "telemetryMachineId": "fc960e133f5dab" + "ab" * 25,
    }
    assert canonical_machine_id(ids).startswith("{AAAAAAAA")
    assert short_machine_id(ids) == "AAAAAAAABBBB"


def test_canonical_prefers_service_over_telemetry():
    ids = {
        "telemetryMachineId": "fc960e133f5d" + "ab" * 26,
        "serviceMachineId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    }
    assert canonical_machine_id(ids) == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert short_machine_id(ids) == "aaaaaaaabbbb"


def test_empty_ids():
    assert canonical_machine_id({}) == ""
    assert short_machine_id(None) == ""
    assert short_machine_id({"macMachineId": "only-mac"}) == ""


def test_list_exposes_short_id_not_full_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr("launcher.accounts._app_dir", lambda: str(tmp_path))
    uid = "user_abc123device"
    jwt = fake_jwt(f"auth0|{uid}")
    store = AccountStore()
    added = store.add_text(f"{uid}::{jwt}")
    assert added and added[0]["id"] == uid

    store.set_device_ids(
        uid,
        {
            "machineId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "serviceMachineId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "telemetryMachineId": "fc960e133f5d" + "ab" * 26,
        },
    )
    row = store.list()[0]
    assert row["hasDeviceIds"] is True
    assert row["machineIdShort"] == "aaaaaaaabbbb"
    assert "deviceIds" not in row

    detail = store.get_detail(uid)
    assert detail["deviceIds"]["serviceMachineId"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert detail["machineIdShort"] == "aaaaaaaabbbb"


def test_peek_local_machine_short_reads_file_only(tmp_path, monkeypatch):
    machine = tmp_path / "machineid"
    machine.write_text("{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}", encoding="utf-8")
    monkeypatch.setattr("launcher.local_cursor.machineid_path", lambda: str(machine))
    assert peek_local_machine_short() == "aaaaaaaabbbb"


def test_settings_html_is_an_overlay_sheet():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    assert 'class="card settings-fold"' in html
    assert 'class="settings-sheet"' in html
    assert html.count("<details") == html.count("</details>")
    assert 'id="btnRotateMachine"' not in html  # 按钮由详情 JS 注入，避免列表页常驻
    css = (Path(__file__).resolve().parents[1] / "web" / "style.css").read_text(encoding="utf-8")
    open_sheet = css.split(".settings-fold[open] .settings-sheet")[1].split("}")[0]
    assert "position: absolute" in open_sheet
    assert "min-height: 0" in open_sheet
    assert "overflow-y: auto" in open_sheet
    js = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "layoutSettingsSheet" in js
    assert "sheet.style.top" in js
