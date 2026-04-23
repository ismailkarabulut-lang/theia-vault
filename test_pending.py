"""core/pending.py birim testleri."""

import pytest


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Her test için izole geçici bir SQLite DB kullanır."""
    import core.config as cfg
    import core.db as db_mod
    import core.pending as pending_mod

    test_db = tmp_path / "test.db"
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    monkeypatch.setattr(db_mod, "DB_PATH", test_db)
    pending_mod.init_pending_table()


from core.pending import add_pending, get_all_open_pendings, get_open_pendings, resolve_pending


def test_add_pending_returns_id():
    action_id = add_pending(user_id=1, text="Raporu yaz")
    assert isinstance(action_id, int)
    assert action_id >= 1


def test_get_open_pendings_returns_added():
    add_pending(user_id=1, text="Toplantıyı planla")
    rows = get_open_pendings(user_id=1)
    assert len(rows) == 1
    assert rows[0]["text"] == "Toplantıyı planla"
    assert rows[0]["user_id"] == 1


def test_resolve_pending_removes_from_open():
    action_id = add_pending(user_id=1, text="Kodu incele")
    resolve_pending(action_id)
    rows = get_open_pendings(user_id=1)
    assert len(rows) == 0


def test_get_open_pendings_isolates_by_user():
    add_pending(user_id=1, text="Kullanıcı 1 görevi")
    add_pending(user_id=2, text="Kullanıcı 2 görevi")
    assert len(get_open_pendings(user_id=1)) == 1
    assert len(get_open_pendings(user_id=2)) == 1


def test_get_all_open_pendings():
    add_pending(user_id=1, text="A")
    add_pending(user_id=2, text="B")
    add_pending(user_id=1, text="C")
    rows = get_all_open_pendings()
    assert len(rows) == 3


def test_resolve_pending_sets_resolved_at():
    from core.db import db
    action_id = add_pending(user_id=1, text="Test")
    resolve_pending(action_id)
    with db() as c:
        row = c.execute(
            "SELECT resolved_at FROM pending_actions WHERE id = ?", (action_id,)
        ).fetchone()
    assert row["resolved_at"] is not None


# ── Niyet tespiti testleri ────────────────────────────────────────────────────

def test_intent_regex_matches_and_add_pending_called(monkeypatch):
    from handlers import message as msg_mod

    calls = []
    monkeypatch.setattr(msg_mod, "add_pending", lambda uid, txt: calls.append((uid, txt)) or 1)

    assert msg_mod._INTENT_RE.search("buna yarın bakacağım")
    msg_mod.add_pending(42, "buna yarın bakacağım")
    assert len(calls) == 1
    assert calls[0] == (42, "buna yarın bakacağım")


def test_no_intent_add_pending_not_called(monkeypatch):
    from handlers import message as msg_mod

    calls = []
    monkeypatch.setattr(msg_mod, "add_pending", lambda uid, txt: calls.append((uid, txt)) or 1)

    assert not msg_mod._INTENT_RE.search("bugün hava nasıl?")
    assert len(calls) == 0
