# hanno-tourism ツアー URL 自動発見 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cal-tourism-fetch` が一覧ページ `/hanno-eco/` から現行ツアー URL を自動発見し、urls.txt の手動メンテなしで CI が通るようにする。

**Architecture:** 純粋関数 `discover_tour_urls(html)` で一覧 HTML からツアーリンクを抽出（既存 allowlist で検証・dedup・末尾スラッシュ正規化）。ネットワーク層 `fetch_index_urls(url)` がそれを呼び、`main()` で「自動発見 URL ∪ urls.txt シード」を抽出対象にする。既存の canonical チェック・min-sessions ガードは不変。

**Tech Stack:** Python 3 標準ライブラリのみ（`re`, `urllib.request`）。テストは pytest 不使用（この repo にテスト基盤が無いため）、`importlib` で対象モジュールを読み込む自己完結スクリプト。

## Global Constraints

- 対象ファイルは `Hanno/hanno-data` リポの `calendar/bin/cal-tourism-fetch`（拡張子なし・実行可能 Python）。
- 実装前に `git -C Hanno/hanno-data pull --ff-only` でリモート最新に追随（CI が日次で push するため。ローカルは 5/19 時点で古い）。
- 既存の `URL_ALLOWLIST_PATTERN` (`^https://hanno-tourism\.jp/hanno-eco/tour/[a-z0-9\-]+/?$`)、`canonical_url_matches`、`--min-sessions` ガードは変更しない。
- LLM 不使用の決定論パーサを維持。新規依存を足さない。
- コミットメッセージ末尾に Co-Authored-By / Claude-Session トレーラを付ける（この repo の慣習に合わせ、既存メッセージ様式は踏襲）。

---

## File Structure

- **Modify** `calendar/bin/cal-tourism-fetch`
  - 新規純粋関数 `normalize_tour_url`, `discover_tour_urls`
  - 新規ネットワーク関数 `fetch_index_urls`
  - `read_url_list` の欠損ファイル許容化（seed 化に伴い）
  - `main()` に `--index-url` / `--no-discover` 追加、URL ソース合成ロジック
- **Create** `calendar/tests/test_tourism_discovery.py`
  - `discover_tour_urls` のネットワーク非依存ユニットテスト

---

## Task 1: 一覧 HTML からツアー URL を抽出する純粋関数

**Files:**
- Modify: `calendar/bin/cal-tourism-fetch`（`url_ok` 定義の直後、`canonical_url_matches` の前あたり）
- Test: `calendar/tests/test_tourism_discovery.py`

**Interfaces:**
- Consumes: 既存 `URL_ALLOWLIST_PATTERN`, `url_ok(url) -> bool`
- Produces:
  - `normalize_tour_url(url: str) -> str` — 末尾に `/` を1つ持つ形へ正規化
  - `discover_tour_urls(html: str) -> list[str]` — HTML 内の `href` から
    `…/hanno-eco/tour/<slug>/` を抽出し、正規化・allowlist 検証・順序保持 dedup したリスト

- [ ] **Step 1: Write the failing test**

Create `calendar/tests/test_tourism_discovery.py`:

```python
#!/usr/bin/env python3
"""cal-tourism-fetch の discover_tour_urls / normalize_tour_url のユニットテスト。
ネットワーク非依存。実行: python3 calendar/tests/test_tourism_discovery.py
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


SAMPLE_HTML = """
<html><body>
  <a href="https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru">ホタル</a>
  <a href="https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/">ホタル(再掲)</a>
  <a href="https://hanno-tourism.jp/hanno-eco/tour/ec-naguricanoe-sup/">SUP</a>
  <a href="https://hanno-tourism.jp/hanno-eco/about/">about(除外)</a>
  <a href="https://hanno-tourism.jp/event/">event(除外)</a>
  <a href="https://hanno-tourism.jp/hanno-eco/tour/BAD_SLUG/">大文字(除外)</a>
</body></html>
"""


def test_normalize_adds_trailing_slash():
    assert mod.normalize_tour_url(
        "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru"
    ) == "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"
    assert mod.normalize_tour_url(
        "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"
    ) == "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"


def test_discover_extracts_dedups_and_filters():
    urls = mod.discover_tour_urls(SAMPLE_HTML)
    assert urls == [
        "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/",
        "https://hanno-tourism.jp/hanno-eco/tour/ec-naguricanoe-sup/",
    ], urls


def test_discover_empty_on_no_links():
    assert mod.discover_tour_urls("<html><body>no tours</body></html>") == []


if __name__ == "__main__":
    test_normalize_adds_trailing_slash()
    test_discover_extracts_dedups_and_filters()
    test_discover_empty_on_no_links()
    print("OK: all discovery tests passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd Hanno/hanno-data && python3 calendar/tests/test_tourism_discovery.py`
Expected: FAIL — `AttributeError: module 'cal_tourism_fetch' has no attribute 'normalize_tour_url'`

- [ ] **Step 3: Write minimal implementation**

In `calendar/bin/cal-tourism-fetch`, immediately after the `url_ok` function (after line ~293), add:

```python
def normalize_tour_url(url: str) -> str:
    """末尾スラッシュを1つに正規化 (発見 URL と urls.txt シードの表記ゆれを吸収)."""
    return url.rstrip("/") + "/"


# 一覧ページ /hanno-eco/ 内の <a href="…/hanno-eco/tour/<slug>…"> を拾う。
# slug 直後は "/" か引用符終端のどちらでも許容 (末尾スラッシュ有無の両表記に対応)。
_TOUR_HREF_RE = re.compile(
    r'href=["\'](https://hanno-tourism\.jp/hanno-eco/tour/[a-z0-9\-]+/?)["\']'
)


def discover_tour_urls(html: str) -> list[str]:
    """一覧ページ HTML から現行ツアー URL を抽出する (allowlist 検証・順序保持 dedup)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _TOUR_HREF_RE.finditer(html):
        url = normalize_tour_url(m.group(1))
        if not url_ok(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd Hanno/hanno-data && python3 calendar/tests/test_tourism_discovery.py`
Expected: `OK: all discovery tests passed`

- [ ] **Step 5: Commit**

```bash
cd Hanno/hanno-data
git add calendar/bin/cal-tourism-fetch calendar/tests/test_tourism_discovery.py
git commit -m "feat(tourism): 一覧ページからツアー URL を発見する純粋関数を追加

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Muiee4TW1unVSwxxejE8fD"
```

---

## Task 2: 自動発見を main() に結線 (CLI オプション + ソース合成)

**Files:**
- Modify: `calendar/bin/cal-tourism-fetch`（`fetch_html` の近く / `read_url_list` / `main()`）

**Interfaces:**
- Consumes: `discover_tour_urls`, `normalize_tour_url`, `fetch_html`, `read_url_list`
- Produces:
  - `fetch_index_urls(index_url: str) -> list[str]` — 一覧ページを取得し発見結果を返す
  - CLI: `--index-url`（default `https://hanno-tourism.jp/hanno-eco/`）, `--no-discover`

- [ ] **Step 1: `fetch_index_urls` を追加**

In `calendar/bin/cal-tourism-fetch`, after `discover_tour_urls` (from Task 1), add:

```python
DEFAULT_INDEX_URL = "https://hanno-tourism.jp/hanno-eco/"


def fetch_index_urls(index_url: str) -> list[str]:
    """一覧ページを取得してツアー URL を発見する。失敗時は空リストを返す (WARN)."""
    try:
        html = fetch_html(index_url)
    except Exception as e:
        print(f"  WARN: failed to fetch index {index_url}: {e}", file=sys.stderr)
        return []
    urls = discover_tour_urls(html)
    if not urls:
        print(f"  WARN: no tour URLs discovered from index {index_url}", file=sys.stderr)
    return urls
```

- [ ] **Step 2: `read_url_list` を欠損ファイル許容に変更**

Replace the existing `read_url_list` (lines ~278-285) with:

```python
def read_url_list(path: str) -> list[str]:
    """urls.txt (シード) を読む。ファイルが無ければ空 (発見のみで動く)."""
    urls: list[str] = []
    if not os.path.exists(path):
        return urls
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if line:
                urls.append(line)
    return urls
```

- [ ] **Step 3: CLI 引数を追加**

In `main()`, after the `--min-sessions` argument (line ~427), add:

```python
    ap.add_argument("--index-url", default=DEFAULT_INDEX_URL,
                    help=f"ツアー一覧ページ (default: {DEFAULT_INDEX_URL})")
    ap.add_argument("--no-discover", action="store_true",
                    help="一覧ページからの自動発見を無効化し urls-file のみ使う")
```

- [ ] **Step 4: URL ソース合成ロジックに差し替え**

Replace the URL-collection block in `main()` (the block starting `urls: list[str] = []` through the `if not urls:` guard, lines ~430-439) with:

```python
    urls: list[str] = []
    seen: set[str] = set()

    def _add(u: str) -> None:
        n = normalize_tour_url(u) if url_ok(normalize_tour_url(u)) else u
        if n not in seen:
            seen.add(n)
            urls.append(n)

    if args.url:
        # 単一 URL 指定時は発見・シードを使わず、その URL だけ処理
        _add(args.url)
    else:
        if not args.no_discover:
            for u in fetch_index_urls(args.index_url):
                _add(u)
        # urls.txt はシード (手動ピン留め)。発見結果と和集合。
        if args.urls_file:
            for u in read_url_list(args.urls_file):
                _add(u)

    if not urls:
        sys.exit("No URL to process (discovery empty and no seed URLs). "
                 "Pass --url, populate urls-file, or check --index-url.")
```

- [ ] **Step 5: 発見関数のリグレッションテストが依然通ることを確認**

Run: `cd Hanno/hanno-data && python3 calendar/tests/test_tourism_discovery.py`
Expected: `OK: all discovery tests passed`

- [ ] **Step 6: ライブ dry-run で end-to-end 検証**

Run: `cd Hanno/hanno-data && python3 calendar/bin/cal-tourism-fetch --dry-run 2>&1 | grep -E "Processing|Done"`
Expected:
- `Processing 17 URL(s) deterministically ...`（発見17件。件数はサイト状況で前後可）
- `Done. urls ok=<N> err=0  total sessions written=<M>` で `M >= 5`（min-sessions を満たす）

補助確認（自動発見を切ると urls.txt シードのみ = 旧10件で全 skip されること）:
Run: `cd Hanno/hanno-data && python3 calendar/bin/cal-tourism-fetch --no-discover --dry-run 2>&1 | grep -E "Processing|Done"`
Expected: `Processing 10 URL(s) ...` / `total sessions written=0`（従来の陳腐化状態を再現。`--no-discover` が効いている証拠）

- [ ] **Step 7: Commit**

```bash
cd Hanno/hanno-data
git add calendar/bin/cal-tourism-fetch
git commit -m "feat(tourism): 一覧ページ自動発見を結線 (--index-url/--no-discover、urls.txt はシード化)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Muiee4TW1unVSwxxejE8fD"
```

---

## Task 3: urls.txt をシード用途に整理

**Files:**
- Modify: `calendar/sources/hanno-tourism/urls.txt`

**Interfaces:**
- Consumes: なし（データファイルのみ）
- Produces: なし

- [ ] **Step 1: 陳腐化した固定10 URL を削除しシード説明に書き換え**

Replace the entire contents of `calendar/sources/hanno-tourism/urls.txt` with:

```text
# hanno-tourism.jp ツアー URL の「手動シード」。
# 通常は空でよい。cal-tourism-fetch が一覧ページ
# https://hanno-tourism.jp/hanno-eco/ から現行ツアーを自動発見する。
#
# 一覧に載らないツアーを個別にピン留めしたい時だけ、1 行 1 URL で追記する。
# 形式: https://hanno-tourism.jp/hanno-eco/tour/<slug>/
# 発見結果と和集合され、重複は除去される。
```

- [ ] **Step 2: 発見のみで min-sessions を満たすことを最終確認**

Run: `cd Hanno/hanno-data && python3 calendar/bin/cal-tourism-fetch --dry-run 2>&1 | grep -E "Processing|Done"`
Expected: `total sessions written` が 5 以上（シードが空でも発見だけで CI が通る）

- [ ] **Step 3: Commit**

```bash
cd Hanno/hanno-data
git add calendar/sources/hanno-tourism/urls.txt
git commit -m "chore(tourism): urls.txt を手動シード用途に整理 (陳腐化した固定 URL を削除)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Muiee4TW1unVSwxxejE8fD"
```

---

## デプロイ / CI 反映（実装後・人手判断）

- 3 タスクを push すると `cal-daily.yml` が次回 07:00 JST に走る。`workflow_dispatch` で即時手動実行して緑を確認するのが望ましい:
  `gh workflow run "Calendar daily" -R tecolicom/hanno-data` → `gh run watch`
- 初回成功時、6/30 以降撤去された古いツアーの events YAML と、新ツアーの events YAML の差分が commit される。Safety check（50 ファイル上限）に引っかからないか出力を確認する。

---

## Self-Review

- **Spec coverage:** 発見処理（Task 1/2）、URL 合成=和集合（Task 2 Step 4）、urls.txt シード温存（Task 2/3）、安全網温存（未変更を明記）、`--index-url`/`--no-discover`（Task 2）、発見0件 WARN（Task 2 Step 1）、ユニットテスト（Task 1）— spec の全項目を網羅。
- **Placeholder scan:** TBD/TODO なし。全ステップに実コードと期待出力を記載。
- **Type consistency:** `normalize_tour_url(str)->str`, `discover_tour_urls(str)->list[str]`, `fetch_index_urls(str)->list[str]` は定義と呼び出しで一致。`url_ok`/`fetch_html`/`read_url_list` は既存シグネチャのまま。
