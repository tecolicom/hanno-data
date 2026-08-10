#!/usr/bin/env python3
"""cal-tourism-news-fetch の本番作成条件のユニットテスト。
実行: python3 calendar/tests/test_news_gating.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

BODY = "日時:2026年8月8日(土) 午後6時〜 会場:中央公園"
PUB = date(2026, 8, 7)


def _ex(event_date="2026-08-08", evidence="日時:2026年8月8日(土)",
        status="normal", end=None):
    return {"summary": "s", "event_date": event_date, "event_end_date": end,
            "date_evidence": evidence, "status": status}


def test_creates_for_valid_normal_event():
    ok, why = mod.should_create_event(_ex(), BODY, PUB, False, None)
    assert ok is True, why


def test_skips_when_event_date_is_null():
    """実データ: ムーミン谷みずあそび (終了日しか無い)。"""
    ok, why = mod.should_create_event(
        _ex(event_date=None, evidence=None, end="2026-09-06"),
        BODY, PUB, False, None)
    assert ok is False and "no-date" in why, why


def test_skips_canceled_article_without_existing_event():
    """中止として生まれた記事は本番を作らない (告知のみ)。"""
    ok, why = mod.should_create_event(_ex(status="canceled"), BODY, PUB,
                                      False, None)
    assert ok is False and "canceled" in why, why


def test_creates_when_canceled_but_existing_event_present():
    """既に本番を出していれば【中止】へ書き換えるため True を返す。"""
    ok, why = mod.should_create_event(_ex(status="canceled"), BODY, PUB,
                                      True, None)
    assert ok is True, why


def test_skips_on_manual_conflict():
    """実データ: 令和8年飯能夏祭り。手動 YAML を優先する。"""
    ok, why = mod.should_create_event(_ex(), BODY, PUB, False,
                                      "calendar/events/2026/07-18_x.yaml")
    assert ok is False and "manual" in why, why


def test_skips_when_verification_fails():
    ok, why = mod.should_create_event(_ex(evidence="本文に無い根拠"), BODY, PUB,
                                      False, None)
    assert ok is False and "evidence-not-found" in why, why


def test_normalize_news_url_decodes_percent_encoding():
    enc = ("https://hanno-tourism.jp/news/"
           "%E4%BB%A4%E5%92%8C%EF%BC%98%E5%B9%B4/")
    dec = "https://hanno-tourism.jp/news/令和８年/"
    assert mod.normalize_news_url(enc) == mod.normalize_news_url(dec)


def test_normalize_news_url_adds_trailing_slash():
    a = mod.normalize_news_url("https://hanno-tourism.jp/news/abc")
    b = mod.normalize_news_url("https://hanno-tourism.jp/news/abc/")
    assert a == b, (a, b)


def test_find_manual_conflict_detects_encoded_url():
    enc = ("https://hanno-tourism.jp/news/"
           "%E4%BB%A4%E5%92%8C%EF%BC%98%E5%B9%B4/")
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "2026"))
        with open(os.path.join(d, "2026", "07-18_x.yaml"), "w",
                  encoding="utf-8") as f:
            f.write('uid: "natsumatsuri-20260718@hanno.city.tecoli.com"\n'
                    f'url: "{enc}"\n')
        got = mod.find_manual_conflict(d, "https://hanno-tourism.jp/news/令和８年/")
        assert got is not None, got


def test_find_manual_conflict_ignores_crawler_owned_yaml():
    """自分が前回作った YAML を「手動」と誤認しない。"""
    url = "https://hanno-tourism.jp/news/abc/"
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "2026"))
        with open(os.path.join(d, "2026", "08-08_tourism-news-101-event.yaml"),
                  "w", encoding="utf-8") as f:
            f.write('uid: "tourism-news-101-event@hanno.city.tecoli.com"\n'
                    f'url: "{url}"\n'
                    "source:\n"
                    f"  type: {mod.SOURCE_TYPE}\n")
        assert mod.find_manual_conflict(d, url) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-gating tests passed")
