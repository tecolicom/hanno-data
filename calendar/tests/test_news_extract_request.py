#!/usr/bin/env python3
"""cal-tourism-news-fetch の抽出リクエストのユニットテスト。
call_llm を差し替えるのでネットワーク非依存。
実行: python3 calendar/tests/test_news_extract_request.py

なぜ要るか: date_evidence は「本文から一字一句コピー」させる項目なので、
原文に 「」 や " があると、エスケープされない " が JSON 文字列に混ざって
json.loads が落ちうる。同じ形の事故が 2026-08-22 に cal-translate-en で
起きている (CI run 32590407302)。応答形式をサーバ側に強制させて塞ぐ。
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

_REPLY = json.dumps({
    "summary": "はんのう昭和盆踊り",
    "event_date": "2026-08-08",
    "event_end_date": None,
    "date_evidence": "8月8日(土)",
    "status": "normal",
    "announces_event_itself": True,
}, ensure_ascii=False)

_BODY = "8月8日(土) はんのう昭和盆踊りへ♪ 日時:2026年8月8日(土) 午後6時〜" * 2


def _stub_call_llm(reply=_REPLY):
    calls = []

    def _call_llm(system, user, **kw):
        calls.append(kw)
        return reply

    mod.call_llm = _call_llm
    return calls


def test_extract_passes_output_schema():
    calls = _stub_call_llm()
    got = mod.extract_with_llm("はんのう昭和盆踊り", _BODY, "2026-08-01")
    assert got is not None, got
    assert calls[0].get("output_schema") is mod.EXTRACT_OUTPUT_SCHEMA, calls[0]


def test_output_schema_matches_the_fields_the_parser_reads():
    """スキーマとプロンプトの JSON 例がずれると、片方だけ直して静かに壊れる。"""
    schema = mod.EXTRACT_OUTPUT_SCHEMA
    expected = {"summary", "event_date", "event_end_date", "date_evidence",
                "status", "announces_event_itself"}
    assert set(schema["properties"]) == expected, schema
    assert set(schema["required"]) == expected, schema
    assert schema["additionalProperties"] is False, schema
    # status の候補はパーサ側の _VALID_STATUS と一致していること
    assert set(schema["properties"]["status"]["enum"]) == set(mod._VALID_STATUS), \
        (schema["properties"]["status"], mod._VALID_STATUS)
    # プロンプトにも同じキーが載っていること (人が読む側とのずれ防止)
    for key in expected:
        assert f'"{key}"' in mod.EXTRACT_SYSTEM_PROMPT, key


def test_extract_returns_none_on_broken_json():
    """スキーマ強制後も壊れた JSON なら None (呼出側が llm_fail を数える)。"""
    _stub_call_llm('{"summary": "a "b"", "event_date": null}')
    assert mod.extract_with_llm("t", _BODY, "2026-08-01") is None


def test_extract_skips_llm_for_thin_body():
    calls = _stub_call_llm()
    assert mod.extract_with_llm("t", "短い", "2026-08-01") is None
    assert calls == [], calls


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news extract request tests passed")
