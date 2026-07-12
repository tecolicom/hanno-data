#!/usr/bin/env python3
"""_lib の Last-Modified→dtstart 変換のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_last_modified_dating.py
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "bin", "_lib.py")
loader = importlib.machinery.SourceFileLoader("cal_lib", LIB)
spec = importlib.util.spec_from_loader("cal_lib", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def test_jst_date_same_day():
    # 02:29 GMT = 11:29 JST 同日
    assert mod.last_modified_to_jst_date("Wed, 08 Jul 2026 02:29:43 GMT") == "2026-07-08"


def test_jst_date_crosses_midnight():
    # 20:00 GMT = 翌 05:00 JST
    assert mod.last_modified_to_jst_date("Tue, 07 Jul 2026 20:00:00 GMT") == "2026-07-08"


def test_jst_date_unparseable():
    assert mod.last_modified_to_jst_date("garbage") is None
    assert mod.last_modified_to_jst_date(None) is None


def test_dtstart_is_lm_plus_one():
    assert mod.dtstart_from_last_modified("Wed, 08 Jul 2026 02:29:43 GMT", "2026-07-12") == "2026-07-09"


def test_dtstart_crosses_month():
    # 31 Jul JST → +1 = 01 Aug
    assert mod.dtstart_from_last_modified("Fri, 31 Jul 2026 03:00:00 GMT", "2026-07-12") == "2026-08-01"


def test_dtstart_fallback_when_no_header():
    assert mod.dtstart_from_last_modified(None, "2026-07-12") == "2026-07-12"
    assert mod.dtstart_from_last_modified("garbage", "2026-07-12") == "2026-07-12"


if __name__ == "__main__":
    test_jst_date_same_day()
    test_jst_date_crosses_midnight()
    test_jst_date_unparseable()
    test_dtstart_is_lm_plus_one()
    test_dtstart_crosses_month()
    test_dtstart_fallback_when_no_header()
    print("OK: all last-modified dating tests passed")
