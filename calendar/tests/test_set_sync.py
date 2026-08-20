#!/usr/bin/env python3
"""_lib.plan_set_sync の削除ガードのユニットテスト。
実行: python3 calendar/tests/test_set_sync.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "_lib.py")
loader = importlib.machinery.SourceFileLoader("_lib", SCRIPT)
spec = importlib.util.spec_from_loader("_lib", loader)
lib = importlib.util.module_from_spec(spec)
loader.exec_module(lib)

TODAY = "2026-06-01"


def test_new_events_are_written():
    got = lib.plan_set_sync(
        existing={},
        incoming={"chef-20260610-01@x": "h1"},
        dates={"chef-20260610-01@x": "2026-06-10"},
        today=TODAY)
    assert got["write"] == ["chef-20260610-01@x"], got
    assert got["delete"] == [], got


def test_unchanged_events_are_not_rewritten():
    got = lib.plan_set_sync(
        existing={"chef-20260610-01@x": "h1"},
        incoming={"chef-20260610-01@x": "h1"},
        dates={"chef-20260610-01@x": "2026-06-10"},
        today=TODAY)
    assert got["write"] == [], got
    assert got["unchanged"] == ["chef-20260610-01@x"], got


def test_changed_events_are_rewritten():
    got = lib.plan_set_sync(
        existing={"chef-20260610-01@x": "old"},
        incoming={"chef-20260610-01@x": "new"},
        dates={"chef-20260610-01@x": "2026-06-10"},
        today=TODAY)
    assert got["write"] == ["chef-20260610-01@x"], got


def test_future_event_gone_from_source_is_deleted():
    # 取得範囲 2026-06-05 〜 2026-06-20 の内側、かつ未来
    got = lib.plan_set_sync(
        existing={"chef-20260610-01@x": "h1", "chef-20260605-01@x": "h2"},
        incoming={"chef-20260605-01@x": "h2", "chef-20260620-01@x": "h3"},
        dates={"chef-20260610-01@x": "2026-06-10",
               "chef-20260605-01@x": "2026-06-05",
               "chef-20260620-01@x": "2026-06-20"},
        today=TODAY)
    assert got["delete"] == ["chef-20260610-01@x"], got


def test_past_event_is_never_deleted():
    # 取得範囲の内側だが today より前 → 記録として残す
    got = lib.plan_set_sync(
        existing={"chef-20260510-01@x": "h1"},
        incoming={"chef-20260501-01@x": "h2", "chef-20260620-01@x": "h3"},
        dates={"chef-20260510-01@x": "2026-05-10",
               "chef-20260501-01@x": "2026-05-01",
               "chef-20260620-01@x": "2026-06-20"},
        today=TODAY)
    assert got["delete"] == [], got


def test_event_outside_fetched_range_is_never_deleted():
    # 未来だが取得範囲の外 → ローリングウィンドウが縮んだだけかもしれない
    got = lib.plan_set_sync(
        existing={"chef-20261225-01@x": "h1"},
        incoming={"chef-20260605-01@x": "h2", "chef-20260620-01@x": "h3"},
        dates={"chef-20261225-01@x": "2026-12-25",
               "chef-20260605-01@x": "2026-06-05",
               "chef-20260620-01@x": "2026-06-20"},
        today=TODAY)
    assert got["delete"] == [], got


def test_empty_incoming_deletes_nothing():
    # パース失敗で 0 件になっても既存を消さない (日付範囲が定義できない)
    got = lib.plan_set_sync(
        existing={"chef-20260610-01@x": "h1"},
        incoming={},
        dates={"chef-20260610-01@x": "2026-06-10"},
        today=TODAY)
    assert got["delete"] == [], got
    assert got["write"] == [], got


def test_too_many_deletions_raises():
    # 削除候補 (06-10〜06-19) を incoming の範囲 (06-05〜06-20) が挟んでいる
    existing = {f"chef-2026061{i}-01@x": "h" for i in range(10)}
    dates = {f"chef-2026061{i}-01@x": f"2026-06-1{i}" for i in range(10)}
    dates["chef-20260605-01@x"] = "2026-06-05"
    dates["chef-20260620-01@x"] = "2026-06-20"
    try:
        lib.plan_set_sync(
            existing=existing,
            incoming={"chef-20260605-01@x": "h", "chef-20260620-01@x": "h"},
            dates=dates,
            today=TODAY,
            max_delete=3)
    except lib.SetSyncTooManyDeletions as e:
        assert "3" in str(e), str(e)
        return
    raise AssertionError("SetSyncTooManyDeletions が投げられなかった")


def test_deletion_at_the_cap_is_allowed():
    existing = {"chef-20260610-01@x": "h1", "chef-20260611-01@x": "h2"}
    dates = {"chef-20260610-01@x": "2026-06-10",
             "chef-20260611-01@x": "2026-06-11",
             "chef-20260605-01@x": "2026-06-05",
             "chef-20260620-01@x": "2026-06-20"}
    got = lib.plan_set_sync(
        existing=existing,
        incoming={"chef-20260605-01@x": "h", "chef-20260620-01@x": "h"},
        dates=dates,
        today=TODAY,
        max_delete=2)
    assert len(got["delete"]) == 2, got


def test_single_incoming_event_narrows_the_range_to_one_day():
    # 範囲は incoming の [min, max]。1 件しか取れなければ単日になり、
    # 他の日付は「範囲外」として削除対象から外れる (保守的な既定)。
    got = lib.plan_set_sync(
        existing={"chef-20260610-01@x": "h1"},
        incoming={"chef-20260620-01@x": "h"},
        dates={"chef-20260610-01@x": "2026-06-10",
               "chef-20260620-01@x": "2026-06-20"},
        today=TODAY)
    assert got["delete"] == [], got


def test_event_on_today_is_deletable():
    # 境界: dtstart == today は「今日以降」に含む
    got = lib.plan_set_sync(
        existing={"chef-20260601-01@x": "h1"},
        incoming={"chef-20260530-01@x": "h2", "chef-20260620-01@x": "h3"},
        dates={"chef-20260601-01@x": "2026-06-01",
               "chef-20260530-01@x": "2026-05-30",
               "chef-20260620-01@x": "2026-06-20"},
        today=TODAY)
    assert got["delete"] == ["chef-20260601-01@x"], got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all set-sync tests passed")
