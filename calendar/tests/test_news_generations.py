#!/usr/bin/env python3
"""告知エントリの世代リンクのユニットテスト。
実行: python3 calendar/tests/test_news_generations.py
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

ITEM = {
    "id": 303,
    "url": "https://hanno-tourism.jp/news/sakura-week/",
    "title": "飯能さくらウィーク開催",
    "body_html": "<p>期間:令和8年3月28日(土)〜4月5日(日)の9日間。中央公園で開催します。"
                 "キッチンカー等が出店し飲食の提供もあります。雨天決行・荒天中止。</p>",
    "date_gmt": "2026-02-25T00:00:00",
    "modified_gmt": "2026-02-25T00:00:00",
    "tags": [6],
}
EX = {"summary": "さくらウィークが開催されます。", "event_date": "2026-03-28",
      "event_end_date": "2026-04-05", "date_evidence": "令和8年3月28日(土)",
      "status": "normal"}


def _stub_llm(payload):
    mod.call_llm = lambda system, user, **kw: json.dumps(payload,
                                                         ensure_ascii=False)


def _names(d):
    return sorted(os.path.basename(p)
                  for p in glob.glob(os.path.join(d, "**", "*.yaml"),
                                     recursive=True))


def test_status_header_new():
    got = mod.notice_status_header("2026-02-25", None)
    assert got.startswith("🆕"), got
    assert "2026-02-25" in got, got


def test_status_header_update_mentions_previous():
    got = mod.notice_status_header("2026-02-25", "2026-02-20")
    assert got.startswith("🔄"), got
    assert "2026-02-20" in got, got


def test_existing_generations_sorts_newest_first():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "2026"))
        for dtstart, h in (("2026-02-25", "aaaaaa"), ("2026-02-20", "bbbbbb")):
            p = os.path.join(d, "2026", f"{dtstart[5:]}_tourism-news-303-{h}.yaml")
            with open(p, "w", encoding="utf-8") as f:
                f.write(f'uid: "tourism-news-303-{h}@hanno.city.tecoli.com"\n'
                        f'dtstart: "{dtstart}"\n'
                        f'  content_hash: "sha256-{h}0000000000"\n')
        idx = mod.existing_notice_generations(d, "tourism-news")
        gens = idx["303"]
        assert gens[0][0] == "2026-02-25", gens
        assert len(gens) == 2, gens


def test_existing_generations_ignores_event_entries():
    """本番エントリ (-event) を世代として数えない。"""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "2026"))
        p = os.path.join(d, "2026", "03-28_tourism-news-303-event.yaml")
        with open(p, "w", encoding="utf-8") as f:
            f.write('uid: "tourism-news-303-event@hanno.city.tecoli.com"\n'
                    'dtstart: "2026-03-28"\n'
                    '  content_hash: "sha256-cccccc0000000000"\n')
        idx = mod.existing_notice_generations(d, "tourism-news")
        assert idx.get("303") in (None, []), idx


def test_second_run_with_same_content_creates_no_new_generation():
    _stub_llm(EX)
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([ITEM], d, False, {})
        first = _names(d)
        mod.process_news([ITEM], d, False, {})
        assert _names(d) == first, (first, _names(d))


def test_updated_content_creates_new_generation_and_keeps_old():
    _stub_llm(EX)
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([ITEM], d, False, {})
        before = _names(d)
        updated = dict(ITEM,
                       body_html="<p>【3/1更新】内容が変わりました。"
                                 "期間:令和8年3月28日(土)〜4月5日(日)の9日間。</p>",
                       modified_gmt="2026-03-01T00:00:00")
        mod.process_news([updated], d, False, {})
        after = _names(d)
        assert len(after) > len(before), (before, after)
        # 前世代が残っている
        for name in before:
            assert name in after, (name, after)


def test_new_generation_records_supersedes():
    _stub_llm(EX)
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([ITEM], d, False, {})
        old_uid = mod.notice_uid("tourism-news", 303, mod.content_hash_of(ITEM))
        updated = dict(ITEM,
                       body_html="<p>【3/1更新】内容が変わりました。"
                                 "期間:令和8年3月28日(土)〜4月5日(日)の9日間。</p>")
        mod.process_news([updated], d, False, {})
        new_uid = mod.notice_uid("tourism-news", 303, mod.content_hash_of(updated))
        new_path = [p for p in glob.glob(os.path.join(d, "**", "*.yaml"),
                                         recursive=True)
                    if new_uid.split("@")[0] in os.path.basename(p)]
        assert new_path, _names(d)
        with open(new_path[0], encoding="utf-8") as f:
            doc = f.read()
        assert "supersedes:" in doc, doc
        assert old_uid in doc, doc
        assert "🔄" in doc, doc


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-generation tests passed")
