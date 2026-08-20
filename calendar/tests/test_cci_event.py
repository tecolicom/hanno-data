#!/usr/bin/env python3
"""cal-cci-event-fetch の純粋関数のユニットテスト。
実行: python3 calendar/tests/test_cci_event.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_cci_event_fetch",
                                              os.path.join(BIN, "cal-cci-event-fetch"))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


def test_category_prefix_by_id():
    assert m.summary_for("補助金の募集", [20]) == "🎓 補助金の募集"
    assert m.summary_for("夏季休業日のお知らせ", [7]) == "ℹ️ 夏季休業日のお知らせ"
    assert m.summary_for("専門家相談の日程", [10]) == "💼 専門家相談の日程"
    assert m.summary_for("はんのう元気市", [8]) == "🏮 はんのう元気市"


def test_unknown_category_gets_no_prefix():
    # 検定 (9) 等、対象外のカテゴリしか持たない記事は prefix 無し。
    # そもそも取得対象外だが、防御的に素通りさせる。
    assert m.summary_for("簿記検定の結果", [9]) == "簿記検定の結果"
    assert m.summary_for("カテゴリ無し", []) == "カテゴリ無し"


def test_first_known_category_wins():
    # 複数カテゴリが付いた記事は CATEGORIES の定義順で最初に一致したものを使う
    got = m.summary_for("複合記事", [9, 8])
    assert got == "🏮 複合記事", got


def test_body_strips_html_entities_and_tags():
    post = {"content": {"rendered": "<p>８月14日は<strong>休業</strong>します。</p>\n<p>&amp; 追記</p>"}}
    got = m.body_from_post(post)
    assert "<p>" not in got, got
    assert "&amp;" not in got, got
    assert "休業" in got, got
    assert "& 追記" in got, got


def test_content_hash_ignores_summary_method():
    # content_hash は title + date + body のみ。要約方式を変えても動かない
    # (2026-05-26 の flood 障害の回帰テスト)。
    a = m.content_hash_for("題", "2026-08-11", "本文")
    b = m.content_hash_for("題", "2026-08-11", "本文")
    assert a == b
    assert a != m.content_hash_for("題", "2026-08-11", "別の本文")
    assert a != m.content_hash_for("別の題", "2026-08-11", "本文")
    assert a != m.content_hash_for("題", "2026-08-12", "本文")
    assert len(a) == 16, a


def test_kentei_category_is_not_in_scope():
    # 9 (検定) を取り込み対象に入れない (設計判断の回帰テスト)
    assert 9 not in m.CATEGORIES, m.CATEGORIES
    assert set(m.CATEGORIES) == {7, 8, 10, 20}, m.CATEGORIES


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all cci-event tests passed")
