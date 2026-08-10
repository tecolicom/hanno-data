#!/usr/bin/env python3
"""_lib.normalize_circled_weekday のユニットテスト。
実行: python3 calendar/tests/test_normalize_weekday.py
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


def test_parenthesized_form():
    # 実データ: 「飯能河原6/27㈯・28㈰の営業について」
    got = lib.normalize_circled_weekday("飯能河原6/27㈯・28㈰の営業について")
    assert got == "飯能河原6/27(土)・28(日)の営業について", got


def test_circled_kanji_form():
    got = lib.normalize_circled_weekday("3月21日㊏案内業務お休み")
    assert got == "3月21日(土)案内業務お休み", got


def test_all_seven_days():
    src = "㈪㈫㈬㈭㈮㈯㈰"
    assert lib.normalize_circled_weekday(src) == "(月)(火)(水)(木)(金)(土)(日)"


def test_leaves_other_text_untouched():
    src = "日時:2026年8月8日(土) 午後5時〜"
    assert lib.normalize_circled_weekday(src) == src


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all normalize-weekday tests passed")
