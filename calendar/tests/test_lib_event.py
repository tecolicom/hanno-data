#!/usr/bin/env python3
"""cal-lib-event-fetch の HTML 解析のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_lib_event.py
"""
from __future__ import annotations
import contextlib
import glob
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin")
SCRIPT = os.path.join(BIN, "cal-lib-event-fetch")
loader = importlib.machinery.SourceFileLoader("cal_lib_event_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_lib_event_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

sys.path.insert(0, BIN)
import _hanno_lib  # noqa: E402

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


def test_content_hash_for_returns_bare_digest_not_prefixed():
    """Ruling 11: existing_content_hash_matches は "sha256-" を剥がした 16 桁を
    比較対象にする (_lib.py の正規表現 `sha256-([0-9a-f]+)` の group(1))。
    content_hash_for が "sha256-" を前置したまま返すと比較が永久に不一致になり、
    skip 経路が一度も発動しない (既存クローラ 4 本と規約が食い違っていた)。
    """
    h = mod.content_hash_for("t", "b", "2026-08-22")
    assert not h.startswith("sha256-"), h
    assert re.fullmatch(r"[0-9a-f]{16}", h), h


def _fixture_manifest_and_reader():
    fixdir = os.path.join(HERE, "fixtures", "cal-lib-event-fetch")
    with open(os.path.join(fixdir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    def _read(fname):
        with open(os.path.join(fixdir, fname), encoding="utf-8") as f:
            return f.read()

    return manifest, _read


def _install_real_fixture_stubs():
    """run-golden の _setup_lib_event 相当をこのテストファイルから直接行う.

    fetch_with_cache は常に fixture の本文を返す (= 常に 200 相当。条件付き GET
    の 304 分岐はここでは検証しない、実データ規模で検証するのが目的)。

    戻り値は差し替え前の値の辞書。呼出側は必ず try/finally で
    `_restore_stubs(orig)` を呼ぶこと (Ruling 6 と同じ理由: 差し替えたまま
    戻さないと、後続のテストに漏れて原因の分かりにくい失敗を生む)。
    """
    manifest, read = _fixture_manifest_and_reader()

    def _fetch_text(url):
        if url not in manifest:
            raise RuntimeError(f"fixture 外の URL: {url}")
        return read(manifest[url])

    orig = {
        "_hanno_lib.fetch_text": _hanno_lib.fetch_text,
        "mod.fetch_with_cache": mod.fetch_with_cache,
        "mod.load_http_cache": mod.load_http_cache,
        "mod.save_http_cache": mod.save_http_cache,
        "mod.llm_available": mod.llm_available,
    }
    _hanno_lib.fetch_text = _fetch_text
    mod.fetch_with_cache = lambda url, etag, lm: (
        (read(manifest[url]), None, None) if url in manifest else (None, None, None))
    mod.load_http_cache = lambda: {}
    mod.save_http_cache = lambda c: None
    mod.llm_available = lambda: False
    return orig


def _restore_stubs(orig):
    _hanno_lib.fetch_text = orig["_hanno_lib.fetch_text"]
    mod.fetch_with_cache = orig["mod.fetch_with_cache"]
    mod.load_http_cache = orig["mod.load_http_cache"]
    mod.save_http_cache = orig["mod.save_http_cache"]
    mod.llm_available = orig["mod.llm_available"]


def _run_main_capture_stderr(argv):
    buf = io.StringIO()
    saved_argv = sys.argv
    sys.argv = argv
    try:
        with contextlib.redirect_stderr(buf):
            mod.main()
    finally:
        sys.argv = saved_argv
    return buf.getvalue()


def test_main_skips_unchanged_articles_on_rerun():
    """Ruling 11 の回帰網: 同じ out-dir に main() を複数回走らせても、
    2 回目以降は skip されること。

    content_hash_for が "sha256-" を前置したまま返すバグがあると、
    existing_content_hash_matches が常に不一致と判定し、内容が同じでも
    毎回 written が全件になる (skipped=0 のまま)。実データ規模の fixture を
    使って実際に 2 回 main() を走らせ、2 回目が written=0 / skipped=written1
    になることを確認する。
    """
    orig = _install_real_fixture_stubs()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            argv = ["cal-lib-event-fetch", "--out-dir", out_dir, "--today", "2026-08-24"]
            out1 = _run_main_capture_stderr(argv)
            out2 = _run_main_capture_stderr(argv)
    finally:
        _restore_stubs(orig)

    m1 = re.search(r"written=(\d+) skipped=(\d+)", out1)
    m2 = re.search(r"written=(\d+) skipped=(\d+)", out2)
    assert m1 and m2, (out1, out2)
    written1 = int(m1.group(1))
    assert written1 > 0, out1
    assert int(m2.group(1)) == 0, out2
    assert int(m2.group(2)) == written1, out2


def test_main_updates_all_days_for_multi_day_article_after_content_change():
    """Ruling 12 の回帰網 (Ruling 2 が作った穴): 1 記事が複数日に出るとき、
    記事本文が更新されたら同一実行内の全ての日が新しい本文に揃うこと。

    304 短絡 (Ruling 2) は「その日の YAML が既にあれば取り直さない」ので、
    同一実行内で最初に処理した日が 200 で新本文を得ても、http_cache が
    その場で新しい Last-Modified に更新されるため、後続日は 304 を受け取り
    (かつ既存 YAML があるので) 古い本文のまま固定されてしまう —
    メモ化 (detail_cache) が無いと直らない。
    """
    detail_url = "https://www.hanno-lib.jp/calendar/999.html"
    events_html = ("<article><div class='txtbox'><ul>"
                   f"<li><a href='{detail_url}'>複数日イベント</a></li>"
                   "</ul></div></article>")

    def _detail_html(marker):
        return (f"<article><h1>複数日イベント</h1><div class='txtbox'>"
               f"<p>本文 {marker} です。これは十分に長い本文にするための"
               "水増しの文章です。" + ("あ" * 40) + "</p></div></article>")

    days = ["2026-08-01", "2026-08-02", "2026-08-03"]

    def fake_fetch_cal(cal_url, lib_code, term_from, term_to):
        ed = days if lib_code == "02" else []
        return {"libraries": [{"code": lib_code,
                               "term": [{"month": "202608", "event_day": ed}]}]}

    server = {"lm": "LM1", "body": _detail_html("A")}

    def fake_fetch_text(url):
        if "events.php" in url:
            return events_html
        if url == detail_url:
            # 304 だが対象日の YAML がまだ無いときの無条件 GET フォールバック
            # (初回実行では 08-02/08-03 がこの経路を通る: 08-01 が in-memory
            # http_cache を更新済みなので 304 になるが、08-02/08-03 はまだ
            # 書かれていない)。現在のサーバ本文をそのまま返す。
            return server["body"]
        raise AssertionError(f"unexpected fetch_text: {url}")

    def fake_fetch_with_cache(url, etag, lm):
        assert url == detail_url, url
        if lm == server["lm"]:
            return None, etag, lm                       # 304
        return server["body"], None, server["lm"]        # 200

    http_cache_store = {}

    orig_fetch_cal = mod.fetch_cal
    orig_fetch_text = _hanno_lib.fetch_text
    orig_fetch_with_cache = mod.fetch_with_cache
    orig_load = mod.load_http_cache
    orig_save = mod.save_http_cache
    orig_llm = mod.llm_available
    orig_argv = sys.argv
    mod.fetch_cal = fake_fetch_cal
    _hanno_lib.fetch_text = fake_fetch_text
    mod.fetch_with_cache = fake_fetch_with_cache
    mod.load_http_cache = lambda: dict(http_cache_store)
    mod.save_http_cache = lambda c: (http_cache_store.clear(), http_cache_store.update(c))
    mod.llm_available = lambda: False
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            argv = ["cal-lib-event-fetch", "--out-dir", out_dir, "--today", "2026-08-24"]
            sys.argv = argv
            mod.main()

            # 配信元が本文を更新 (Last-Modified も変わる)
            server["lm"] = "LM2"
            server["body"] = _detail_html("B")

            sys.argv = argv
            mod.main()

            for day in days:
                ymd = day.replace("-", "")
                paths = glob.glob(os.path.join(
                    out_dir, "**", f"{day[5:]}_libkids-event-999-{ymd}.yaml"),
                    recursive=True)
                assert paths, f"{day} の YAML が無い: {out_dir}"
                content = open(paths[0], encoding="utf-8").read()
                assert "本文 B" in content, (day, content)
                assert "本文 A" not in content, (day, content)
    finally:
        sys.argv = orig_argv
        mod.fetch_cal = orig_fetch_cal
        _hanno_lib.fetch_text = orig_fetch_text
        mod.fetch_with_cache = orig_fetch_with_cache
        mod.load_http_cache = orig_load
        mod.save_http_cache = orig_save
        mod.llm_available = orig_llm


def test_main_does_not_crash_on_relative_or_fragment_links():
    """Ruling 13: allowlist 判定は try の中で urlparse を使うこと。

    `detail_url.split("/")[2]` は href="#" のような相対 URL / フラグメントで
    IndexError になる。この判定が try の外にあると except (ValueError, OSError)
    を素通りして生の traceback で落ちる (Ruling 10 が塞いだはずの「1 件で
    全体停止」が別の例外型で再発する)。
    """
    events_html = ("<article><div class='txtbox'><ul>"
                   "<li><a href='#'>フラグメントだけ</a></li>"
                   "<li><a href='/other/123.html'>別ディレクトリ</a></li>"
                   "</ul></div></article>")

    def fake_fetch_cal(cal_url, lib_code, term_from, term_to):
        ed = ["2026-08-01"] if lib_code == "02" else []
        return {"libraries": [{"code": lib_code,
                               "term": [{"month": "202608", "event_day": ed}]}]}

    def fake_fetch_text(url):
        if "events.php" in url:
            return events_html
        raise AssertionError(f"unexpected fetch_text: {url}")

    orig_fetch_cal = mod.fetch_cal
    orig_fetch_text = _hanno_lib.fetch_text
    orig_load = mod.load_http_cache
    orig_save = mod.save_http_cache
    orig_argv = sys.argv
    mod.fetch_cal = fake_fetch_cal
    _hanno_lib.fetch_text = fake_fetch_text
    mod.load_http_cache = lambda: {}
    mod.save_http_cache = lambda c: None
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            sys.argv = ["cal-lib-event-fetch", "--out-dir", out_dir, "--today", "2026-08-24"]
            try:
                mod.main()
            except SystemExit as e:
                assert e.code == 2, e.code
            except Exception as e:
                raise AssertionError(
                    f"main() が SystemExit(2) ではなく生の例外で落ちた: "
                    f"{type(e).__name__}: {e}")
            else:
                raise AssertionError("allowlist 外の記事があるのに main() が exit しない")
    finally:
        sys.argv = orig_argv
        mod.fetch_cal = orig_fetch_cal
        _hanno_lib.fetch_text = orig_fetch_text
        mod.load_http_cache = orig_load
        mod.save_http_cache = orig_save


def test_limit_event_days_keeps_future_days_over_past_days():
    """Ruling 15: days は昇順なので単純な [:max] は古い方 (過去) を残してしまう。
    打ち切る前に day >= today を優先して残すこと。
    """
    days = ["2026-08-01", "2026-08-02", "2026-08-03",  # 過去 (today=08-24 基準)
            "2026-09-01", "2026-09-02", "2026-09-03"]  # 未来
    got = mod.limit_event_days(days, "2026-08-24", 4)
    assert got == sorted(got), got
    future = [d for d in got if d >= "2026-08-24"]
    assert future == ["2026-09-01", "2026-09-02", "2026-09-03"], got
    assert len(got) == 4, got


def test_limit_event_days_truncates_future_when_it_alone_exceeds_max():
    days = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]
    got = mod.limit_event_days(days, "2026-08-24", 2)
    # 未来しか無いときは早い方 (直近) を残す
    assert got == ["2026-09-01", "2026-09-02"], got


def test_limit_event_days_noop_when_under_limit():
    days = ["2026-08-01", "2026-09-01"]
    assert mod.limit_event_days(days, "2026-08-24", 60) == days


def test_build_description_url_only_for_short_body():
    desc, method = mod.build_description("title", "短い", "https://x/1")
    assert method == "url-only", method
    assert desc == "https://x/1", desc


def test_build_description_full_for_medium_body():
    body = "本文。" * 20  # MIN_BODY_CHARS 以上、FULL_TEXT_THRESHOLD 以下
    assert mod.MIN_BODY_CHARS < len(body) <= mod.FULL_TEXT_THRESHOLD, len(body)
    desc, method = mod.build_description("title", body, "https://x/2")
    assert method == "full", method
    assert desc == f"{body}\n\nhttps://x/2", desc


def test_build_description_llm_summary_for_long_body():
    """実データの記事本文は 400 字未満が大半だが (post-84 が 369 字と最長)、
    記事が伸びれば LLM 経路に入る。call_llm をスタブして分岐を直接確かめる。
    """
    body = "本文。" * 200  # FULL_TEXT_THRESHOLD を超える
    assert len(body) > mod.FULL_TEXT_THRESHOLD, len(body)
    orig_call_llm = mod.call_llm
    orig_llm_available = mod.llm_available
    mod.llm_available = lambda: True
    mod.call_llm = lambda system, user, **kw: "要約結果"
    try:
        desc, method = mod.build_description("title", body, "https://x/3")
    finally:
        mod.call_llm = orig_call_llm
        mod.llm_available = orig_llm_available
    assert method == "llm-haiku-4-5", method
    assert desc == f"{mod.AI_DISCLAIMER_JP}\n\n要約結果\n\nhttps://x/3", desc


def test_build_description_falls_back_to_full_when_llm_unavailable():
    body = "本文。" * 200
    orig_llm_available = mod.llm_available
    mod.llm_available = lambda: False
    try:
        desc, method = mod.build_description("title", body, "https://x/4")
    finally:
        mod.llm_available = orig_llm_available
    assert method == "full", method
    assert desc == f"{body}\n\nhttps://x/4", desc


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all lib-event tests passed")
