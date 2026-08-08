#!/usr/bin/env python3
"""cal-tourism-fetch の REST API 取得のユニットテスト。fetch_json を差し替えるので
ネットワーク非依存。
実行: python3 calendar/tests/test_tourism_api.py
"""
import importlib.machinery
import importlib.util
import os
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def _post(slug, modified_gmt="2026-08-07T01:00:51", months=(61,), link=None):
    """API が返す tour 投稿 1 件を模した dict。"""
    return {
        "id": abs(hash(slug)) % 10000,
        "link": link or f"https://hanno-tourism.jp/hanno-eco/tour/{slug}",
        "slug": slug,
        "modified_gmt": modified_gmt,
        "tour-month": list(months),
    }


class _FakeBody:
    """HTTPError の fp として渡す read() 可能なオブジェクト。

    HTTPError は後始末で fp.close() を呼ぶので close() も生やしておく
    (無いとインタプリタ終了時に AttributeError がノイズとして出る)。
    """

    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def close(self):
        pass


class FakeJson:
    """pages: [[post, ...], ...] を page=1,2,... の順に返す fetch_json のフェイク。

    ページ数を超えた要求には HTTP 400 (rest_post_invalid_page_number) を投げる
    (実サーバの挙動を再現)。
    """

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        # url 末尾の page=N を読む
        page = 1
        for part in url.split("?", 1)[-1].split("&"):
            if part.startswith("page="):
                page = int(part[len("page="):])
        if page > len(self.pages):
            raise urllib.error.HTTPError(
                url, 400, "Bad Request", {},
                _FakeBody(b'{"code":"rest_post_invalid_page_number"}'))
        return self.pages[page - 1]


def test_returns_url_slug_modified():
    mod.fetch_json = FakeJson([[_post("ec-a"), _post("ec-b", "2026-01-02T03:04:05")]])
    got = mod.fetch_tour_index()
    assert got == [
        {"url": "https://hanno-tourism.jp/hanno-eco/tour/ec-a/",
         "slug": "ec-a", "modified_gmt": "2026-08-07T01:00:51"},
        {"url": "https://hanno-tourism.jp/hanno-eco/tour/ec-b/",
         "slug": "ec-b", "modified_gmt": "2026-01-02T03:04:05"},
    ], got


def test_excludes_posts_without_tour_month():
    """tour-month が空 = 一覧ページに載らない = 現在提供していない (編集意図)。"""
    mod.fetch_json = FakeJson([[
        _post("ec-current", months=(61, 62)),
        _post("ec-retired", months=()),
    ]])
    got = mod.fetch_tour_index()
    assert [t["slug"] for t in got] == ["ec-current"], got


def test_excludes_urls_outside_allowlist():
    mod.fetch_json = FakeJson([[
        _post("ec-ok"),
        _post("bad", link="https://evil.example.com/hanno-eco/tour/bad"),
        _post("BAD-SLUG", link="https://hanno-tourism.jp/hanno-eco/tour/BAD_SLUG"),
    ]])
    got = mod.fetch_tour_index()
    assert [t["slug"] for t in got] == ["ec-ok"], got


def test_single_page_makes_one_request():
    fake = FakeJson([[_post("ec-a")]])
    mod.fetch_json = fake
    mod.fetch_tour_index()
    assert len(fake.calls) == 1, fake.calls
    assert "page=1" in fake.calls[0]
    assert f"per_page={mod.TOUR_API_PER_PAGE}" in fake.calls[0]


def test_follows_all_pages():
    """1 ページ目が per_page ぴったりなら次を要求し、足りなくなったら終わる。"""
    per = mod.TOUR_API_PER_PAGE
    page1 = [_post(f"ec-p1-{i}") for i in range(per)]
    page2 = [_post(f"ec-p2-{i}") for i in range(3)]
    fake = FakeJson([page1, page2])
    mod.fetch_json = fake
    got = mod.fetch_tour_index()
    assert len(got) == per + 3
    assert len(fake.calls) == 2, fake.calls
    assert "page=2" in fake.calls[1]


def test_treats_http_400_invalid_page_as_end():
    """総件数が per_page の倍数のとき 1 ページ余分に要求してしまう。
    実サーバは HTTP 400 rest_post_invalid_page_number を返すので終端扱いにする。"""
    per = mod.TOUR_API_PER_PAGE
    page1 = [_post(f"ec-{i}") for i in range(per)]
    fake = FakeJson([page1])          # page=2 は 400 を投げる
    mod.fetch_json = fake
    got = mod.fetch_tour_index()      # 例外を投げずに page1 分を返すこと
    assert len(got) == per
    assert len(fake.calls) == 2, fake.calls


def test_reraises_other_http_errors():
    """400 invalid_page 以外のエラーは伝播させる (静かに空を返さない)。"""
    def boom(url):
        raise urllib.error.HTTPError(url, 500, "Server Error", {},
                                     _FakeBody(b"oops"))
    mod.fetch_json = boom
    try:
        mod.fetch_tour_index()
    except urllib.error.HTTPError as e:
        assert e.code == 500
    else:
        raise AssertionError("HTTPError 500 should propagate")


def test_empty_result():
    mod.fetch_json = FakeJson([[]])
    assert mod.fetch_tour_index() == []


def test_check_tour_count_passes_when_enough():
    # 例外が出ないこと自体が検証
    mod.check_tour_count(39, 20)
    mod.check_tour_count(20, 20)


def test_check_tour_count_exits_2_when_too_few():
    for n in (19, 1, 0):
        try:
            mod.check_tour_count(n, 20)
        except SystemExit as e:
            assert e.code == 2, f"n={n}: exit code should be 2, got {e.code}"
        else:
            raise AssertionError(f"n={n}: should have exited")


def test_min_sessions_flag_is_gone():
    """--min-sessions は意味が変わったので廃止した (同名で残すと誤解を招く)。"""
    src = open(SCRIPT, encoding="utf-8").read()
    assert "--min-sessions" not in src
    assert "min_sessions" not in src


def _tour(slug, modified_gmt="2026-08-07T01:00:51"):
    return {"url": f"https://hanno-tourism.jp/hanno-eco/tour/{slug}/",
            "slug": slug, "modified_gmt": modified_gmt}


def test_select_skips_when_modified_matches():
    tours = [_tour("ec-a", "2026-08-07T01:00:51"), _tour("ec-b", "2026-08-07T02:00:00")]
    cache = {tours[0]["url"]: {"modified_gmt": "2026-08-07T01:00:51"}}
    todo, unchanged = mod.select_tours_to_fetch(tours, cache)
    assert [t["slug"] for t in todo] == ["ec-b"], todo
    assert unchanged == 1


def test_select_fetches_when_modified_differs():
    tours = [_tour("ec-a", "2026-08-08T09:00:00")]
    cache = {tours[0]["url"]: {"modified_gmt": "2026-08-07T01:00:51"}}
    todo, unchanged = mod.select_tours_to_fetch(tours, cache)
    assert [t["slug"] for t in todo] == ["ec-a"]
    assert unchanged == 0


def test_select_fetches_when_not_in_cache():
    tours = [_tour("ec-new")]
    todo, unchanged = mod.select_tours_to_fetch(tours, {})
    assert [t["slug"] for t in todo] == ["ec-new"]
    assert unchanged == 0


def test_select_fetches_when_api_modified_is_empty():
    """API が modified_gmt を返さなかった場合は判定材料が無いので必ず取得する。"""
    tours = [_tour("ec-a", "")]
    cache = {tours[0]["url"]: {"modified_gmt": ""}}
    todo, unchanged = mod.select_tours_to_fetch(tours, cache)
    assert [t["slug"] for t in todo] == ["ec-a"]
    assert unchanged == 0


def test_select_preserves_other_cache_fields():
    """etag / last_modified を持つ既存エントリを壊さない。"""
    tours = [_tour("ec-a", "2026-08-07T01:00:51")]
    cache = {tours[0]["url"]: {"etag": 'W/"abc"', "last_modified": "Wed, 01 Jan 2026 00:00:00 GMT"}}
    todo, unchanged = mod.select_tours_to_fetch(tours, cache)
    assert [t["slug"] for t in todo] == ["ec-a"]      # modified_gmt が無いので取得
    assert cache[tours[0]["url"]]["etag"] == 'W/"abc"'


def test_process_tours_records_modified_on_success():
    tours = [_tour("ec-a", "2026-08-08T09:00:00")]
    cache = {}
    mod.process_one = lambda url, out_dir, uid_prefix, dry_run: 3
    got = mod.process_tours(tours, "/tmp/x", "tourism", True, cache)
    assert got["ok"] == 1 and got["sessions"] == 3 and got["err"] == 0, got
    assert cache[tours[0]["url"]]["modified_gmt"] == "2026-08-08T09:00:00"


def test_process_tours_does_not_record_on_exception():
    """失敗したツアーは記録しない → 次回リトライされる。"""
    tours = [_tour("ec-bad", "2026-08-08T09:00:00")]
    cache = {}

    def boom(url, out_dir, uid_prefix, dry_run):
        raise RuntimeError("fetch failed")

    mod.process_one = boom
    got = mod.process_tours(tours, "/tmp/x", "tourism", True, cache)
    assert got["err"] == 1 and got["ok"] == 0, got
    assert tours[0]["url"] not in cache, cache


def test_process_tours_records_zero_session_but_counts_it():
    """0 セッション (パース失敗の疑い) は記録するが zero_session に計上する。

    記録するのは、同じ内容を毎日取り直しても結果が変わらないため。構造変化の
    検知は zero_session のカウントで行う。
    """
    tours = [_tour("ec-zero", "2026-08-08T09:00:00")]
    cache = {}
    mod.process_one = lambda url, out_dir, uid_prefix, dry_run: 0
    got = mod.process_tours(tours, "/tmp/x", "tourism", True, cache)
    assert got["zero_session"] == 1 and got["ok"] == 0, got
    assert cache[tours[0]["url"]]["modified_gmt"] == "2026-08-08T09:00:00"


def test_process_tours_keeps_existing_cache_fields():
    tours = [_tour("ec-a", "2026-08-08T09:00:00")]
    cache = {tours[0]["url"]: {"etag": 'W/"abc"'}}
    mod.process_one = lambda url, out_dir, uid_prefix, dry_run: 1
    mod.process_tours(tours, "/tmp/x", "tourism", True, cache)
    assert cache[tours[0]["url"]]["etag"] == 'W/"abc"'
    assert cache[tours[0]["url"]]["modified_gmt"] == "2026-08-08T09:00:00"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all tourism-api tests passed")
