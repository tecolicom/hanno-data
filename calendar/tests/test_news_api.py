#!/usr/bin/env python3
"""cal-tourism-news-fetch の REST API 取得のユニットテスト。
fetch_json を差し替えるのでネットワーク非依存。
実行: python3 calendar/tests/test_news_api.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def _post(pid, date_gmt, modified_gmt=None, tags=(6,), title="タイトル",
          body="<p>本文</p>"):
    """API が返す news 投稿 1 件を模した dict。"""
    return {
        "id": pid,
        "link": f"https://hanno-tourism.jp/news/post-{pid}/",
        "slug": f"post-{pid}",
        "date_gmt": date_gmt,
        "modified_gmt": modified_gmt or date_gmt,
        "title": {"rendered": title},
        "content": {"rendered": body},
        "tag-news": list(tags),
    }


def _stub_pages(pages):
    """fetch_json を差し替え、page 番号ごとに固定リストを返す。

    `&page=` で切ること。`page=` だと `per_page=` に先に当たる。
    """
    def _f(url):
        n = 1
        if "&page=" in url:
            n = int(url.split("&page=")[1].split("&")[0])
        return pages[n - 1] if n <= len(pages) else []
    mod.fetch_json = _f


def test_fetch_news_index_maps_fields():
    _stub_pages([[_post(101, "2026-08-07T06:18:16", tags=(6,),
                        title="8月8日(土) 盆踊りへ", body="<p>日時:2026年8月8日(土)</p>")]])
    got = mod.fetch_news_index(months=6, today=date(2026, 8, 10))
    assert len(got) == 1, got
    it = got[0]
    assert it["id"] == 101
    assert it["url"] == "https://hanno-tourism.jp/news/post-101/"
    assert it["title"] == "8月8日(土) 盆踊りへ"
    assert it["body_html"] == "<p>日時:2026年8月8日(土)</p>"
    assert it["date_gmt"] == "2026-08-07T06:18:16"
    assert it["tags"] == [6]


def test_fetch_news_index_drops_old_articles():
    _stub_pages([[
        _post(1, "2026-08-01T00:00:00"),
        _post(2, "2025-01-01T00:00:00"),   # 6 ヶ月より古い
    ]])
    got = mod.fetch_news_index(months=6, today=date(2026, 8, 10))
    assert [it["id"] for it in got] == [1], got


def test_fetch_news_index_follows_paging():
    _stub_pages([
        [_post(i, "2026-08-01T00:00:00") for i in range(1, 101)],
        [_post(101, "2026-08-02T00:00:00")],
    ])
    got = mod.fetch_news_index(months=6, today=date(2026, 8, 10))
    assert len(got) == 101, len(got)


def test_fetch_news_index_handles_missing_tags():
    # 実測でタグ無しの記事が 2 件ある
    p = _post(5, "2026-08-01T00:00:00")
    del p["tag-news"]
    _stub_pages([[p]])
    got = mod.fetch_news_index(months=6, today=date(2026, 8, 10))
    assert got[0]["tags"] == [], got


def test_select_news_to_fetch_skips_unchanged():
    items = [
        {"url": "https://hanno-tourism.jp/news/a/", "modified_gmt": "2026-08-01T00:00:00"},
        {"url": "https://hanno-tourism.jp/news/b/", "modified_gmt": "2026-08-02T00:00:00"},
    ]
    cache = {"https://hanno-tourism.jp/news/a/": {"modified_gmt": "2026-08-01T00:00:00"}}
    todo, unchanged = mod.select_news_to_fetch(items, cache)
    assert [it["url"] for it in todo] == ["https://hanno-tourism.jp/news/b/"], todo
    assert unchanged == 1


def test_select_news_to_fetch_treats_unknown_as_todo():
    items = [{"url": "https://hanno-tourism.jp/news/x/", "modified_gmt": "2026-08-01T00:00:00"}]
    todo, unchanged = mod.select_news_to_fetch(items, {})
    assert len(todo) == 1 and unchanged == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-api tests passed")
