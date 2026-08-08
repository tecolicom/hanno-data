#!/usr/bin/env python3
"""cal-myhanno の events.list ページングのユニットテスト。gws を差し替えるので
ネットワーク非依存。
実行: python3 calendar/tests/test_calendar_paging.py
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


class FakeGws:
    """pages: [(items, next_token)] を順に返す gws のフェイク。"""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []          # 各呼び出しの params を記録

    def __call__(self, *args, params=None, body=None):
        self.calls.append(dict(params or {}))
        items, token = self.pages[len(self.calls) - 1]
        res = {"items": items}
        if token:
            res["nextPageToken"] = token
        return res


def _ev(uid):
    return {"iCalUID": uid, "id": uid.replace("@", "_")}


def test_single_page():
    fake = FakeGws([([_ev("a@x"), _ev("b@x")], None)])
    mod.gws = fake
    got = mod.list_all_events("cal-1")
    assert [e["iCalUID"] for e in got] == ["a@x", "b@x"]
    assert len(fake.calls) == 1
    assert "pageToken" not in fake.calls[0]


def test_empty():
    fake = FakeGws([([], None)])
    mod.gws = fake
    assert mod.list_all_events("cal-1") == []


def test_follows_next_page_token():
    fake = FakeGws([
        ([_ev("a@x")], "TOK1"),
        ([_ev("b@x")], "TOK2"),
        ([_ev("c@x")], None),
    ])
    mod.gws = fake
    got = mod.list_all_events("cal-1")
    assert [e["iCalUID"] for e in got] == ["a@x", "b@x", "c@x"]
    assert len(fake.calls) == 3
    assert "pageToken" not in fake.calls[0]
    assert fake.calls[1]["pageToken"] == "TOK1"
    assert fake.calls[2]["pageToken"] == "TOK2"


def test_does_not_truncate_beyond_500():
    """現行バグの回帰テスト: maxResults:500 固定 + ページング未処理で
    501 件目以降を静かに切り捨てていた。"""
    page1 = [_ev(f"e{i}@x") for i in range(500)]
    page2 = [_ev(f"e{i}@x") for i in range(500, 620)]
    fake = FakeGws([(page1, "TOK1"), (page2, None)])
    mod.gws = fake
    got = mod.list_all_events("cal-1")
    assert len(got) == 620
    assert got[-1]["iCalUID"] == "e619@x"


def test_request_params():
    fake = FakeGws([([], None)])
    mod.gws = fake
    mod.list_all_events("cal-42")
    p = fake.calls[0]
    assert p["calendarId"] == "cal-42"
    assert p["maxResults"] == 2500      # Calendar API の上限
    assert p["singleEvents"] is False
    assert p["showDeleted"] is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all calendar-paging tests passed")
