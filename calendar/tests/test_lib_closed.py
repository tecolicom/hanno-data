#!/usr/bin/env python3
"""cal-lib-closed-fetch の純粋関数のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_lib_closed.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-lib-closed-fetch")
loader = importlib.machinery.SourceFileLoader("cal_lib_closed_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_lib_closed_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

_LIB = {"code": "02", "name": "こども図書館",
        "uid_prefix": "libkids-closed", "source_type": "hanno-lib-kids-closed"}
_PAGE = "https://www.hanno-lib.jp/calendar/"


def test_closing_items_shape():
    got = mod.closing_items(["2026-08-03", "2026-08-12"], _LIB, _PAGE, "🏛 ")
    assert got == [
        {"date": "2026-08-03", "summary": "🏛 こども図書館 休館",
         "description": "こども図書館は休館です。"},
        {"date": "2026-08-12", "summary": "🏛 こども図書館 休館",
         "description": "こども図書館は休館です。"},
    ], got


def test_closing_items_keeps_館名_in_summary():
    """カレンダーが分かれていても日次表示では混ざるので「休館」だけにしない。"""
    got = mod.closing_items(["2026-08-03"], _LIB, _PAGE, "🏛 ")
    assert "こども図書館" in got[0]["summary"], got


def test_closing_items_empty():
    assert mod.closing_items([], _LIB, _PAGE, "🏛 ") == []


def test_check_min_days_passes():
    terms = [{"month": "202608", "closing_day": ["a", "b", "c", "d"]},
             {"month": "202609", "closing_day": ["a", "b", "c"]}]
    mod.check_min_days(terms, "02", 3)   # 例外が飛ばなければ OK


def test_check_min_days_flags_a_thin_month():
    """月ごとに見る。合計で見ると 1 か月の欠落が隠れる。"""
    terms = [{"month": "202608", "closing_day": ["a", "b", "c", "d", "e", "f"]},
             {"month": "202609", "closing_day": ["a"]}]
    try:
        mod.check_min_days(terms, "02", 3)
    except ValueError as e:
        assert "202609" in str(e), e
        return
    raise AssertionError("薄い月があるのに ValueError が飛ばない")


def test_check_min_days_rejects_empty_terms():
    """term が 1 つも無いのは異常 (今月分は必ず返るはず)。"""
    try:
        mod.check_min_days([], "02", 3)
    except ValueError:
        return
    raise AssertionError("term 空なのに ValueError が飛ばない")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all lib-closed tests passed")
