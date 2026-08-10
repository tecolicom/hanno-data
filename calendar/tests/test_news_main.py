#!/usr/bin/env python3
"""cal-tourism-news-fetch の main / process_news のユニットテスト。
実行: python3 calendar/tests/test_news_main.py
"""
from __future__ import annotations
import glob
import importlib.machinery
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

BON = {
    "id": 101,
    "url": "https://hanno-tourism.jp/news/bon-odori/",
    "title": "8月8日(土) はんのう昭和盆踊りへ♪",
    "body_html": "<p>日時:2026年8月8日(土) 午後6時から午後9時まで。会場は中央公園です。"
                 "どなたでもご参加いただけます。雨天の場合は中止となります。</p>",
    "date_gmt": "2026-08-07T06:18:16",
    "modified_gmt": "2026-08-07T06:18:16",
    "tags": [6],
}


def _stub_llm(payload):
    mod.call_llm = lambda system, user, **kw: json.dumps(payload,
                                                         ensure_ascii=False)


def _files(d):
    return sorted(os.path.basename(p)
                  for p in glob.glob(os.path.join(d, "**", "*.yaml"),
                                     recursive=True))


def _notice_name(item):
    h6 = mod.content_hash_of(item)[:6]
    return f"08-07_tourism-news-101-{h6}.yaml"


def test_process_news_writes_both_entries():
    _stub_llm({"summary": "盆踊りが開催されます。", "event_date": "2026-08-08",
               "event_end_date": None, "date_evidence": "日時:2026年8月8日(土)",
               "status": "normal"})
    with tempfile.TemporaryDirectory() as d:
        r = mod.process_news([BON], d, False, {})
        assert r["notice"] == 1 and r["event"] == 1, r
        names = _files(d)
        assert _notice_name(BON) in names, names
        assert "08-08_tourism-news-101-event.yaml" in names, names


def test_process_news_writes_notice_only_when_no_date():
    _stub_llm({"summary": "会報誌を発行しました。", "event_date": None,
               "event_end_date": None, "date_evidence": None,
               "status": "normal"})
    with tempfile.TemporaryDirectory() as d:
        r = mod.process_news([BON], d, False, {})
        assert r["notice"] == 1 and r["event"] == 0, r
        assert _files(d) == [_notice_name(BON)], _files(d)


def test_process_news_records_cache_on_success():
    _stub_llm({"summary": "s", "event_date": None, "event_end_date": None,
               "date_evidence": None, "status": "normal"})
    cache = {}
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([BON], d, False, cache)
    assert cache[BON["url"]]["modified_gmt"] == "2026-08-07T06:18:16", cache


def test_process_news_does_not_record_cache_on_llm_failure():
    """失敗した記事は次回リトライされる必要がある。"""
    mod.call_llm = lambda system, user, **kw: None
    cache = {}
    with tempfile.TemporaryDirectory() as d:
        r = mod.process_news([BON], d, False, cache)
    assert r["llm_fail"] == 1, r
    assert BON["url"] not in cache, cache


def test_process_news_keeps_existing_cache_fields():
    _stub_llm({"summary": "s", "event_date": None, "event_end_date": None,
               "date_evidence": None, "status": "normal"})
    cache = {BON["url"]: {"etag": 'W/"abc"'}}
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([BON], d, False, cache)
    assert cache[BON["url"]]["etag"] == 'W/"abc"', cache


def test_dry_run_writes_nothing():
    _stub_llm({"summary": "s", "event_date": "2026-08-08",
               "event_end_date": None, "date_evidence": "日時:2026年8月8日(土)",
               "status": "normal"})
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([BON], d, True, {})
        assert _files(d) == [], _files(d)


THIN = dict(BON, id=777,
            url="https://hanno-tourism.jp/news/eco-flier-autumn2026",
            title="飯能エコツアーチラシ2026.秋号",
            body_html="<p>PDF</p>")


def test_thin_body_counts_as_skip_not_failure():
    """実データ: エコツアーチラシは本文が PDF リンクだけ。

    MIN_BODY_CHARS の安全装置で LLM を呼ばないのは正常動作であって失敗ではない。
    これを llm_fail に数えると「全件失敗 = API 障害」と誤判定する。
    """
    called = {"n": 0}

    def _f(system, user, **kw):
        called["n"] += 1
        return "{}"
    mod.call_llm = _f
    with tempfile.TemporaryDirectory() as d:
        r = mod.process_news([THIN], d, False, {})
    assert called["n"] == 0, "薄い本文で LLM を呼んではいけない"
    assert r["short_body"] == 1, r
    assert r["llm_fail"] == 0, r


def test_thin_body_is_cached():
    """再実行しても結果が変わらないのでキャッシュに記録する。

    記録しないと毎回リトライ対象に残り続ける (実測: CI が毎回 4 件を再処理した)。
    """
    mod.call_llm = lambda system, user, **kw: None
    cache = {}
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([THIN], d, False, cache)
    assert THIN["url"] in cache, cache


def test_llm_all_failed_ignores_thin_bodies():
    """変更分がたまたま全部チラシだった日に exit 2 で誤発火しないこと。"""
    stats = {"short_body": 4, "llm_fail": 0}
    assert mod.llm_all_failed(stats, n_todo=4) is False


def test_llm_all_failed_detects_real_outage():
    stats = {"short_body": 0, "llm_fail": 3}
    assert mod.llm_all_failed(stats, n_todo=3) is True


def test_llm_all_failed_false_on_partial_failure():
    stats = {"short_body": 1, "llm_fail": 1}
    assert mod.llm_all_failed(stats, n_todo=3) is False


def test_check_news_count_exits_when_too_few():
    try:
        mod.check_news_count(50, 100)
    except SystemExit as e:
        assert e.code == 2, e
    else:
        raise AssertionError("should have exited")


def test_check_news_count_passes():
    mod.check_news_count(137, 100)   # 例外が出なければよい


def test_build_description_adds_disclaimer_for_llm_summary():
    got = mod.build_description({"summary": "要約です。", "status": "normal"},
                                "本文" * 300)
    assert mod.AI_DISCLAIMER_JP in got, got
    assert "要約です。" in got, got


def test_build_description_falls_back_to_body():
    got = mod.build_description({"summary": "", "status": "normal"}, "短い本文")
    assert "短い本文" in got, got
    assert mod.AI_DISCLAIMER_JP not in got, got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-main tests passed")
