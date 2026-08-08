# cal-tourism-fetch を REST API ベースの更新検知に変える 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** hanno-tourism.jp の 39 ページ全取得 (55 秒) をやめ、WordPress REST API で更新を検知して変更分だけ取得する。

**Architecture:** 一覧ページの HTML スクレイピングを REST API (`/wp-json/wp/v2/tour`) に置き換える。掲載制御は `tour-month` タクソノミーが担っており、空でないもの 39 件が現行のスクレイピング結果と完全一致することを実機確認済み。各ツアーの `modified_gmt` を既存の `.http-cache.json` に保存し、一致するものは HTML を取得しない。日程は ACF 由来で API に無いため、変更分の HTML 取得は残る二段構え。

**Tech Stack:** Python 3 (標準ライブラリのみ)、WordPress REST API v2

**Spec:** `docs/superpowers/specs/2026-08-08-tourism-rest-api-design.md`

## Global Constraints

- **`gws` は無関係。** これは `cal-tourism-fetch` だけの変更で、Calendar API には触らない。
- `maxResults` 相当の「静かな切り捨て」を作らない。ページングは必ず辿る。
- **範囲外ページは HTTP 400** (`{"code":"rest_post_invalid_page_number"}`) を返す。終端として扱い例外を投げない。
- `_lib.fetch()` はボディのみを返しヘッダを取れない。`x-wp-totalpages` は**読めない**前提で設計する。
- API 失敗・JSON パース失敗・`tour-month` あり件数が `--min-tours` 未満 → すべて **exit 2**。スクレイピングへのフォールバックは持たない。
- 処理が成功したツアーだけ `modified_gmt` を保存する。失敗したものは更新しない (次回リトライ)。
- `--url` 指定時は API を引かず `modified_gmt` 判定もしない (手動デバッグ用途)。
- LLM は使わない (このクローラは決定論的パーサ)。
- コメント・docstring は既存コードと同じく日本語。

## 実機で検証済みの前提 (2026-08-08)

| 前提 | 結果 |
|---|---|
| `tour-month` あり = 一覧ページの 39 件と一致 | ✅ 差分ゼロ |
| API 全件 | 40 (`tour-month` なしは `ec-tairakuri-wagashi` の 1 件) |
| `per_page=100` で 1 ページに収まる | ✅ `x-wp-totalpages: 1` |
| `per_page=15&page=1..3` でページング動作 | ✅ 15 / 15 / 10 件 |
| 範囲外ページ (`page=4`) | ✅ HTTP 400 `rest_post_invalid_page_number` |
| 日次の変更件数 | 6 / 40 (8/7 以降) |
| `.http-cache.json` の現状 | 154 URL、すべて `www.city.hanno.lg.jp`、tourism は 0 件 |

## テストの土台

既存の `calendar/tests/test_tourism_discovery.py` と同じローダを使う:

```python
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)  # __name__ != "__main__" なので main() は走らない
```

`mod.fetch_json` を差し替えればネットワークに出ない。

---

### Task 1: REST API からツアー一覧を取得する

**Files:**
- Modify: `calendar/bin/cal-tourism-fetch` (import 追加、Source セクションに定数追加、`normalize_tour_url` の直後に関数追加)
- Create: `calendar/tests/test_tourism_api.py`

**Interfaces:**
- Consumes: `_lib.fetch()`、既存の `normalize_tour_url()` / `url_ok()`
- Produces:
  - `TOUR_API_URL: str` = `"https://hanno-tourism.jp/wp-json/wp/v2/tour"`
  - `TOUR_API_PER_PAGE: int` = `100`
  - `fetch_json(url: str) -> object`
  - `fetch_tour_index() -> list[dict]` — 各要素は `{"url": str, "slug": str, "modified_gmt": str}`。`tour-month` が空の投稿と allowlist 外の URL は除外。順序は API の返却順を保つ。

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_tourism_api.py`:

```python
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


class _FakeBody:
    """HTTPError の fp として渡す read() 可能なオブジェクト。"""

    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all tourism-api tests passed")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_tourism_api.py`
Expected: FAIL — `AttributeError: module 'cal_tourism_fetch' has no attribute 'fetch_tour_index'`

- [ ] **Step 3: import に `urllib.error` を足す**

`calendar/bin/cal-tourism-fetch` の import 部、`import urllib.request` の行を置換:

```python
import urllib.error
import urllib.request
```

- [ ] **Step 4: Source セクションに API の定数を追加**

`calendar/bin/cal-tourism-fetch` の `URL_ALLOWLIST_PATTERN = ...` の行の直後に追加:

```python
# WordPress REST API。掲載制御は tour-month タクソノミー (空 = 一覧ページに載らない
# = 現在提供していない、という編集意図)。一覧ページのスクレイピングと違い HTML 構造に
# 依存せず、更新日時 (modified_gmt) も同時に取れる。
TOUR_API_URL = "https://hanno-tourism.jp/wp-json/wp/v2/tour"
TOUR_API_PER_PAGE = 100
TOUR_API_FIELDS = "id,link,slug,modified_gmt,tour-month"
```

- [ ] **Step 5: `fetch_json()` と `fetch_tour_index()` を実装する**

`calendar/bin/cal-tourism-fetch` の `normalize_tour_url()` 定義の直後に追加:

```python
def fetch_json(url: str) -> object:
    """URL を GET して JSON をパースして返す (_lib.fetch の薄いラッパ).

    HTTP エラー / パース失敗は呼出側に伝播する。
    """
    return json.loads(fetch(url))


def _is_invalid_page_error(e: urllib.error.HTTPError) -> bool:
    """WordPress REST の「ページ範囲外」エラーか判定する.

    per_page の倍数ちょうどの件数だと 1 ページ余分に要求してしまうため、これを
    終端として扱う。実測: page 範囲外は HTTP 400 で
    {"code":"rest_post_invalid_page_number"} を返す。
    """
    if e.code != 400:
        return False
    try:
        body = e.read().decode("utf-8", errors="replace")
    except Exception:
        return False
    return "rest_post_invalid_page_number" in body


def fetch_tour_index() -> list[dict]:
    """REST API から tour 一覧を取得する.

    tour-month が空でない (= 一覧ページに載る = 現在提供中) ものだけ返す。
    要素は {"url": <末尾スラッシュ正規化済み>, "slug": ..., "modified_gmt": ...}。

    ページングは page=1 から順に辿り、取得件数が per_page 未満なら終了する。
    x-wp-totalpages はヘッダなので _lib.fetch() では読めない (ボディのみ返す)。
    """
    out: list[dict] = []
    page = 1
    while True:
        url = (f"{TOUR_API_URL}?_fields={TOUR_API_FIELDS}"
               f"&per_page={TOUR_API_PER_PAGE}&page={page}")
        try:
            items = fetch_json(url)
        except urllib.error.HTTPError as e:
            if page > 1 and _is_invalid_page_error(e):
                break          # 前ページで打ち切り済み = 正常終了
            raise
        if not isinstance(items, list):
            raise ValueError(f"unexpected API response (not a list): {items!r:.200}")
        for it in items:
            if not it.get("tour-month"):
                continue       # 現在提供していない (編集意図)
            u = normalize_tour_url(it.get("link", ""))
            if not url_ok(u):
                print(f"  WARN: URL outside allowlist, skip: {u}", file=sys.stderr)
                continue
            out.append({"url": u, "slug": it.get("slug", ""),
                        "modified_gmt": it.get("modified_gmt", "")})
        if len(items) < TOUR_API_PER_PAGE:
            break
        page += 1
    return out
```

- [ ] **Step 6: テストを実行して通ることを確認**

Run: `python3 calendar/tests/test_tourism_api.py`
Expected: PASS — `OK: all tourism-api tests passed`

- [ ] **Step 7: 実 API に対して 39 件返ることを確認**

Run:
```bash
python3 -c "
import importlib.machinery, importlib.util
l = importlib.machinery.SourceFileLoader('t','calendar/bin/cal-tourism-fetch')
s = importlib.util.spec_from_loader('t', l)
m = importlib.util.module_from_spec(s); l.exec_module(m)
tours = m.fetch_tour_index()
print('件数:', len(tours))
for t in tours[:3]: print(' ', t)
"
```
Expected: `件数: 39`（実データなので前後しうるが 38〜40 の範囲）。各要素に `url` / `slug` / `modified_gmt` が入っていること。

- [ ] **Step 8: Commit**

```bash
git add calendar/bin/cal-tourism-fetch calendar/tests/test_tourism_api.py
git commit -m "feat(tourism): REST API からツアー一覧を取得する関数を追加

WordPress REST API (/wp-json/wp/v2/tour) から tour-month が空でない投稿を
取得する。tour-month は掲載制御に使われており、空でない 39 件が一覧ページの
スクレイピング結果と実機で完全一致した。

ページングは件数 < per_page で終了 + 範囲外ページの HTTP 400
(rest_post_invalid_page_number) を終端として許容の二重。
まだ main() からは呼んでいない。"
```

---

### Task 2: `main()` を API ベースに切り替え、スクレイピングを削除する

この時点では**全件取得を維持する** (skip はまだ入れない)。よって `--min-sessions` の
サニティチェックはそのまま機能し、挙動は現行と同じままになる。

**Files:**
- Modify: `calendar/bin/cal-tourism-fetch` (`discover_tour_urls` / `fetch_index_urls` / `_TOUR_HREF_RE` / `DEFAULT_INDEX_URL` を削除、`main()` の URL 収集を書き換え、`--index-url` 削除、`--no-discover` のヘルプ書き換え)
- Modify: `calendar/tests/test_tourism_discovery.py` (削除した関数のテストを除去)

**Interfaces:**
- Consumes: `fetch_tour_index() -> list[dict]`（Task 1）
- Produces: `main()` が `tours: list[dict]` を組み立てて `process_one(t["url"], ...)` を回す。`--no-discover` は「API を引かず `urls.txt` のみ」の意味になる。

- [ ] **Step 1: 削除される関数のテストを外す**

`calendar/tests/test_tourism_discovery.py` から `SAMPLE_HTML`、
`test_discover_extracts_dedups_and_filters`、`test_discover_empty_on_no_links` を削除し、
`__main__` ブロックの呼び出しからも外す。`test_normalize_adds_trailing_slash` は残す
（API の `link` 正規化に使い続けるため）。

削除後のファイル全体:

```python
#!/usr/bin/env python3
"""cal-tourism-fetch の normalize_tour_url のユニットテスト。
ネットワーク非依存。実行: python3 calendar/tests/test_tourism_discovery.py

ツアー一覧の取得は REST API 化されたので、その検証は test_tourism_api.py にある。
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-fetch")

loader = importlib.machinery.SourceFileLoader("cal_tourism_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)  # __name__ != "__main__" なので main() は走らない


def test_normalize_adds_trailing_slash():
    assert mod.normalize_tour_url(
        "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru"
    ) == "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"
    assert mod.normalize_tour_url(
        "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"
    ) == "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"


if __name__ == "__main__":
    test_normalize_adds_trailing_slash()
    print("OK: all normalize tests passed")
```

- [ ] **Step 2: テストを実行（この時点では通る）**

Run: `python3 calendar/tests/test_tourism_discovery.py`
Expected: PASS — `OK: all normalize tests passed`

- [ ] **Step 3: スクレイピング用のコードを削除する**

`calendar/bin/cal-tourism-fetch` から以下を削除する:

- `_TOUR_HREF_RE`（`# 一覧ページ /hanno-eco/ 内の <a href=...` のコメントごと）
- `discover_tour_urls()` 関数全体
- `DEFAULT_INDEX_URL = "https://hanno-tourism.jp/hanno-eco/"`
- `fetch_index_urls()` 関数全体

- [ ] **Step 4: `main()` の URL 収集を API ベースに書き換える**

`calendar/bin/cal-tourism-fetch` の `main()` 内、argparse の該当行を削除:

```python
    ap.add_argument("--index-url", default=DEFAULT_INDEX_URL,
                    help=f"ツアー一覧ページ (default: {DEFAULT_INDEX_URL})")
```

`--no-discover` のヘルプを置換:

```python
    ap.add_argument("--no-discover", action="store_true",
                    help="REST API を引かず urls-file のみ使う (API 障害時の手動退避用)")
```

URL 収集ブロック全体（`urls: list[str] = []` から `if not urls:` の直前まで）を置換:

```python
    # ツアー一覧: REST API が正本 (tour-month 空 = 現在提供していない、を除外済み)。
    # urls.txt はシード (手動ピン留め) で、API 結果との和集合を取る。
    tours: list[dict] = []
    seen: set[str] = set()

    def _add(url: str, modified_gmt: str = "", slug: str = "") -> None:
        u = normalize_tour_url(url)
        if not url_ok(u):
            print(f"  WARN: URL outside allowlist, skip: {url}", file=sys.stderr)
            return
        if u in seen:
            return
        seen.add(u)
        tours.append({"url": u, "slug": slug or slug_from_url(u),
                      "modified_gmt": modified_gmt})

    if args.url:
        # 単一 URL 指定時は API を引かず、その URL だけ処理 (手動デバッグ用途)
        _add(args.url)
    else:
        if not args.no_discover:
            for t in fetch_tour_index():
                _add(t["url"], t["modified_gmt"], t["slug"])
        if args.urls_file:
            for u in read_url_list(args.urls_file):
                _add(u)

    if not tours:
        sys.exit("No tour to process (API returned nothing and no seed URLs). "
                 "Pass --url, populate urls-file, or check the REST API.")
```

処理ループを置換:

```python
    print(f"Processing {len(tours)} tour(s) deterministically (no LLM)...", file=sys.stderr)
    ok = err = total_sessions = 0
    for i, t in enumerate(tours, 1):
        print(f"[{i}/{len(tours)}] {t['url']}", file=sys.stderr)
        try:
            n = process_one(t["url"], args.out_dir, args.uid_prefix, args.dry_run)
            if n > 0:
                ok += 1
                total_sessions += n
        except Exception as e:
            err += 1
            print(f"  ERROR: {e}", file=sys.stderr)
    print(f"Done. urls ok={ok} err={err}  total sessions extracted={total_sessions}", file=sys.stderr)
```

- [ ] **Step 5: 全テストを回す**

Run: `python3 calendar/tests/test_tourism_api.py && python3 calendar/tests/test_tourism_discovery.py`
Expected: どちらも PASS

Run: `grep -n "discover_tour_urls\|fetch_index_urls\|_TOUR_HREF_RE\|DEFAULT_INDEX_URL\|index-url" calendar/bin/cal-tourism-fetch`
Expected: 出力なし（削除漏れがない）

- [ ] **Step 6: 実 API に対して dry-run し、現行と同じ結果になることを確認**

Run: `python3 calendar/bin/cal-tourism-fetch --dry-run --out-dir /tmp/tour-out 2>&1 | tail -3`
Expected: `Done. urls ok=39 err=0  total sessions extracted=85` の形。
**`ok` が 38〜40、`err=0`、`total sessions` が 80 前後**であること。
CI の直近実測は `ok=39 err=0 total sessions extracted=85`。
大きくずれたら API 経路の URL 収集が壊れている。

- [ ] **Step 7: Commit**

```bash
git add calendar/bin/cal-tourism-fetch calendar/tests/test_tourism_discovery.py
git commit -m "refactor(tourism): 一覧ページのスクレイピングを REST API に置き換え

discover_tour_urls / fetch_index_urls / _TOUR_HREF_RE / DEFAULT_INDEX_URL と
--index-url を削除。--no-discover は「REST API を引かず urls.txt のみ」の意味に。

この時点では全件取得を維持するので挙動は現行と同じ (--min-sessions も機能する)。"
```

---

### Task 3: サニティチェックを `--min-tours` に差し替える

**skip を入れる前に**ガードを差し替える。この順序なら、まだ全件取得しているので
どちらのガードも誤発火せず、差し替えの正しさだけを確認できる。

**Files:**
- Modify: `calendar/bin/cal-tourism-fetch` (`--min-sessions` を `--min-tours` に、パース失敗検知を追加)
- Modify: `.github/workflows/cal-daily.yml:81`
- Modify: `calendar/tests/test_tourism_api.py` (ガードのテストを追加)

**Interfaces:**
- Consumes: `fetch_tour_index()`（Task 1）
- Produces: `check_tour_count(n_tours: int, min_tours: int) -> None` — 下限未満なら `sys.exit(2)`。CLI は `--min-tours`（既定 20）。`--min-sessions` は削除。

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_tourism_api.py` の `if __name__ == "__main__":` の直前に追加:

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_tourism_api.py`
Expected: FAIL — `AttributeError: module 'cal_tourism_fetch' has no attribute 'check_tour_count'`

- [ ] **Step 3: `check_tour_count()` を実装する**

`calendar/bin/cal-tourism-fetch` の `def main() -> None:` の直前に追加:

```python
def check_tour_count(n_tours: int, min_tours: int) -> None:
    """API が返したツアー件数の下限チェック。未満なら exit 2.

    API の崩壊・大量非公開・仕様変更を検知する。以前は「抽出セッション総数」で
    判定していたが、変更のないページの取得を skip するようになるとセッションが
    0 件の日が普通にあるため、件数の根拠を API 側に移した。
    """
    if n_tours < min_tours:
        print(
            f"FAIL: tours from API ({n_tours}) < --min-tours ({min_tours}). "
            f"Likely API change or mass unpublish. Refusing to continue.",
            file=sys.stderr,
        )
        sys.exit(2)
```

- [ ] **Step 4: CLI 引数を差し替える**

`calendar/bin/cal-tourism-fetch` の argparse から削除:

```python
    ap.add_argument("--min-sessions", type=int, default=5,
                    help="抽出セッション数がこの数未満なら exit code 2 (CI 暴走防止、default: 5)")
```

同じ位置に追加:

```python
    ap.add_argument("--min-tours", type=int, default=20,
                    help="API が返すツアー件数がこれ未満なら exit 2 "
                         "(API 崩壊/大量非公開の検知、default: 20)")
```

- [ ] **Step 5: `main()` でガードを呼び、旧ガードを消す**

`calendar/bin/cal-tourism-fetch` の `main()` 内、API 取得の直後にチェックを入れる。
Task 2 Step 4 で書いた `else:` ブロックを置換:

```python
    else:
        if not args.no_discover:
            # API 障害 / JSON パース失敗も exit 2 (スクレイピングへの fallback は持たない)
            try:
                api_tours = fetch_tour_index()
            except Exception as e:
                print(f"FAIL: tour API unavailable: {e}", file=sys.stderr)
                sys.exit(2)
            # --no-discover 時は API を引かないので件数の根拠が無く、チェックしない
            check_tour_count(len(api_tours), args.min_tours)
            for t in api_tours:
                _add(t["url"], t["modified_gmt"], t["slug"])
        if args.urls_file:
            for u in read_url_list(args.urls_file):
                _add(u)
```

関数末尾の旧ガードを削除:

```python
    # サニティチェック: 抽出セッションが想定より極端に少ないと
    # (ソース構造変化等で) パース失敗の可能性が高い → exit code 2
    if total_sessions < args.min_sessions and not args.dry_run:
        print(
            f"FAIL: extracted sessions ({total_sessions}) < --min-sessions ({args.min_sessions}). "
            f"Likely source structure change. Refusing to commit a possibly-corrupt result.",
            file=sys.stderr,
        )
        sys.exit(2)
```

代わりにパース失敗の検知を追加する。処理ループを置換:

```python
    print(f"Processing {len(tours)} tour(s) deterministically (no LLM)...", file=sys.stderr)
    ok = err = total_sessions = zero_session = 0
    for i, t in enumerate(tours, 1):
        print(f"[{i}/{len(tours)}] {t['url']}", file=sys.stderr)
        try:
            n = process_one(t["url"], args.out_dir, args.uid_prefix, args.dry_run)
            if n > 0:
                ok += 1
                total_sessions += n
            else:
                zero_session += 1
        except Exception as e:
            err += 1
            print(f"  ERROR: {e}", file=sys.stderr)
    print(f"Done. tours={len(tours)}  ok={ok} err={err} zero-session={zero_session}  "
          f"sessions={total_sessions}", file=sys.stderr)

    # パース失敗の検知: 取得したページが 1 件以上あり、その全件でセッションが
    # 取れなかった → HTML 構造が変わった疑い。取得 0 件の日はこの判定をしない。
    fetched = ok + zero_session
    if fetched > 0 and ok == 0 and not args.dry_run:
        print(
            f"FAIL: fetched {fetched} page(s) but extracted 0 sessions. "
            f"Likely source HTML structure change. Refusing to commit a possibly-corrupt result.",
            file=sys.stderr,
        )
        sys.exit(2)
```

- [ ] **Step 6: テストを実行して通ることを確認**

Run: `python3 calendar/tests/test_tourism_api.py && python3 calendar/tests/test_tourism_discovery.py`
Expected: どちらも PASS

- [ ] **Step 7: CI の起動行を差し替える**

`.github/workflows/cal-daily.yml:81` を置換:

```yaml
        run: ./calendar/bin/cal-tourism-fetch --out-dir calendar/events --min-tours 20 || echo "hanno-tourism" >> "$RUNNER_TEMP/crawl-failures.txt"
```

Run: `grep -n "min-sessions" .github/workflows/cal-daily.yml`
Expected: 出力なし（旧引数のままだと argparse がエラーになる）

- [ ] **Step 8: API 失敗が exit 2 になることを確認**

`fetch_tour_index` を失敗させて main を走らせる:

```bash
python3 -c "
import importlib.machinery, importlib.util, sys
l = importlib.machinery.SourceFileLoader('t','calendar/bin/cal-tourism-fetch')
s = importlib.util.spec_from_loader('t', l)
m = importlib.util.module_from_spec(s); l.exec_module(m)
m.fetch_tour_index = lambda: (_ for _ in ()).throw(RuntimeError('boom'))
sys.argv = ['t', '--dry-run', '--out-dir', '/tmp/tour-out-fail']
try:
    m.main()
except SystemExit as e:
    print('exit code =', e.code)
"
```
Expected: `FAIL: tour API unavailable: boom` が出て `exit code = 2`

- [ ] **Step 9: 実 API で dry-run し、ガードが通ることを確認**

Run: `python3 calendar/bin/cal-tourism-fetch --dry-run --out-dir /tmp/tour-out2 2>&1 | tail -2`
Expected: `Done. tours=39  ok=39 err=0 zero-session=0  sessions=85` の形。
exit code が 0 であること（`echo "exit=$?"` で確認）。

Run: `python3 calendar/bin/cal-tourism-fetch --dry-run --min-tours 100 --out-dir /tmp/tour-out3 2>&1 | tail -2; echo "exit=$?"`
Expected: `FAIL: tours from API (39) < --min-tours (100)` が出て `exit=2`

- [ ] **Step 10: Commit**

```bash
git add calendar/bin/cal-tourism-fetch calendar/tests/test_tourism_api.py .github/workflows/cal-daily.yml
git commit -m "refactor(tourism): サニティチェックを --min-tours に差し替え

--min-sessions (抽出セッション総数) は、変更のないページを skip するように
なると変更 0 件の日に必ず誤発火する。目的を 2 つに分離した:

- --min-tours (既定 20): API が返すツアー件数の下限。API 崩壊/大量非公開を検知
- パース失敗検知: 取得したページが 1 件以上あり全件 0 セッションなら exit 2

CI の起動引数も同じコミットで差し替え (--min-sessions 削除により argparse が
エラーになるため)。"
```

---

### Task 4: `modified_gmt` で変更分だけ取得する

**Files:**
- Modify: `calendar/bin/cal-tourism-fetch` (import に cache ヘルパ追加、`select_tours_to_fetch()` / `process_tours()` を追加、`main()` を書き換え)
- Modify: `calendar/tests/test_tourism_api.py` (skip 判定と cache 更新のテストを追加)

**Interfaces:**
- Consumes: `_lib.load_http_cache()` / `_lib.save_http_cache()`、`fetch_tour_index()`（Task 1）、`check_tour_count()`（Task 3）
- Produces:
  - `select_tours_to_fetch(tours: list[dict], cache: dict) -> tuple[list[dict], int]` — `(取得対象, unchanged 件数)`。`modified_gmt` が空文字のツアーは常に取得対象。
  - `process_tours(tours, out_dir, uid_prefix, dry_run, cache) -> dict` — 取得対象を順に処理し、**成功したものだけ** `cache[url]["modified_gmt"]` を更新する。戻り値は `{"ok": int, "err": int, "sessions": int, "zero_session": int}`。

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_tourism_api.py` の `if __name__ == "__main__":` の直前に追加:

```python
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
```

注: `mod.process_one` を差し替えるので、このテストより後に `process_one` の実物を
使うテストを書かないこと（このファイルには無い）。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_tourism_api.py`
Expected: FAIL — `AttributeError: module 'cal_tourism_fetch' has no attribute 'select_tours_to_fetch'`

- [ ] **Step 3: import に cache ヘルパを足す**

`calendar/bin/cal-tourism-fetch` の `from _lib import (...)` を置換:

```python
from _lib import (
    USER_AGENT, UID_NAMESPACE, fetch, existing_content_hash_matches,
    yaml_escape_str, yaml_block_scalar, strip_html, collapse_space,
    normalize_fullwidth_digits, normalize_tilde,
    infer_year_from_og, load_http_cache, save_http_cache,
)
```

- [ ] **Step 4: `select_tours_to_fetch()` と `process_tours()` を実装する**

`calendar/bin/cal-tourism-fetch` の `check_tour_count()` 定義の直後に追加:

```python
def select_tours_to_fetch(tours: list[dict], cache: dict) -> tuple[list[dict], int]:
    """API の modified_gmt と保存値を突き合わせ、(取得対象, unchanged 件数) を返す.

    hanno-tourism.jp は ETag / Last-Modified を返さないので条件付き GET が使えない。
    代わりに WordPress REST API の modified_gmt を .http-cache.json に保存し、
    一致すれば HTML を取得しない。

    modified_gmt が空 (API が返さなかった) 場合は判定材料が無いので必ず取得する。
    """
    todo: list[dict] = []
    unchanged = 0
    for t in tours:
        mg = t.get("modified_gmt") or ""
        prev = (cache.get(t["url"]) or {}).get("modified_gmt") or ""
        if mg and prev and mg == prev:
            unchanged += 1
            continue
        todo.append(t)
    return todo, unchanged


def process_tours(tours: list[dict], out_dir: str, uid_prefix: str,
                  dry_run: bool, cache: dict) -> dict:
    """取得対象を順に処理し、成功したものだけ cache に modified_gmt を記録する.

    例外が出たツアーは記録しない → 次回リトライされる。
    0 セッション (パース失敗の疑い) は記録するが zero_session に計上する
    (同じ内容を毎日取り直しても結果は変わらないため)。

    戻り値: {"ok": int, "err": int, "sessions": int, "zero_session": int}
    """
    ok = err = sessions = zero_session = 0
    for i, t in enumerate(tours, 1):
        print(f"[{i}/{len(tours)}] {t['url']}", file=sys.stderr)
        try:
            n = process_one(t["url"], out_dir, uid_prefix, dry_run)
        except Exception as e:
            err += 1
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
        if n > 0:
            ok += 1
            sessions += n
        else:
            zero_session += 1
        if t.get("modified_gmt"):
            cache.setdefault(t["url"], {})["modified_gmt"] = t["modified_gmt"]
    return {"ok": ok, "err": err, "sessions": sessions, "zero_session": zero_session}
```

- [ ] **Step 5: テストを実行して通ることを確認**

Run: `python3 calendar/tests/test_tourism_api.py`
Expected: PASS — `OK: all tourism-api tests passed`

- [ ] **Step 6: `main()` を結線する**

`calendar/bin/cal-tourism-fetch` の `main()` 内、Task 3 Step 5 で書いた処理ループ
（`print(f"Processing ...")` から関数末尾まで）を置換:

```python
    # --url 指定時は手動デバッグ用途なので判定せず常に取得する。
    # --no-discover 時は urls.txt 由来で modified_gmt が空になり、
    # select_tours_to_fetch が「判定材料なし = 取得」と扱うので特別扱いは不要。
    use_cache = not args.url
    cache = load_http_cache() if use_cache else {}
    if use_cache:
        todo, unchanged = select_tours_to_fetch(tours, cache)
    else:
        todo, unchanged = tours, 0

    print(f"Processing {len(todo)} of {len(tours)} tour(s) "
          f"({unchanged} unchanged, no LLM)...", file=sys.stderr)
    r = process_tours(todo, args.out_dir, args.uid_prefix, args.dry_run, cache)
    if use_cache and not args.dry_run:
        save_http_cache(cache)

    print(f"Done. tours={len(tours)}  fetched={len(todo)}  unchanged={unchanged}  "
          f"ok={r['ok']} err={r['err']} zero-session={r['zero_session']}  "
          f"sessions={r['sessions']}", file=sys.stderr)

    # パース失敗の検知: 取得したページが 1 件以上あり、その全件でセッションが
    # 取れなかった → HTML 構造が変わった疑い。取得 0 件の日はこの判定をしない。
    if len(todo) > 0 and r["ok"] == 0 and not args.dry_run:
        print(
            f"FAIL: fetched {len(todo)} page(s) but extracted 0 sessions. "
            f"Likely source HTML structure change. Refusing to commit a possibly-corrupt result.",
            file=sys.stderr,
        )
        sys.exit(2)
```

- [ ] **Step 7: 全テストを回す**

Run: `python3 calendar/tests/test_tourism_api.py && python3 calendar/tests/test_tourism_discovery.py`
Expected: どちらも PASS

Run: `python3 calendar/tests/run-golden 2>&1 | tail -2`
Expected: `All golden checks passed.`（tourism は golden 対象外だが壊していないことの確認）

- [ ] **Step 8: 実 API で初回実行（全件取得）を確認**

`.http-cache.json` に tourism の URL は 0 件なので、初回は全件取得になる。

Run:
```bash
{ time python3 calendar/bin/cal-tourism-fetch --out-dir calendar/events 2>&1 | tail -2 ; } 2>&1 | grep -E "real|Done"
```
Expected: `Done. tours=39  fetched=39  unchanged=0  ok=39 err=0 zero-session=0  sessions=85` の形で、
`real` は 55 秒前後（初回は現行と同じ）。

Run: `git status --porcelain calendar/.http-cache.json calendar/events/`
Expected: `.http-cache.json` が変更されている。`events/` は変わらないか、ごく少数
（`existing_content_hash_matches` により内容不変なら書かれない）。

Run:
```bash
python3 -c "
import json
d = json.load(open('calendar/.http-cache.json'))
n = sum(1 for u in d if 'hanno-tourism' in u)
print('tourism の URL 数:', n)
print('うち modified_gmt あり:', sum(1 for u,v in d.items() if 'hanno-tourism' in u and v.get('modified_gmt')))
print('city.hanno.lg.jp の URL 数 (壊していないこと):', sum(1 for u in d if 'city.hanno.lg.jp' in u))
"
```
Expected: tourism 39 件、`modified_gmt` あり 39 件、`city.hanno.lg.jp` は 154 件のまま

- [ ] **Step 9: 2 回目の実行で skip が効くことを確認**

Run:
```bash
{ time python3 calendar/bin/cal-tourism-fetch --out-dir calendar/events 2>&1 | tail -2 ; } 2>&1 | grep -E "real|Done"
```
Expected: `Done. tours=39  fetched=0  unchanged=39  ok=0 err=0 zero-session=0  sessions=0` で、
**`real` が 2 秒未満**。`fetched=0` なのでパース失敗ガードは発火しないこと（exit 0）。

Run: `echo "exit=$?"` — Expected: `exit=0`

- [ ] **Step 10: Commit**

```bash
git add calendar/bin/cal-tourism-fetch calendar/tests/test_tourism_api.py calendar/.http-cache.json
git commit -m "perf(tourism): modified_gmt で変更分だけ取得する

hanno-tourism.jp は ETag/Last-Modified を返さないので条件付き GET が使えない。
代わりに REST API の modified_gmt を .http-cache.json に相乗りさせ、一致すれば
HTML を取得しない。実測では日次の変更は 40 件中 0〜6 件。

成功したツアーだけ記録するので、失敗したものは次回リトライされる。
--url は手動デバッグ用途なので判定せず常に取得する。"
```

---

### Task 5: README を更新し、CI で確認する

**Files:**
- Modify: `calendar/README.md` (`## bin/cal-tourism-fetch` セクション、HTTP Conditional GET の対応状況、ユニットテスト一覧)

**Interfaces:**
- Consumes: Task 1〜4 の全成果
- Produces: なし（最終タスク）

- [ ] **Step 1: `## bin/cal-tourism-fetch` セクションを更新する**

`calendar/README.md` の `## bin/cal-tourism-fetch` セクション（`calendar/README.md:168` 付近）に、
ツアー一覧の取得方法を説明する小見出しを追加する:

```markdown
### ツアー一覧の取得 (REST API)

hanno-tourism.jp は WordPress で、REST API が公開されている（ページの `link:` ヘッダが
`/wp-json/` を自己申告している）。ツアーはカスタム投稿タイプ `tour`。

```
GET /wp-json/wp/v2/tour?_fields=id,link,slug,modified_gmt,tour-month&per_page=100&page=N
```

**掲載制御は `tour-month` タクソノミー。** 開催月が 1 つ以上割り当てられているものだけが
一覧ページに載る = 現在提供中。空のものは「提供していない」という編集意図なので除外する。
実測（2026-08-08）で、`tour-month` あり 39 件が一覧ページのスクレイピング結果と
**差分ゼロで一致**した。

ページングは `page=1` から辿り、取得件数が `per_page` 未満なら終了。加えて範囲外ページが
返す HTTP 400 (`rest_post_invalid_page_number`) を終端として許容する（総件数が `per_page` の
倍数のとき 1 ページ余分に要求するため）。`x-wp-totalpages` はヘッダなので `_lib.fetch()`
では読めない。

### 更新検知 (modified_gmt)

hanno-tourism.jp は `ETag` / `Last-Modified` を返さないので条件付き GET が使えない。
代わりに API の `modified_gmt` を `calendar/.http-cache.json` に相乗りさせ、一致すれば
HTML を取得しない。

```json
"https://hanno-tourism.jp/hanno-eco/tour/ec-tenta-kaibori/": {
  "modified_gmt": "2026-08-07T01:00:51"
}
```

**処理が成功したツアーだけ記録する**ので、失敗したものは次回リトライされる。
日程は ACF 由来で API に露出していないため（`content.rendered` は紹介文のみ）、
変更分の HTML 取得は避けられない二段構えになる。

実測した日次の変更件数は 40 件中 0〜6 件。全件取得の 55 秒が、変更 0 件の日は 2 秒未満になる。

### サニティチェック

| フラグ / 判定 | 内容 |
|---|---|
| `--min-tours` (既定 20) | API が返すツアー件数がこれ未満なら exit 2。API 崩壊・大量非公開・仕様変更を検知 |
| パース失敗検知 | 取得したページが 1 件以上あり、その全件で 0 セッションなら exit 2 |

`--min-sessions`（抽出セッション総数）は廃止した。取得を skip するようになると、変更 0 件の
日に必ず誤発火するため。API 失敗・JSON パース失敗は exit 2 で止め、スクレイピングへの
フォールバックは持たない。
```

- [ ] **Step 2: HTTP Conditional GET の対応状況を更新する**

`calendar/README.md` の `### HTTP Conditional GET (efficiency)` セクションの対応状況リストを置換:

```markdown
対応状況:
- ✅ `cal-shiminkaikan`, `cal-gikai`, `cal-shicho-blog` (city.hanno.lg.jp)
- ✅ `cal-oshirase` の**記事ページ** (city.hanno.lg.jp。実測で 50 件すべて 304)
- ❌ `cal-oshirase` の**フィード** (`feed.php` は動的生成で cache header を返さない)
- ⚠️ `cal-tourism` — `hanno-tourism.jp` が `ETag` / `Last-Modified` を返さないので条件付き
  GET は使えない。代わりに REST API の `modified_gmt` を `.http-cache.json` に相乗りさせて
  同等の効果を得ている（上記「更新検知 (modified_gmt)」参照）
```

- [ ] **Step 3: ユニットテスト一覧に追記する**

`calendar/README.md` の `### ユニットテスト` の表に 1 行追加し、既存行を 1 行修正する:

```markdown
| `test_tourism_discovery.py` | tourism の URL 正規化 |
| `test_tourism_api.py` | tourism の REST API 取得 / modified_gmt 判定 / サニティチェック |
```

（`test_tourism_discovery.py` の説明は「一覧ページ自動発見」から「URL 正規化」に変わる。）

- [ ] **Step 4: 実測値を README に反映する**

Step 1 で書いた「全件取得の 55 秒が、変更 0 件の日は 2 秒未満になる」の数字を、
Task 4 Step 8 / Step 9 で得た実測値に差し替える。推測値を書かない。

- [ ] **Step 5: Commit**

```bash
git add calendar/README.md
git commit -m "docs(tourism): REST API 化と modified_gmt 更新検知を README に追記"
```

- [ ] **Step 6: push して CI で確認する**

Run: `git push origin main`

`calendar/bin/**` の変更なので `Calendar daily` が即座に走る。

Run: `gh run list --limit 3`

完了後、tourism ステップの所要時間を確認:

```bash
gh run view <RUN_ID> --json jobs --jq '.jobs[].steps[] | select(.name|test("Crawl hanno-tourism")) | "\(.startedAt) \(.completedAt)"'
```

Expected: **10 秒未満**（改善前は 55 秒）。CI 上の `.http-cache.json` は Task 4 Step 10 で
commit 済みなので、初回から skip が効く。

Run: `gh run view <RUN_ID> --log 2>/dev/null | grep "Crawl hanno-tourism" | grep -E "Done\.|FAIL"`
Expected: `Done. tours=39 fetched=<少数> unchanged=<多数> ok=... err=0 ...`。
`FAIL` が出ていないこと。

**`conclusion` が `success` でなければ原因を報告して止まること。** 特に
`tours=` が 20 未満なら `--min-tours` ガードが発火しているので、API 仕様変更を疑う。

---

## 完了条件

- [ ] `calendar/tests/test_tourism_api.py` と `test_tourism_discovery.py` が緑
- [ ] 既存のユニットテスト 8 本と `run-golden` 3 シナリオが緑
- [ ] `grep -n "discover_tour_urls\|fetch_index_urls\|_TOUR_HREF_RE\|DEFAULT_INDEX_URL\|index-url\|min-sessions" calendar/bin/cal-tourism-fetch` が空
- [ ] `grep -n "min-sessions" .github/workflows/cal-daily.yml` が空
- [ ] 2 回目のローカル実行が `fetched=0 unchanged=39` で 2 秒未満、exit 0
- [ ] `.http-cache.json` の `city.hanno.lg.jp` 154 件が壊れていない
- [ ] CI の `Crawl hanno-tourism` が 10 秒未満で `success`、`FAIL` なし
- [ ] `calendar/README.md` に REST API / `tour-month` / `modified_gmt` / サニティチェック / テスト一覧が載っている
