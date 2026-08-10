#!/usr/bin/env python3
"""cal-tourism-news-fetch の LLM 抽出のユニットテスト。
call_llm を差し替えるので LLM を実呼び出ししない。
実行: python3 calendar/tests/test_news_extract.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def _stub(reply):
    """call_llm を固定応答に差し替え、渡された (system, user) を記録する。"""
    seen = {}

    def _f(system, user, **kw):
        seen["system"] = system
        seen["user"] = user
        seen["kw"] = kw
        return reply
    mod.call_llm = _f
    return seen


def test_extract_parses_json():
    _stub(json.dumps({
        "summary": "はんのう昭和盆踊りが開催されます。",
        "event_date": "2026-08-08",
        "event_end_date": None,
        "date_evidence": "日時:2026年8月8日(土)",
        "status": "normal",
    }, ensure_ascii=False))
    got = mod.extract_with_llm("盆踊り", "日時:2026年8月8日(土)" * 5)
    assert got["event_date"] == "2026-08-08", got
    assert got["date_evidence"] == "日時:2026年8月8日(土)", got
    assert got["status"] == "normal", got


def test_extract_strips_code_fence():
    # LLM が ```json ... ``` で包んで返すことがある
    _stub('```json\n{"summary":"x","event_date":null,"event_end_date":null,'
          '"date_evidence":null,"status":"normal"}\n```')
    got = mod.extract_with_llm("t", "本文" * 40)
    assert got is not None and got["event_date"] is None, got


def test_extract_normalizes_unknown_status():
    _stub(json.dumps({"summary": "x", "event_date": None, "event_end_date": None,
                      "date_evidence": None, "status": "なんか変な値"}))
    got = mod.extract_with_llm("t", "本文" * 40)
    assert got["status"] == "normal", got


def test_extract_returns_none_on_broken_json():
    _stub("これは JSON ではありません")
    assert mod.extract_with_llm("t", "本文" * 40) is None


def test_extract_returns_none_when_llm_unavailable():
    mod.call_llm = lambda system, user, **kw: None
    assert mod.extract_with_llm("t", "本文" * 40) is None


def test_extract_skips_short_body():
    """安全装置: 本文が薄い状態で LLM を呼ばない (ハルシネーション防止)。"""
    called = {"n": 0}

    def _f(system, user, **kw):
        called["n"] += 1
        return "{}"
    mod.call_llm = _f
    assert mod.extract_with_llm("t", "短い") is None
    assert called["n"] == 0, called


def test_extract_sends_title_and_body():
    seen = _stub(json.dumps({"summary": "x", "event_date": None,
                             "event_end_date": None, "date_evidence": None,
                             "status": "normal"}))
    mod.extract_with_llm("タイトルです", "本文です" * 20)
    assert "タイトルです" in seen["user"], seen["user"]
    assert "本文です" in seen["user"], seen["user"]
    assert seen["kw"]["model"] == mod.LLM_MODEL
    assert seen["kw"]["temperature"] == 0


def test_html_to_text_opens_circled_weekday():
    got = mod.html_to_text("<p>飯能河原6/27㈯・28㈰の営業について</p>")
    assert "(土)" in got and "(日)" in got, got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-extract tests passed")
