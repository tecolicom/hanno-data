# お知らせ・市長ブログ 掲載日を Last-Modified 基準にする Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** お知らせ・市長ブログのカレンダー掲載日 (`dtstart`) を、記事の自己申告日でも取得日でもなく **HTTP Last-Modified (JST) + 1 日** にする。既存の catch-up 山も再配置する。

**Architecture:** 共有純粋関数 `_lib.dtstart_from_last_modified` が「Last-Modified ヘッダ → JST 日付 + 1 日 (取れなければ取得日フォールバック)」を担う。両クローラは記事取得を条件付き GET (`fetch_with_cache` + `.http-cache.json`) に寄せ、返ってきた `last_modified` から `dtstart` を決める。既存の `content_hash` (本文 identity) による重複判定はそのまま。`--redate` 保守モードで既存 YAML を再配置。

**Tech Stack:** Python 3 標準ライブラリ (`email.utils`, `datetime`)。テストは pytest 不使用、`importlib` で対象を読む自己完結スクリプト (tourism と同方式)。

## Global Constraints

- 作業リポ: `Hanno/hanno-data`。対象は `calendar/bin/_lib.py`, `calendar/bin/cal-oshirase-fetch`, `calendar/bin/cal-shicho-blog-fetch` (いずれも拡張子なし Python)。
- 実装前に `git -C Hanno/hanno-data pull --ff-only` (CI が日次 push するため)。ブランチを切って作業 (main へ直接 commit しない)。
- **既存の `content_hash` = `{title, 記事日付, body(+blog は body_truncated)}` は変更しない。** これが本文 identity の唯一の基準であり、掲載日を含めないことで再配置しても identity が churn しない。
- `dtstart` 以外の出力 (title, description, uid, source ブロックの既存フィールド) は変えない。`last_modified` を YAML に書き足さない (`dtstart - 1 日 = lm 日付` で追跡可能、`build_yaml_doc` の signature を変えないため)。
- 掲載日の +1 は「実際にウェブに現れた翌日」の意図。JST 変換必須 (Last-Modified は GMT)。
- コミットメッセージ末尾に Co-Authored-By / Claude-Session トレーラ。

## File Structure

- **Modify** `calendar/bin/_lib.py` — 純粋関数 `last_modified_to_jst_date`, `dtstart_from_last_modified` を追加。
- **Modify** `calendar/bin/cal-oshirase-fetch` — http-cache 導入 + 記事を条件付き GET 化、`dtstart` を新ルールに。
- **Modify** `calendar/bin/cal-shicho-blog-fetch` — 記事取得を条件付き GET 化 (月インデックス用 `fetch_cached` を記事にも展開)、`dtstart` を新ルールに。
- **Create** `calendar/tests/test_last_modified_dating.py` — 純粋関数のユニットテスト。
- **Modify (Task 4)** 両クローラ — `--redate` / `--redate-since` 保守モード。

---

## Task 1: 共有純粋関数 (Last-Modified → dtstart)

**Files:**
- Modify: `calendar/bin/_lib.py` (HTTP fetch 群の近く、`fetch_with_cache` の後)
- Test: `calendar/tests/test_last_modified_dating.py`

**Interfaces:**
- Produces:
  - `last_modified_to_jst_date(header: str | None) -> str | None`
    RFC 1123 の Last-Modified を JST 日付 `"YYYY-MM-DD"` に。パース不能/None なら `None`。
  - `dtstart_from_last_modified(header: str | None, fallback_date: str) -> str`
    header が解釈できれば `(JST 日付 + 1 日)` を `"YYYY-MM-DD"` で、できなければ `fallback_date`。

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_last_modified_dating.py`:

```python
#!/usr/bin/env python3
"""_lib の Last-Modified→dtstart 変換のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_last_modified_dating.py
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "bin", "_lib.py")
loader = importlib.machinery.SourceFileLoader("cal_lib", LIB)
spec = importlib.util.spec_from_loader("cal_lib", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def test_jst_date_same_day():
    # 02:29 GMT = 11:29 JST 同日
    assert mod.last_modified_to_jst_date("Wed, 08 Jul 2026 02:29:43 GMT") == "2026-07-08"


def test_jst_date_crosses_midnight():
    # 20:00 GMT = 翌 05:00 JST
    assert mod.last_modified_to_jst_date("Tue, 07 Jul 2026 20:00:00 GMT") == "2026-07-08"


def test_jst_date_unparseable():
    assert mod.last_modified_to_jst_date("garbage") is None
    assert mod.last_modified_to_jst_date(None) is None


def test_dtstart_is_lm_plus_one():
    assert mod.dtstart_from_last_modified("Wed, 08 Jul 2026 02:29:43 GMT", "2026-07-12") == "2026-07-09"


def test_dtstart_crosses_month():
    # 31 Jul JST → +1 = 01 Aug
    assert mod.dtstart_from_last_modified("Fri, 31 Jul 2026 03:00:00 GMT", "2026-07-12") == "2026-08-01"


def test_dtstart_fallback_when_no_header():
    assert mod.dtstart_from_last_modified(None, "2026-07-12") == "2026-07-12"
    assert mod.dtstart_from_last_modified("garbage", "2026-07-12") == "2026-07-12"


if __name__ == "__main__":
    test_jst_date_same_day()
    test_jst_date_crosses_midnight()
    test_jst_date_unparseable()
    test_dtstart_is_lm_plus_one()
    test_dtstart_crosses_month()
    test_dtstart_fallback_when_no_header()
    print("OK: all last-modified dating tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd Hanno/hanno-data && python3 calendar/tests/test_last_modified_dating.py`
Expected: FAIL — `AttributeError: module 'cal_lib' has no attribute 'last_modified_to_jst_date'`

- [ ] **Step 3: 最小実装**

`calendar/bin/_lib.py` の import 群に追加 (ファイル冒頭の import 節、既存 import に合わせて):

```python
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
```
(既に `datetime`/`timedelta`/`timezone` が import 済みなら重複させない。`parsedate_to_datetime` は新規。)

`fetch_with_cache` 定義の後に追加:

```python
_JST = timezone(timedelta(hours=9))


def last_modified_to_jst_date(header: str | None) -> str | None:
    """HTTP Last-Modified (RFC 1123, GMT) を JST の 'YYYY-MM-DD' に。解釈不能なら None."""
    if not header:
        return None
    try:
        dt = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_JST).strftime("%Y-%m-%d")


def dtstart_from_last_modified(header: str | None, fallback_date: str) -> str:
    """掲載日 = Last-Modified(JST) + 1 日。取れなければ fallback_date をそのまま返す."""
    jst = last_modified_to_jst_date(header)
    if jst is None:
        return fallback_date
    d = datetime.strptime(jst, "%Y-%m-%d").date() + timedelta(days=1)
    return d.strftime("%Y-%m-%d")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd Hanno/hanno-data && python3 calendar/tests/test_last_modified_dating.py`
Expected: `OK: all last-modified dating tests passed`

- [ ] **Step 5: Commit**

```bash
cd Hanno/hanno-data
git add calendar/bin/_lib.py calendar/tests/test_last_modified_dating.py
git commit -m "feat(cal): Last-Modified→掲載日(JST+1) 変換の純粋関数を追加

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Muiee4TW1unVSwxxejE8fD"
```

---

## Task 2: oshirase を Last-Modified 掲載日に

**Files:**
- Modify: `calendar/bin/cal-oshirase-fetch` (import 節、`main()` の記事 fetch と incremental 分岐)

**Interfaces:**
- Consumes: `_lib.load_http_cache`, `save_http_cache`, `fetch_with_cache`, `dtstart_from_last_modified`

**背景:** 現状 `main()` は記事を `article_html = fetch(it["url"])` で取得し (~426 行)、incremental 分岐で `dtstart = today_jst` (~483 行)。oshirase は http-cache 未使用。

- [ ] **Step 1: import に追加**

`from _lib import (...)` に `load_http_cache, save_http_cache, fetch_with_cache, dtstart_from_last_modified` を足す (既存の import 括弧内へ)。

- [ ] **Step 2: main() 冒頭で http-cache をロード**

`today_jst = ...` を計算している箇所の近く (記事ループ開始前) に:

```python
    http_cache = load_http_cache()
```

- [ ] **Step 3: 記事取得を条件付き GET 化**

`article_html = fetch(it["url"])` を含む try ブロックを次に置換 (304=未更新は skip):

```python
        # 記事取得: 記録済み Last-Modified/ETag で条件付き GET。304 は未更新 → skip。
        entry = http_cache.get(it["url"], {})
        try:
            article_html, etag, lm = fetch_with_cache(
                it["url"], entry.get("etag"), entry.get("last_modified"))
        except Exception as e:
            print(f"  ERROR fetching {it['url']}: {e}", file=sys.stderr)
            continue
        if article_html is None:   # 304 Not Modified
            unchanged += 1
            continue
        http_cache[it["url"]] = {"etag": etag, "last_modified": lm}
```

(`unchanged` は既存カウンタ。無ければ `continue` のみで可。)

- [ ] **Step 4: incremental 分岐の dtstart を新ルールに**

incremental 分岐の `dtstart = today_jst` を置換:

```python
            dtstart = dtstart_from_last_modified(
                http_cache.get(it["url"], {}).get("last_modified"), today_jst)
```

(legacy `--once-per-page` 分岐の `dtstart = it["date"]` は変更しない。)

- [ ] **Step 5: main() 末尾で http-cache を保存**

記事ループを抜けた後 (集計 print の近く) に:

```python
    save_http_cache(http_cache)
```

- [ ] **Step 6: dry-run で検証**

Run: `cd Hanno/hanno-data && ANTHROPIC_API_KEY= python3 calendar/bin/cal-oshirase-fetch --dry-run 2>&1 | grep -E "===|dtstart|Done|WARN" | head -20`
Expected: 新規/変更記事の `dtstart` が「その記事の Last-Modified(JST)+1」になっている (取得日 today ではない)。ファイルパスも新 dtstart 由来。ネットワーク不通時はその旨を報告 (BLOCKED にしない)。

補助 (フォールバック確認): Last-Modified が無いページが無ければ確認不要。ログに WARN が出ないこと。

- [ ] **Step 7: Commit**

```bash
cd Hanno/hanno-data
git add calendar/bin/cal-oshirase-fetch
git commit -m "feat(oshirase): 掲載日を Last-Modified(JST)+1 に、記事を条件付きGET化

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Muiee4TW1unVSwxxejE8fD"
```

---

## Task 3: 市長ブログを Last-Modified 掲載日に

**Files:**
- Modify: `calendar/bin/cal-shicho-blog-fetch` (`main()` の記事 fetch と incremental 分岐)

**背景:** ブログは月インデックス取得に既に `fetch_cached(url)` (http-cache + `fetch_with_cache`、304 は None、`http_cache[url]={etag,last_modified}` 更新) を持つ (~362-369 行、`main()` 内の closure)。ただし記事本文は `article_html = fetch(article_url)` (~423 行) と素取得。incremental の `dtstart = today_jst` (~463 行)。`save_http_cache(http_cache)` は末尾 (~495 行) に既にある。

- [ ] **Step 1: import に追加**

`from _lib import (...)` に `dtstart_from_last_modified` を足す (load_http_cache/save_http_cache/fetch_with_cache は既に import 済み)。

- [ ] **Step 2: 記事取得を `fetch_cached` に寄せる**

`article_html = fetch(article_url)` を含む try ブロックを置換:

```python
            # 記事取得も条件付き GET。304 (= None) は未更新 → skip。
            try:
                article_html = fetch_cached(article_url)
            except Exception as e:
                print(f"    ERROR fetching {article_url}: {e}", file=sys.stderr)
                continue
            if article_html is None:   # 304 Not Modified
                unchanged += 1
                continue
```

(`fetch_cached` は 200 時に `http_cache[article_url] = {"etag":.., "last_modified":..}` を更新済み。`unchanged` は既存カウンタ。)

- [ ] **Step 3: incremental 分岐の dtstart を新ルールに**

incremental 分岐の `dtstart = today_jst` を置換:

```python
                dtstart = dtstart_from_last_modified(
                    http_cache.get(article_url, {}).get("last_modified"), today_jst)
```

(legacy `--once-per-page` 分岐の `dtstart = parsed["date"]` は変更しない。)

- [ ] **Step 4: dry-run で検証**

Run: `cd Hanno/hanno-data && python3 calendar/bin/cal-shicho-blog-fetch --dry-run 2>&1 | grep -E "===|dtstart|articles|Done|WARN" | head -20`
Expected: 新規/変更記事の `dtstart` が「記事の Last-Modified(JST)+1」。バックデート記事 (本文更新日が過去) でも dtstart は実 Last-Modified 由来になる。

- [ ] **Step 5: Commit**

```bash
cd Hanno/hanno-data
git add calendar/bin/cal-shicho-blog-fetch
git commit -m "feat(shicho-blog): 掲載日を Last-Modified(JST)+1 に、記事を条件付きGET化

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Muiee4TW1unVSwxxejE8fD"
```

---

## Task 4: `--redate` 保守モードで既存バックログを再配置

**Files:**
- Modify: `calendar/bin/cal-oshirase-fetch`, `calendar/bin/cal-shicho-blog-fetch` (argparse + 再配置ルーチン)

**方針:** 既存の crawler 管理 YAML について、URL を再取得して Last-Modified を求め、`dtstart` を新ルールで再計算。現 `dtstart` と違えばファイルを移動 (旧日付名を削除し新日付名で書き直す) し、YAML 内の `dtstart:`/`dtend:` を更新。`--redate-since YYYY-MM-DD` で対象を「現 dtstart がその日以降」に限定し、過去の大量イベントを巻き込まない。

**Interfaces:**
- 新 CLI: `--redate` (action store_true), `--redate-since YYYY-MM-DD` (str, default なし=全件)。
- Consumes: `_lib.dtstart_from_last_modified`, `_lib.output_path_for`, `_lib.load_http_cache/save_http_cache/fetch_with_cache`, 既存の YAML scalar 読取 (`_read_yaml_scalar`/`read_yaml_scalar`) と `_rewrite_yaml_scalar` (oshirase にあり。blog は同等の in-place 書換関数を確認し、無ければ最小実装)。

- [ ] **Step 1: argparse に 2 フラグを追加 (両クローラ)**

各 `main()` の argparse に:

```python
    ap.add_argument("--redate", action="store_true",
                    help="既存 YAML を Last-Modified(JST)+1 で再配置 (ファイル移動)。LLM 呼出なし")
    ap.add_argument("--redate-since", metavar="YYYY-MM-DD",
                    help="現 dtstart がこの日以降の YAML だけ再配置 (未指定=全件)")
```

- [ ] **Step 2: 再配置ルーチンを追加 (両クローラで同型)**

`main()` 冒頭付近で、`--redate` 指定時は通常クロールに入る前に専用処理をして return する分岐を置く。ルーチン (擬似コード、各クローラの既存ヘルパ名に合わせて具体化):

```python
    if args.redate:
        http_cache = load_http_cache()
        moved = skipped = 0
        for path in _iter_managed_yamls(args.out_dir, args.uid_prefix):  # source.type/uid_prefix で絞る
            cur = read_yaml_scalar(path, "dtstart")                      # "YYYY-MM-DD"
            if args.redate_since and cur < args.redate_since:
                continue
            url = read_yaml_scalar(path, "url")
            entry = http_cache.get(url, {})
            body, etag, lm = fetch_with_cache(url, None, None)           # 無条件 GET (lm を確実に取る)
            http_cache[url] = {"etag": etag, "last_modified": lm}
            new_dt = dtstart_from_last_modified(lm, cur)                 # 取れなければ現状維持
            if new_dt == cur:
                skipped += 1
                continue
            uid = read_yaml_scalar(path, "uid")
            new_path = output_path_for(args.out_dir, uid, new_dt)
            if args.dry_run:
                print(f"# REDATE {os.path.relpath(path, args.out_dir)} -> {os.path.relpath(new_path, args.out_dir)}  ({cur} -> {new_dt})")
                moved += 1
                continue
            _rewrite_yaml_scalar(path, "dtstart", new_dt)
            _rewrite_yaml_scalar(path, "dtend", new_dt)
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            os.rename(path, new_path)
            print(f"  REDATE {os.path.basename(path)} -> {os.path.basename(new_path)} ({cur}->{new_dt})", file=sys.stderr)
            moved += 1
        save_http_cache(http_cache)
        print(f"redate: moved={moved} skipped={skipped}", file=sys.stderr)
        return
```

注意: `_iter_managed_yamls` は「その crawler が書いた YAML」を uid の prefix (`tourism-`/`oshirase-`/`shicho-blog-`) かファイル名で絞る。既存の走査ヘルパ (`_existing_content_hashes` 等) の走査ロジックを流用してよい。`read_yaml_scalar` の実名は各ファイルの import を確認して合わせる。

- [ ] **Step 3: dry-run で今日の山への効果を確認 (oshirase)**

Run: `cd Hanno/hanno-data && python3 calendar/bin/cal-oshirase-fetch --redate --redate-since 2026-07-12 --dry-run 2>&1 | grep -E "REDATE|redate:" | head`
Expected: `2026-07-12` に積み上がった oshirase 各件が、実 Last-Modified+1 の日付へ移動する行が出る。`moved` が今日分の件数程度。

- [ ] **Step 4: dry-run 確認 (blog)**

Run: `cd Hanno/hanno-data && python3 calendar/bin/cal-shicho-blog-fetch --redate --redate-since 2026-07-12 --dry-run 2>&1 | grep -E "REDATE|redate:" | head`
Expected: バックデート記事が実 Last-Modified+1 (7月上旬等) へ移動する行が出る。

- [ ] **Step 5: Commit**

```bash
cd Hanno/hanno-data
git add calendar/bin/cal-oshirase-fetch calendar/bin/cal-shicho-blog-fetch
git commit -m "feat(cal): --redate 保守モード (既存YAMLをLast-Modified+1で再配置)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Muiee4TW1unVSwxxejE8fD"
```

---

## 実行 / 反映 (実装後・人手判断)

1. Task 1-3 を push → push トリガで CI が走る (手動 dispatch は重複起動になるので投げない)。翌日以降の新規記事が新掲載日で入る。
2. 既存 23 件の再配置は、まず手元で `--redate --redate-since 2026-07-12` を **dry-run で diff 確認** → 本実行 → `git add calendar/events && git commit && git push`。
   - blast-radius が 50 を超えるなら `gh workflow run "Calendar daily" -f max_changes=N` で catch-up 実行し Calendar 反映。
   - 再配置は既存 event の日付移動 = Google カレンダー上で move。件数と移動先を dry-run で必ず目視してから反映する。

---

## Self-Review

- **Spec coverage:** 掲載日=Last-Modified(JST)+1 (Task 1-3)、条件付き GET による更新検知=304 skip + content_hash 据置 (Task 2/3 Step 3-4、content_hash は不変のまま identity gate)、フォールバック=取得日 (Task 1 `dtstart_from_last_modified`)、既存再配置 `--redate`/`--redate-since` (Task 4) — spec を網羅。`last_modified` の YAML 追記は spec の「source に追加」を YAGNI で省略 (dtstart-1 で追跡可能) ＝ Global Constraints に明記。
- **Placeholder scan:** Task 1-3 は実コード。Task 4 は既存ヘルパ名の確認が必要な箇所を「実名に合わせる」と明示した擬似コード (再配置ロジックは完全記載)。
- **Type consistency:** `last_modified_to_jst_date(str|None)->str|None`, `dtstart_from_last_modified(str|None,str)->str` は定義と全呼出で一致。`output_path_for(out_dir,uid,date_str)` は既存シグネチャのまま。
