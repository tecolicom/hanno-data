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


def _seed_event(d, post_id, dtstart, url):
    os.makedirs(os.path.join(d, dtstart[:4]), exist_ok=True)
    p = os.path.join(d, dtstart[:4],
                     f"{dtstart[5:]}_tourism-news-{post_id}-event.yaml")
    with open(p, "w", encoding="utf-8") as f:
        f.write(f'uid: "tourism-news-{post_id}-event@hanno.city.tecoli.com"\n'
                f'summary: "🎪 前世代"\n'
                f'url: "{url}"\n'
                f'dtstart: "{dtstart}"\n'
                f'dtend: "{dtstart}"\n'
                "source:\n"
                f"  type: {mod.SOURCE_TYPE}\n")
    return p


def test_stale_event_removed_when_judged_not_announcement():
    """判定が false に変わったら、既に作った本番を取り下げる。

    消さないと「協賛のお願い」等が当日欄に残り続ける (実測: 11/7 の
    飯能まつり協賛エントリが判定導入後も残った)。
    """
    _stub_llm({"summary": "協賛金を募集しています。", "event_date": "2026-06-27",
               "event_end_date": None, "date_evidence": "日時:2026年6月27日(土)",
               "status": "normal", "announces_event_itself": False})
    with tempfile.TemporaryDirectory() as d:
        prev = _seed_event(d, 202, "2026-06-27", HOTARU["url"])
        r = mod.process_news([HOTARU], d, False, {})
        assert not os.path.exists(prev), "本番が残っている"
        assert r["removed_event"] == 1, r


def test_stale_event_kept_when_extraction_merely_failed():
    """日付が取れなかっただけでは消さない。

    LLM の揺れで一時的に no-date になることがあり、それで消すと正しい
    イベントが失われる。
    """
    _stub_llm({"summary": "s", "event_date": None, "event_end_date": None,
               "date_evidence": None, "status": "normal"})
    with tempfile.TemporaryDirectory() as d:
        prev = _seed_event(d, 202, "2026-06-27", HOTARU["url"])
        r = mod.process_news([HOTARU], d, False, {})
        assert os.path.exists(prev), "消してはいけない"
        assert r["removed_event"] == 0, r


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-cancel tests passed")
