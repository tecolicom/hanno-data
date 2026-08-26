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


def test_month_window_crosses_year_wide():
    """年を跨いで 11 か月先まで要求するケース。月の繰り上がりの off-by-one を捕まえる回帰網。"""
    assert hl.month_window("2026-01-01", 11) == ("202601", "202612")


def test_month_window_starts_in_december():
    """12 月起点で 12 か月先。term_to の年が 1 つ繰り上がることを確認する。"""
    assert hl.month_window("2026-12-31", 12) == ("202612", "202712")


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


def test_terms_of_raises_when_term_is_missing():
    """館は見つかるが term キー自体が無いケース。"""
    try:
        hl.terms_of({"libraries": [{"code": "02"}]}, "02")
    except ValueError:
        return
    raise AssertionError("term が無いのに ValueError が飛ばない")


def test_terms_of_raises_when_term_is_not_a_list():
    """term が dict や文字列で返るケース (list でなければ壊れた応答)。"""
    for bad_term in ({"month": "202608"}, "202608"):
        try:
            hl.terms_of({"libraries": [{"code": "02", "term": bad_term}]}, "02")
        except ValueError:
            continue
        raise AssertionError(f"term={bad_term!r} が list でないのに ValueError が飛ばない")


def test_terms_of_raises_when_library_entry_is_not_a_dict():
    """libraries の要素が dict でない場合に AttributeError ではなく ValueError で落ちること。

    Task 3/4 は except ValueError で受けるため、ここが AttributeError のままだと
    そこだけ traceback になる。
    """
    for bad_libs in (["oops"], [None]):
        try:
            hl.terms_of({"libraries": bad_libs}, "02")
        except ValueError:
            continue
        raise AssertionError(f"libraries={bad_libs!r} なのに ValueError が飛ばない")


def test_days_of_normalizes_and_sorts():
    terms = hl.terms_of(_SAMPLE, "02")
    assert hl.days_of(terms, "closing_day") == ["2026-08-03", "2026-08-12", "2026-09-07"]


def test_days_of_missing_key_is_empty():
    terms = hl.terms_of(_SAMPLE, "02")
    assert hl.days_of(terms, "event_day") == ["2026-08-01"]
    assert hl.days_of([{"month": "202610"}], "closing_day") == []


def test_days_of_dedups_across_terms():
    """term を跨いで同じ日付が重複するケース。

    現行のサンプルは term を跨いだ重複が無いため、set を list に変えても
    テストが緑のままになってしまう。境界月の休館日が前後の term に重複して
    載る (配信元でも起こりうる) ケースを別途足して重複潰しを検証する。
    """
    terms = [
        {"month": "202608", "closing_day": ["2026/08/31"]},
        {"month": "202609", "closing_day": ["2026/08/31", "2026/09/01"]},
    ]
    assert hl.days_of(terms, "closing_day") == ["2026-08-31", "2026-09-01"]


def test_days_of_raises_for_unpadded_date():
    """ゼロ埋め無し ("2026/8/3") は 'None' のようなソート崩れや不正 UID の元になる。"""
    terms = [{"month": "202608", "closing_day": ["2026/8/3"]}]
    try:
        hl.days_of(terms, "closing_day")
    except ValueError:
        return
    raise AssertionError("ゼロ埋め無しの日付なのに ValueError が飛ばない")


def test_days_of_raises_when_value_is_a_string_not_a_list():
    """値が list でなく文字列だと 1 文字ずつ回ってしまう ("2026/08/03" → ['-','0',...])。"""
    terms = [{"month": "202608", "closing_day": "2026/08/03"}]
    try:
        hl.days_of(terms, "closing_day")
    except ValueError:
        return
    raise AssertionError("closing_day が文字列なのに ValueError が飛ばない")


def test_days_of_raises_for_none_or_int_entries():
    """None や int が混ざると str() で 'None' / '20260803' のような値が日付として通ってしまう。"""
    for bad_entry in (None, 20260803):
        terms = [{"month": "202608", "closing_day": [bad_entry]}]
        try:
            hl.days_of(terms, "closing_day")
        except ValueError:
            continue
        raise AssertionError(f"closing_day に {bad_entry!r} が混ざっているのに ValueError が飛ばない")


def test_fetch_cal_sends_one_library_per_request():
    """hl.fetch_text の差し替えは try/finally で必ず戻す。

    テストは名前のソート順に走る。ここで差し替えたまま戻さないと、将来 "f" より
    後ろの名前 (例: test_terms_of_*) を足した人が実物ではなく偽物の fetch_text を
    意図せず掴んでしまう。
    """
    seen = []

    def _fake(url):
        seen.append(url)
        return json.dumps(_SAMPLE)

    original = hl.fetch_text
    hl.fetch_text = _fake
    try:
        got = hl.fetch_cal("https://example.test/cal.php", "02", "202608", "202708")
    finally:
        hl.fetch_text = original
    assert got == _SAMPLE, got
    assert seen == ["https://example.test/cal.php"
                    "?libraries=02&term_from=202608&term_to=202708"], seen


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all _hanno_lib tests passed")
