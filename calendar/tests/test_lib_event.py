#!/usr/bin/env python3
"""cal-lib-event-fetch の HTML 解析のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_lib_event.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-lib-event-fetch")
loader = importlib.machinery.SourceFileLoader("cal_lib_event_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_lib_event_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

_EVENTS_HTML = """<html><body>
<div class="contents"><div class="wrap">
<article>
<h1>2026月8月22日のイベント（子ども図書館）</h1>
<div class="txtbox"><ul>
<li><a href='https://www.hanno-lib.jp/calendar/822.html'>夜のおはなし会（8月22日）</a></li>
<li><a href='https://www.hanno-lib.jp/calendar/88128911151622232930.html'>8月のおはなしのじかん(8月1・2日）</a></li>
</ul></div>
</article>
</div></div>
<footer><a href="/sitemap.html">サイトマップ</a></footer>
</body></html>"""

_DETAIL_HTML = """<html><body>
<article>
<h1>夜のおはなし会（8月22日）</h1>
<div class="txtbox">
<p>8月のおはなし会は、いつもとちがい、夜に開催します。</p>
<h2>日時</h2>
<p>令和8年8月22日(土)</p>
<p>　19:00～19:45</p>
<p><img alt="s-おはなし会.jpg" src="/calendar/images/de3a.jpg" width="449"></p>
</div>
</article>
<footer><p>Copyright</p></footer>
</body></html>"""


def test_parse_events_page_returns_links_in_the_article_only():
    got = mod.parse_events_page(_EVENTS_HTML)
    assert got == [
        ("https://www.hanno-lib.jp/calendar/822.html", "夜のおはなし会（8月22日）"),
        ("https://www.hanno-lib.jp/calendar/88128911151622232930.html",
         "8月のおはなしのじかん(8月1・2日）"),
    ], got


def test_parse_events_page_ignores_footer_links():
    """<article> の外は拾わない。サイトマップまでイベントにしない。"""
    got = mod.parse_events_page(_EVENTS_HTML)
    assert all("sitemap" not in u for u, _ in got), got


def test_parse_events_page_raises_without_article():
    """ページ構造の変化を静かに握り潰さない。"""
    try:
        mod.parse_events_page("<html><body>なにもない</body></html>")
    except ValueError:
        return
    raise AssertionError("article が無いのに ValueError が飛ばない")


def test_parse_events_page_empty_article_is_not_an_error():
    """イベントが 0 件の日は普通にある。"""
    assert mod.parse_events_page(
        "<article><h1>x</h1><div class='txtbox'></div></article>") == []


def test_parse_detail_extracts_heading_and_body():
    title, body = mod.parse_detail(_DETAIL_HTML)
    assert title == "夜のおはなし会（8月22日）", title
    assert "夜に開催します" in body, body
    assert "19:00" in body, body


def test_parse_detail_drops_images_and_heading():
    _title, body = mod.parse_detail(_DETAIL_HTML)
    assert "images" not in body, body
    assert "s-おはなし会.jpg" not in body, body
    assert not body.startswith("夜のおはなし会"), body


def test_page_name():
    assert mod.page_name("https://www.hanno-lib.jp/calendar/822.html") == "822"
    assert mod.page_name("https://www.hanno-lib.jp/calendar/post-84.html") == "post-84"


def test_content_hash_is_stable_and_date_sensitive():
    a = mod.content_hash_for("t", "b", "2026-08-22")
    assert a == mod.content_hash_for("t", "b", "2026-08-22")
    assert a != mod.content_hash_for("t", "b", "2026-08-23")
    assert a != mod.content_hash_for("t", "b2", "2026-08-22")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all lib-event tests passed")
