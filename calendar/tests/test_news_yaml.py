#!/usr/bin/env python3
"""cal-tourism-news-fetch の YAML 生成のユニットテスト。
実行: python3 calendar/tests/test_news_yaml.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

ITEM = {
    "id": 101,
    "url": "https://hanno-tourism.jp/news/bon-odori/",
    "title": "8月8日(土) はんのう昭和盆踊りへ♪",
    "body_html": "<p>日時:2026年8月8日(土)</p>",
    "date_gmt": "2026-08-07T06:18:16",
    "modified_gmt": "2026-08-07T06:18:16",
    "tags": [6],
}
EX = {"summary": "盆踊りが開催されます。", "event_date": "2026-08-08",
      "event_end_date": None, "date_evidence": "日時:2026年8月8日(土)",
      "status": "normal"}
FIXED_TS = "2026-08-10T00:00:00Z"


def test_jst_date_of_crosses_day_boundary():
    # 06:18 UTC = 15:18 JST 同日
    assert mod.jst_date_of("2026-08-07T06:18:16") == "2026-08-07"
    # 16:00 UTC = 翌日 01:00 JST
    assert mod.jst_date_of("2026-08-07T16:00:00") == "2026-08-08"


def test_uids():
    assert mod.notice_uid("tourism-news", 101, "abcdef0123456789") == \
        "tourism-news-101-abcdef@hanno.city.tecoli.com"
    assert mod.event_uid("tourism-news", 101) == \
        "tourism-news-101-event@hanno.city.tecoli.com"


def test_content_hash_is_stable_and_changes_with_body():
    a = mod.content_hash_of(ITEM)
    assert a == mod.content_hash_of(dict(ITEM)), "同じ入力なら同じハッシュ"
    b = mod.content_hash_of(dict(ITEM, body_html="<p>違う本文</p>"))
    assert a != b, "本文が変われば変わる"
    # modified_gmt は内容ではないのでハッシュに含めない
    c = mod.content_hash_of(dict(ITEM, modified_gmt="2099-01-01T00:00:00"))
    assert a == c, "modified_gmt はハッシュに含めない"


def test_strip_leading_date_removes_redundant_prefix():
    """本番は日付の位置そのものが情報なので、タイトル先頭の日付は二重になる。"""
    f = mod.strip_leading_date
    assert f("8月8日(土) はんのう昭和盆踊りへ♪") == "はんのう昭和盆踊りへ♪"
    assert f("3月21日(土)案内業務お休みのお知らせ") == "案内業務お休みのお知らせ"


def test_strip_leading_date_handles_fullwidth_and_ranges():
    f = mod.strip_leading_date
    # 全角数字 + 全角括弧 + 全角空白
    assert f("８月12日（水）　飯能なぐりの星空観察会　開催！") == "飯能なぐりの星空観察会　開催！"
    # 「・19日(日)」のように月を省いた連結も食う
    assert f("7月18日(土)・19日(日)休業のお知らせ") == "休業のお知らせ"


def test_strip_leading_date_leaves_non_leading_dates():
    """先頭以外の日付は文の一部なので触らない。"""
    f = mod.strip_leading_date
    src = "飯能河原6/27㈯・28㈰の営業について"
    assert f(src) == src
    src2 = "「氷彫刻」で表現されたムーミンの物語の世界2/15(日)、23(祝)限定で！"
    assert f(src2) == src2


def test_strip_leading_date_keeps_title_when_nothing_would_remain():
    """タイトルが日付だけなら落とさない (空 summary を作らないための退避)。"""
    f = mod.strip_leading_date
    assert f("8月8日(土)") == "8月8日(土)"


def test_event_summary_drops_leading_date_but_notice_keeps_it():
    item = dict(ITEM, title="8月8日(土) はんのう昭和盆踊りへ♪")
    ev = mod.build_event_yaml(item, EX, "本文", fetched_at=FIXED_TS)
    nt = mod.build_notice_yaml(item, EX, "本文", fetched_at=FIXED_TS)
    ev_sum = [l for l in ev.split("\n") if l.startswith("summary:")][0]
    nt_sum = [l for l in nt.split("\n") if l.startswith("summary:")][0]
    assert "8月8日" not in ev_sum, ev_sum
    assert "はんのう昭和盆踊りへ♪" in ev_sum, ev_sum
    # 告知は掲載日に置くので、タイトル内の日付は「いつの話か」を示す情報
    assert "8月8日" in nt_sum, nt_sum


def test_summary_prefix_for():
    assert mod.summary_prefix_for([6]) == mod.SUMMARY_PREFIX_EVENT
    assert mod.summary_prefix_for([7, 4]) == mod.SUMMARY_PREFIX_EVENT
    assert mod.summary_prefix_for([4]) == mod.SUMMARY_PREFIX_OTHER
    assert mod.summary_prefix_for([]) == mod.SUMMARY_PREFIX_OTHER


def test_notice_yaml_uses_publish_date():
    doc = mod.build_notice_yaml(ITEM, EX, "本文", fetched_at=FIXED_TS)
    assert 'dtstart: "2026-08-07"' in doc, doc
    assert 'dtend: "2026-08-07"' in doc, doc
    h6 = mod.content_hash_of(ITEM)[:6]
    assert f'uid: "tourism-news-101-{h6}@hanno.city.tecoli.com"' in doc, doc
    assert mod.SUMMARY_PREFIX_NOTICE in doc, doc
    assert f"type: {mod.SOURCE_TYPE}" in doc, doc
    assert "content_hash:" in doc, doc


def test_event_yaml_uses_extracted_date():
    doc = mod.build_event_yaml(ITEM, EX, "本文", fetched_at=FIXED_TS)
    assert 'dtstart: "2026-08-08"' in doc, doc
    assert 'dtend: "2026-08-08"' in doc, doc
    assert 'uid: "tourism-news-101-event@hanno.city.tecoli.com"' in doc, doc
    assert mod.SUMMARY_PREFIX_EVENT in doc, doc


def test_event_yaml_uses_end_date_for_range():
    ex = dict(EX, event_date="2026-03-28", event_end_date="2026-04-05")
    doc = mod.build_event_yaml(ITEM, ex, "本文", fetched_at=FIXED_TS)
    assert 'dtstart: "2026-03-28"' in doc, doc
    assert 'dtend: "2026-04-05"' in doc, doc


def test_event_yaml_marks_canceled():
    ex = dict(EX, status="canceled")
    doc = mod.build_event_yaml(ITEM, ex, "本文", fetched_at=FIXED_TS)
    assert "【中止】" in doc, doc


def test_yaml_has_no_raw_newline_in_scalar():
    """summary に改行が混ざると YAML が壊れるので空白に畳む。"""
    item = dict(ITEM, title="改行\nを含む\nタイトル")
    doc = mod.build_notice_yaml(item, EX, "本文", fetched_at=FIXED_TS)
    summary_line = [ln for ln in doc.split("\n") if ln.startswith("summary:")]
    assert len(summary_line) == 1, doc
    assert "改行 を含む タイトル" in summary_line[0], summary_line


def test_description_carries_summary_and_url():
    doc = mod.build_notice_yaml(ITEM, EX, "要約テキスト", fetched_at=FIXED_TS)
    assert "要約テキスト" in doc, doc
    assert ITEM["url"] in doc, doc


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-yaml tests passed")
