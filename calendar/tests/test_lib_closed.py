#!/usr/bin/env python3
"""cal-lib-closed-fetch の純粋関数のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_lib_closed.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import urllib.error

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


def test_check_min_days_rejects_string_closing_day():
    """closing_day が文字列だと len() が通ってしまう ("2027-04-01" == 10 文字)。

    型検査が無いと月 3 日の閾値を素通りしてしまうので、isinstance で止める。
    """
    terms = [{"month": "202608", "closing_day": "2027-04-01"}]
    try:
        mod.check_min_days(terms, "02", 3)
    except ValueError as e:
        assert "202608" in str(e), e
        return
    raise AssertionError("closing_day が文字列なのに ValueError が飛ばない")


def test_check_min_days_rejects_dict_closing_day():
    """closing_day が dict のときも同じく型検査で止める。"""
    terms = [{"month": "202608", "closing_day": {"a": 1, "b": 2, "c": 3}}]
    try:
        mod.check_min_days(terms, "02", 3)
    except ValueError as e:
        assert "202608" in str(e), e
        return
    raise AssertionError("closing_day が dict なのに ValueError が飛ばない")


def test_main_isolates_communication_failure_per_library():
    """Ruling 9: 通信そのものの失敗も館ごとに閉じる。

    _hanno_lib.fetch_cal は urllib の例外をラップせず呼出側に伝播させる (docstring
    の契約)。DNS 失敗・タイムアウト・HTTP エラーは urllib.error.URLError
    (OSError のサブクラス) として飛ぶので、except ValueError だけでは素通りして
    main() 全体を落としてしまい、「1 館の失敗を他館に波及させない」(Ruling 7) が
    いちばん起きやすい失敗 (通信) に対して効かなくなる。01 を通信エラーにしても
    02 は最後まで処理され、exit code は検査・取得失敗と同じ 2 になることを確認する。
    """
    fixtures = os.path.join(HERE, "fixtures", "cal-lib-closed-fetch")
    with open(os.path.join(fixtures, "cal-02.json"), encoding="utf-8") as f:
        cal_02 = json.load(f)

    def fake_fetch_cal(cal_url, lib_code, term_from, term_to):
        if lib_code == "01":
            raise urllib.error.URLError("boom")
        return cal_02

    # クローラは `from _hanno_lib import fetch_cal` しているので、差し替えは
    # _hanno_lib の実体ではなくクローラの名前空間 (mod.fetch_cal) に対して行う。
    orig_fetch_cal = mod.fetch_cal
    orig_argv = sys.argv
    mod.fetch_cal = fake_fetch_cal
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            sys.argv = ["cal-lib-closed-fetch", "--out-dir", out_dir,
                        "--today", "2026-08-24"]
            try:
                mod.main()
            except SystemExit as e:
                assert e.code == 2, e.code
            else:
                raise AssertionError("01 が通信エラーなのに main() が exit しない")

            written = []
            for _root, _dirs, files in os.walk(out_dir):
                written.extend(files)
            assert any("libkids-closed-" in f for f in written), written
            assert not any("libmain-closed-" in f for f in written), written
    finally:
        sys.argv = orig_argv
        mod.fetch_cal = orig_fetch_cal


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all lib-closed tests passed")
