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


# ---------- RSS のパース ----------

RSS_ITEM = '''<item>
	<title>「年収の壁の見直しで注意すべき税制実務のポイント」の開催について</title>
	<link>https://www.hanno-cci.or.jp/xo_event/xo_event-2778/</link>
	<dc:creator><![CDATA[editor]]></dc:creator>
	<pubDate>Tue, 11 Aug 2026 00:00:36 +0000</pubDate>
	<guid isPermaLink="false">https://www.hanno-cci.or.jp/?post_type=xo_event&#038;p=2778</guid>
	<description><![CDATA[「年収の壁」の見直しにより…]]></description>
	<content:encoded><![CDATA[<p>本文の一行目。</p>
<p>本文の二行目。</p>]]></content:encoded>
</item>'''

RSS_XML = f'<?xml version="1.0"?><rss><channel>{RSS_ITEM}</channel></rss>'


def test_parse_feed_extracts_fields():
    got = m.parse_feed(RSS_XML, "seminar")
    assert len(got) == 1, got
    p = got[0]
    assert p["id"] == 2778, p
    assert p["date"] == "2026-08-11", p
    assert p["link"] == "https://www.hanno-cci.or.jp/xo_event/xo_event-2778/", p
    assert p["title"]["rendered"].startswith("「年収の壁"), p
    assert "本文の一行目" in p["content"]["rendered"], p
    assert p["xo_event_cat"] == [20], p        # seminar → term id 20


def test_pubdate_is_converted_to_jst():
    # pubDate は UTC。JST に直してから日付にする。
    # 2026-08-11T00:00:36Z = 2026-08-11 09:00 JST → 同じ日
    assert m.parse_feed(RSS_XML, "seminar")[0]["date"] == "2026-08-11"
    # 2026-08-11T20:00:00Z = 2026-08-12 05:00 JST → 翌日になる
    late = RSS_XML.replace("Tue, 11 Aug 2026 00:00:36 +0000",
                           "Tue, 11 Aug 2026 20:00:00 +0000")
    assert m.parse_feed(late, "seminar")[0]["date"] == "2026-08-12"


def test_slug_to_category_id():
    assert m.SLUG_TO_CAT_ID == {"promotion": 8, "seminar": 20,
                                "manage": 10, "news": 7}, m.SLUG_TO_CAT_ID
    assert "exam" not in m.SLUG_TO_CAT_ID          # 検定は除外


def test_merge_dedupes_by_post_id():
    # 複数カテゴリを持つ記事は複数のフィードに現れる。記事 ID で名寄せする
    # (名寄せしないと実データで 60 件に見える。実際は 49 件)。
    a = m.parse_feed(RSS_XML, "seminar")
    b = m.parse_feed(RSS_XML, "manage")
    merged = m.merge_posts([a, b])
    assert len(merged) == 1, merged
    # カテゴリは両方が残る (CATEGORIES の定義順で category_of が選ぶ)
    assert sorted(merged[0]["xo_event_cat"]) == [10, 20], merged[0]


def test_merge_keeps_posts_sorted_newest_first():
    old = RSS_XML.replace("Tue, 11 Aug 2026 00:00:36 +0000",
                          "Mon, 05 Jan 2026 00:00:00 +0000").replace("p=2778", "p=1111")
    merged = m.merge_posts([m.parse_feed(RSS_XML, "seminar"), m.parse_feed(old, "news")])
    assert [p["id"] for p in merged] == [2778, 1111], merged


def test_kentei_category_is_not_in_scope():
    # 9 (検定) を取り込み対象に入れない (設計判断の回帰テスト)
    assert 9 not in m.CATEGORIES, m.CATEGORIES
    assert set(m.CATEGORIES) == {7, 8, 10, 20}, m.CATEGORIES


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all cci-event tests passed")
