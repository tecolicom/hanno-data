#!/usr/bin/env python3
"""_hanno_lib のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_hanno_lib.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "_hanno_lib.py")
loader = importlib.machinery.SourceFileLoader("_hanno_lib", SCRIPT)
spec = importlib.util.spec_from_loader("_hanno_lib", loader)
hl = importlib.util.module_from_spec(spec)
loader.exec_module(hl)


def test_month_window_same_year():
    assert hl.month_window("2026-08-24", 12) == ("202608", "202708")


def test_month_window_crosses_year():
    assert hl.month_window("2026-12-01", 1) == ("202612", "202701")


def test_month_window_zero_ahead():
    assert hl.month_window("2026-01-31", 0) == ("202601", "202601")


_SAMPLE = {
    "libraries": [
        {"code": "01", "name": "市立図書館",
         "term": [{"month": "202608", "closing_day": ["2026/08/03"], "event_day": []}]},
        {"code": "02", "name": "こども図書館",
         "term": [{"month": "202608",
                   "closing_day": ["2026/08/03", "2026/08/12"],
                   "event_day": ["2026/08/01"]},
                  {"month": "202609", "closing_day": ["2026/09/07"]}]},
    ]
}


def test_terms_of_picks_the_right_library():
    terms = hl.terms_of(_SAMPLE, "02")
    assert [t["month"] for t in terms] == ["202608", "202609"], terms


def test_terms_of_raises_for_unknown_library():
    try:
        hl.terms_of(_SAMPLE, "99")
    except ValueError:
        return
    raise AssertionError("館が無いのに ValueError が飛ばない")


def test_terms_of_raises_when_shape_is_wrong():
    """取得層が死んだことを「0 件」と区別できなくしない。"""
    try:
        hl.terms_of({"error": "blocked"}, "02")
    except ValueError:
        return
    raise AssertionError("libraries が無いのに ValueError が飛ばない")


def test_days_of_normalizes_and_sorts():
    terms = hl.terms_of(_SAMPLE, "02")
    assert hl.days_of(terms, "closing_day") == ["2026-08-03", "2026-08-12", "2026-09-07"]


def test_days_of_missing_key_is_empty():
    terms = hl.terms_of(_SAMPLE, "02")
    assert hl.days_of(terms, "event_day") == ["2026-08-01"]
    assert hl.days_of([{"month": "202610"}], "closing_day") == []


def test_fetch_cal_sends_one_library_per_request():
    seen = []

    def _fake(url):
        seen.append(url)
        return json.dumps(_SAMPLE)

    hl.fetch_text = _fake
    got = hl.fetch_cal("https://example.test/cal.php", "02", "202608", "202708")
    assert got == _SAMPLE, got
    assert seen == ["https://example.test/cal.php"
                    "?libraries=02&term_from=202608&term_to=202708"], seen


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all _hanno_lib tests passed")
