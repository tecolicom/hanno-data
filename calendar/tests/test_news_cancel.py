#!/usr/bin/env python3
"""中止・延期の追記が既存の本番エントリに反映されるかのテスト。
実行: python3 calendar/tests/test_news_cancel.py
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

# 実データ: 名栗ほたる祭り。6/11 告知 → 6/26 に冒頭へ中止が追記された。
HOTARU = {
    "id": 202,
    "url": "https://hanno-tourism.jp/news/naguri-hotaru/",
    "title": "名栗ほたる祭り",
    "body_html": "<p>【6/26更新】台風接近に伴い中止が決定しました。 ノーラ名栗にて"
                 "今年も「名栗ほたる祭り」を開催! 日時:2026年6月27日(土) "
                 "午後5時〜午後8時30分(雨天決行) 会場:ノーラ名栗</p>",
    "date_gmt": "2026-06-11T00:00:00",
    "modified_gmt": "2026-06-26T09:00:00",
    "tags": [6],
}


def _stub_llm(payload):
    mod.call_llm = lambda system, user, **kw: json.dumps(payload,
                                                         ensure_ascii=False)


def test_existing_event_gets_canceled_mark():
    _stub_llm({"summary": "台風接近に伴い中止が決定しました。",
               "event_date": "2026-06-27", "event_end_date": None,
               "date_evidence": "日時:2026年6月27日(土)", "status": "canceled"})
    with tempfile.TemporaryDirectory() as d:
        # 前回の実行で本番が既にある状態を作る
        os.makedirs(os.path.join(d, "2026"))
        prev = os.path.join(d, "2026", "06-27_tourism-news-202-event.yaml")
        with open(prev, "w", encoding="utf-8") as f:
            f.write('uid: "tourism-news-202-event@hanno.city.tecoli.com"\n'
                    'summary: "🎪 名栗ほたる祭り"\n'
                    f'url: "{HOTARU["url"]}"\n'
                    'dtstart: "2026-06-27"\n'
                    'dtend: "2026-06-27"\n'
                    "source:\n"
                    f"  type: {mod.SOURCE_TYPE}\n")
        r = mod.process_news([HOTARU], d, False, {})
        assert r["event"] == 1, r
        with open(prev, encoding="utf-8") as f:
            doc = f.read()
        assert "【中止】" in doc, doc
        assert 'dtstart: "2026-06-27"' in doc, doc


def test_born_canceled_creates_notice_only():
    """中止として生まれた記事 (既存本番なし) は本番を作らない。"""
    _stub_llm({"summary": "中止のお知らせ", "event_date": "2026-06-27",
               "event_end_date": None,
               "date_evidence": "日時:2026年6月27日(土)", "status": "canceled"})
    with tempfile.TemporaryDirectory() as d:
        r = mod.process_news([HOTARU], d, False, {})
        assert r["event"] == 0, r
        names = sorted(os.path.basename(p) for p in
                       glob.glob(os.path.join(d, "**", "*.yaml"), recursive=True))
        h6 = mod.content_hash_of(HOTARU)[:6]
        assert names == [f"06-11_tourism-news-202-{h6}.yaml"], names


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-cancel tests passed")
