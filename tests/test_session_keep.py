"""session_keep 防误踢回归。"""

from launcher.session_keep import merge_keep_ids, pick_auto_keep_sessions, sessions_to_revoke


def _sess(sid, typ, created="2026-08-01T00:00:00.000Z", current=False):
    return {
        "id": sid,
        "sessionType": typ,
        "typeLabel": typ,
        "createdAt": created,
        "isCurrent": current,
        "raw": {},
    }


def test_auto_keep_protects_all_desktops():
    sessions = [
        _sess("w1", "SESSION_TYPE_WEB", "2026-08-01"),
        _sess("w2", "SESSION_TYPE_WEB", "2026-08-10"),
        _sess("d1", "SESSION_TYPE_CLIENT", "2026-08-05"),
        _sess("d2", "SESSION_TYPE_CLIENT", "2026-08-06"),
    ]
    picked = pick_auto_keep_sessions(sessions, "eyJhbGciOiJIUzI1NiJ9.e30.sig")
    assert "d1" in picked["keepIds"]
    assert "d2" in picked["keepIds"]
    assert "w2" in picked["keepIds"]


def test_batch_revoke_never_targets_desktop():
    sessions = [
        _sess("w1", "SESSION_TYPE_WEB", "2026-08-01"),
        _sess("w2", "SESSION_TYPE_WEB", "2026-08-10"),
        _sess("d1", "SESSION_TYPE_CLIENT", "2026-08-05"),
    ]
    keep = merge_keep_ids(sessions, "eyJ.e30.sig", ["w2"])
    targets = sessions_to_revoke(sessions, keep)
    assert all(t["sessionType"] != "SESSION_TYPE_CLIENT" for t in targets)
    assert "d1" not in {t["id"] for t in targets}
    assert "w1" in {t["id"] for t in targets}
