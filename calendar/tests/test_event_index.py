#!/usr/bin/env python3
"""cal-myhanno の EventIndex のユニットテスト。list_all_events を差し替えるので
ネットワーク非依存。
実行: python3 calendar/tests/test_event_index.py
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_myhanno",
                                              os.path.join(BIN, "cal-myhanno"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


class FakeList:
    """calendar_id → events を返す list_all_events のフェイク。呼び出しを記録する。"""

    def __init__(self, by_cal):
        self.by_cal = by_cal
        self.calls = []

    def __call__(self, calendar_id):
        self.calls.append(calendar_id)
        return self.by_cal.get(calendar_id, [])


def _ev(uid, **over):
    e = {"iCalUID": uid, "id": uid.replace("@", "_"), "summary": uid}
    e.update(over)
    return e


def test_get_returns_event_by_uid():
    mod.list_all_events = FakeList({"cal-A": [_ev("a@x"), _ev("b@x")]})
    idx = mod.EventIndex()
    got = idx.get("cal-A", "b@x")
    assert got is not None
    assert got["iCalUID"] == "b@x"


def test_get_returns_none_for_unknown_uid():
    mod.list_all_events = FakeList({"cal-A": [_ev("a@x")]})
    idx = mod.EventIndex()
    assert idx.get("cal-A", "nosuch@x") is None


def test_fetches_each_calendar_only_once():
    fake = FakeList({"cal-A": [_ev("a@x"), _ev("b@x")]})
    mod.list_all_events = fake
    idx = mod.EventIndex()
    idx.get("cal-A", "a@x")
    idx.get("cal-A", "b@x")
    idx.get("cal-A", "nosuch@x")
    assert fake.calls == ["cal-A"]      # 3 回引いても fetch は 1 回


def test_fetches_each_calendar_separately():
    fake = FakeList({"cal-A": [_ev("a@x")], "cal-B": [_ev("b@x")]})
    mod.list_all_events = fake
    idx = mod.EventIndex()
    assert idx.get("cal-A", "a@x") is not None
    assert idx.get("cal-B", "b@x") is not None
    assert idx.get("cal-A", "b@x") is None      # カレンダーをまたがない
    assert sorted(fake.calls) == ["cal-A", "cal-B"]


def test_skips_events_without_ical_uid():
    fake = FakeList({"cal-A": [{"id": "no-uid", "summary": "手動作成"}, _ev("a@x")]})
    mod.list_all_events = fake
    idx = mod.EventIndex()
    assert idx.get("cal-A", "a@x") is not None
    # uid 無しイベントで索引が壊れていないこと (例外が出ないこと自体が検証)


def test_empty_calendar():
    mod.list_all_events = FakeList({})
    idx = mod.EventIndex()
    assert idx.get("cal-empty", "a@x") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all event-index tests passed")
