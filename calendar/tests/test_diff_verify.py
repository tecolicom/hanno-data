#!/usr/bin/env python3
"""cal-oshirase-fetch の差分行の機械検算 (drop_unchanged_claims) のユニットテスト。

LLM は「〜が〜に変更されました」の型に、変わっていない値を入れてしまうことが
ある。DIFF_SYSTEM_PROMPT で禁じ temperature=0 にしてもなお起きたので、生成後に
コード側で検査する。実例 (2026-08-19 本番、oshirase-7334-62e7b2):

    物件Aの最低売却価格が1,970万円から1,970万円に、入札保証金が295.5万円から
    295.5万円に変更されました。…

実行: python3 calendar/tests/test_diff_verify.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_oshirase_fetch",
                                              os.path.join(BIN, "cal-oshirase-fetch"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

drop = mod.drop_unchanged_claims


# ---------- 実際に起きた誤り ----------

REAL_BOGUS = (
    "物件Aの最低売却価格が1,970万円から1,970万円に、入札保証金が295.5万円から"
    "295.5万円に変更されました。物件Bの最低売却価格が4,690万円から4,690万円に、"
    "入札保証金が703.5万円から703.5万円に変更されました。"
)


def test_real_world_bogus_line_is_dropped_entirely():
    # 4 対すべて同値 = 全文が無価値 → None (「主な変更」行を出さない)
    assert drop(REAL_BOGUS) is None


# ---------- 同値の検出 ----------

def test_same_value_sentence_is_dropped():
    assert drop("料金が1,000円から1,000円に変更されました。") is None


def test_fullwidth_digits_are_compared_after_normalization():
    assert drop("料金が１，０００円から1,000円に変更されました。") is None


# ---------- 真の変更は残す ----------

def test_genuine_change_is_kept():
    s = "料金が1,000円から2,000円に変更されました。"
    assert drop(s) == s


def test_prefix_digits_are_not_treated_as_same():
    # 「1,970万円 から 970万円」は真の変更。左辺の末尾一致で誤検出しないこと
    s = "最低売却価格が1,970万円から970万円に変更されました。"
    assert drop(s) == s


def test_date_range_is_not_a_change_claim():
    s = "申込期間が8月21日から9月3日に変更されました。"
    assert drop(s) == s


def test_text_without_change_claims_is_untouched():
    s = "入札参加資格の要件が追加されました。"
    assert drop(s) == s


# ---------- 混在 ----------

def test_only_the_bogus_sentence_is_dropped():
    src = ("料金が1,000円から2,000円に変更されました。"
           "定員が30名から30名に変更されました。")
    assert drop(src) == "料金が1,000円から2,000円に変更されました。"


def test_sentence_with_any_same_pair_is_dropped_whole():
    # 1 文に真の対と同値の対が混ざる場合、その文の生成は信用できないので丸ごと捨てる
    src = "料金が1,000円から2,000円に、定員が30名から30名に変更されました。"
    assert drop(src) is None


# ---------- 境界 ----------

def test_none_and_empty_pass_through():
    assert drop(None) is None
    assert drop("") is None
    assert drop("   ") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all diff-verify tests passed")
