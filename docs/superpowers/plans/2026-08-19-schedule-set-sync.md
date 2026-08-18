# 集合同期型クローラ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 配布された予定表を集合として同期するクローラの系統を `calendar/` に新設し、その最初の利用者として飯能商工会議所「日替わりシェフレストラン」の当番表を取り込む。

**Architecture:** 既存クローラは記事 1 本 = イベント 1 個の追記型で、消えたものを判別できない。本系統は「1 エンドポイントに全件」というソースを扱い、**不在 = 予定から外れた**と解釈して削除まで行う。中核は `_lib` に置く 2 つの関数 — 削除可否を決める純粋関数 `plan_set_sync()` と、その決定を実行する I/O ラッパ `sync_set()`。Google カレンダー側への削除伝播は `cal-myhanno prune` を新設して担う。

**Tech Stack:** Python 3 (標準ライブラリ + PyYAML)、`gws` (googleworkspace/cli)、GitHub Actions。LLM は使わない。

設計書: [`docs/superpowers/specs/2026-08-19-schedule-set-sync-design.md`](../specs/2026-08-19-schedule-set-sync-design.md)

## Global Constraints

- **LLM を一切使わない。** このクローラは決定論パースのみ。`ANTHROPIC_API_KEY` に依存してはならない
- **既存 4 カレンダー (`default` / `gikai` / `default.en` / `gikai.en`) の挙動を変えない。** 新しい `chef` カレンダーだけが対象
- **`source:` を持たない YAML (手動キュレーション) には絶対に触れない。** `calendar/README.md` の不可侵原則
- **UID 形式**: `{uid_prefix}-{YYYYMMDD}-{NN:02d}@hanno.city.tecoli.com` (`_lib.UID_NAMESPACE`)
- **`content_hash` 形式**: `sha256-` + sha256 hex の先頭 16 文字。**イベント単位**で計算する (ページ単位ではない)
- **内容無変化なら書き込まない。** mtime も git diff も増やさない。既存 YAML の `translations:` 等を保持するため (`_lib.existing_content_hash_matches` の docstring 参照)
- **絵文字 prefix を summary に付けない**
- **英訳しない。** `chef.en` カレンダーは作らない
- テストの実行方法は既存慣習に従う: `python3 calendar/tests/test_xxx.py` で自己実行、末尾に `if __name__ == "__main__":` の runner を置く
- 新規カレンダー ID: `ae1577f36d2b51db208baec59cc84e90ceab25d41bad166b42c37fb7063f4a46@group.calendar.google.com`

---

## File Structure

| ファイル | 責務 |
|---|---|
| `calendar/bin/_lib.py` (変更) | `normalize_char_width()` / `plan_set_sync()` / `sync_set()` / `SetSyncTooManyDeletions` を追加 |
| `calendar/bin/cal-cci-chef-fetch` (新規) | 商工会議所ページの取得・パース・YAML 生成。`sync_set()` に集合を渡す |
| `calendar/bin/cal-myhanno` (変更) | `prune` サブコマンド追加、`CALENDARS` / `SOURCE_TYPE_TO_CALENDAR` に `chef` 追加 |
| `calendar/bin/cal-translate-en` (変更) | `hanno-cci-chef` を翻訳対象から除外 |
| `calendar/sources.yaml` (変更) | `cci-chef` セクション追加 |
| `calendar/tests/test_char_width.py` (新規) | 文字種正規化 |
| `calendar/tests/test_set_sync.py` (新規) | 削除ガード (純粋関数) |
| `calendar/tests/test_sync_set_io.py` (新規) | `sync_set()` の I/O (tmpdir) |
| `calendar/tests/test_chef_parse.py` (新規) | title 分割と JSON 抽出 |
| `calendar/tests/fixtures/cal-cci-chef-fetch/` (新規) | 取得済み HTML + manifest |
| `calendar/tests/seed/cal-cci-chef-*/` (新規) | 削除シナリオ用の既存 YAML |
| `calendar/tests/golden/cal-cci-chef-*/` (新規) | 期待出力 |
| `calendar/tests/run-golden` (変更) | `CRAWLERS` に 4 シナリオ追加 |
| `.github/workflows/cal-daily.yml` (変更) | crawl + prune ステップ追加 |
| `.github/workflows/cal-golden-test.yml` (変更) | ユニットテストも実行する |
| `README.md` / `calendar/README.md` (変更) | 新系統の説明 |

---

### Task 1: 文字種正規化 `_lib.normalize_char_width()`

同一店が `Ｎ．Ｔｅａｔｉｍｅ` / `Ｎ．Teatime` / `N．Teatime` / `N.Teatime` と最大 6 通りに揺れる。判断を含まない機械的な文字種変換だけで寄せる。

**変換規則**

- 全角 ASCII 相当 (U+FF01–FF5E) → 半角 (コードポイントから 0xFEE0 を引く)。**ただし括弧類は除外**: `（` `）` `［` `］` `｛` `｝` (U+FF08, FF09, FF3B, FF3D, FF5B, FF5D)。日本語文の括弧を半角にすると読みにくくなるため
- 半角カタカナ (U+FF61–FF9F) → 全角。濁点・半濁点の合成が必要なので、連続する run 単位で `unicodedata.normalize("NFKC", run)` を掛ける
- **全角スペース (U+3000) は変換しない。** `Bouguet　Bagle` のような店名内の空白は原文のまま保つ

**Files:**
- Modify: `calendar/bin/_lib.py` (`normalize_fullwidth_digits` の直後、196 行目付近)
- Test: `calendar/tests/test_char_width.py`

**Interfaces:**
- Consumes: なし
- Produces: `_lib.normalize_char_width(s: str) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_char_width.py`:

```python
#!/usr/bin/env python3
"""_lib.normalize_char_width のユニットテスト。
実行: python3 calendar/tests/test_char_width.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "_lib.py")
loader = importlib.machinery.SourceFileLoader("_lib", SCRIPT)
spec = importlib.util.spec_from_loader("_lib", loader)
lib = importlib.util.module_from_spec(spec)
loader.exec_module(lib)


def test_fullwidth_latin_to_ascii():
    # 実データの表記揺れ 6 種のうち 5 種が N.Teatime に寄る
    assert lib.normalize_char_width("Ｎ．Ｔｅａｔｉｍｅ") == "N.Teatime"
    assert lib.normalize_char_width("Ｎ．Teatime") == "N.Teatime"
    assert lib.normalize_char_width("N．Teatime") == "N.Teatime"
    assert lib.normalize_char_width("Ｎ.Teatime") == "N.Teatime"
    assert lib.normalize_char_width("N.Teatime") == "N.Teatime"


def test_case_difference_is_preserved():
    # 大小文字は判断を含むので寄せない (残差 1 件は許容する設計)
    assert lib.normalize_char_width("N.teatime") == "N.teatime"


def test_fullwidth_digits():
    assert lib.normalize_char_width("（８月は夏季休業）") == "（8月は夏季休業）"


def test_parens_are_preserved():
    # 日本語文中の全角括弧は保つ
    assert lib.normalize_char_width("ダルバート（ネパール料理）") == "ダルバート（ネパール料理）"
    assert lib.normalize_char_width("吊るし飾りの会（ＰＭ）") == "吊るし飾りの会（PM）"


def test_halfwidth_kana_to_fullwidth():
    assert lib.normalize_char_width("焼きたてﾍﾞｰｸﾞﾙ・ﾄﾞﾘﾝｸ") == "焼きたてベーグル・ドリンク"
    assert lib.normalize_char_width("魯肉飯（ﾙｰﾛｰﾊﾝ）") == "魯肉飯（ルーローハン）"


def test_ideographic_space_untouched():
    # 店名内の全角スペース 1 個は原文のまま
    assert lib.normalize_char_width("Bouguet　Bagle") == "Bouguet　Bagle"


def test_japanese_text_untouched():
    for s in ["北京ごはん", "浮き雲", "日替わりランチ", "手網焙煎珈琲", "出店者募集中"]:
        assert lib.normalize_char_width(s) == s, s


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all char-width tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_char_width.py`
Expected: FAIL — `AttributeError: module '_lib' has no attribute 'normalize_char_width'`

- [ ] **Step 3: 最小実装を書く**

`calendar/bin/_lib.py` の `normalize_fullwidth_digits()` の直後に追加。ファイル冒頭の import に `import unicodedata` を足す。

```python
# 全角 → 半角に寄せない括弧類。日本語文中の括弧を半角にすると読みにくくなるので
# 意図的に除外する (＝ 変換は「判断を含まない文字種の寄せ」に留める)。
_FULLWIDTH_KEEP = frozenset("（）［］｛｝")

# 半角カタカナ (濁点・半濁点を含む)。濁点は後続文字なので run 単位で合成する。
_HALFWIDTH_KANA_RE = re.compile(r"[｡-ﾟ]+")


def normalize_char_width(s: str) -> str:
    """文字種を機械的に寄せる (全角 ASCII → 半角、半角カナ → 全角).

    表記揺れ (`Ｎ．Ｔｅａｔｉｍｅ` / `N.Teatime` 等) を減らすための正規化。
    **判断を含む正規化はしない**: 大小文字の差、全角スペース (U+3000)、
    全角括弧はそのまま残す。エイリアス表による寄せもしない。

    半角カナは `unicodedata.normalize("NFKC", ...)` を連続 run に掛けて
    合成する (`ﾍﾞ` → `ベ`)。NFKC を文字列全体に掛けないのは、`～` や `①`、
    全角括弧まで巻き込んで原文を必要以上に書き換えてしまうため。
    """
    def _kana(m: re.Match) -> str:
        return unicodedata.normalize("NFKC", m.group(0))

    s = _HALFWIDTH_KANA_RE.sub(_kana, s)

    out = []
    for c in s:
        co = ord(c)
        if 0xff01 <= co <= 0xff5e and c not in _FULLWIDTH_KEEP:
            out.append(chr(co - 0xfee0))
        else:
            out.append(c)
    return "".join(out)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_char_width.py`
Expected: `OK: all char-width tests passed`

- [ ] **Step 5: 既存テストが壊れていないことを確認**

Run: `python3 calendar/tests/run-golden`
Expected: `All golden checks passed.`

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/_lib.py calendar/tests/test_char_width.py
git commit -m "feat(calendar): 文字種正規化 normalize_char_width を追加"
```

---

### Task 2: 集合照合と削除ガード `_lib.plan_set_sync()`

**この設計の安全性の中核。** 純粋関数として切り出し、I/O 抜きで全分岐をテストする。

**削除の 3 条件** (すべて満たすときだけ削除):

1. 既存側にあり、取得側に無い
2. `dtstart` が取得集合の日付範囲 `[min, max]` に含まれる — ソースはローリングウィンドウなので、範囲外の過去分を守る
3. `dtstart >= today` — 時間が経って流れた予定は記録として残す

加えて、削除対象が `max_delete` を超えたら例外を投げて**何も書かせない**。

**Files:**
- Modify: `calendar/bin/_lib.py` (ファイル末尾付近、`load_source_config` の後)
- Test: `calendar/tests/test_set_sync.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `_lib.SetSyncTooManyDeletions(RuntimeError)`
  - `_lib.plan_set_sync(existing: dict[str, str], incoming: dict[str, str], dates: dict[str, str], today: str, max_delete: int = 10) -> dict[str, list[str]]`
    - `existing`: `{uid: content_hash}` — 既存 YAML
    - `incoming`: `{uid: content_hash}` — 取得した集合
    - `dates`: `{uid: "YYYY-MM-DD"}` — existing と incoming の**両方**の uid → dtstart
    - 返り値: `{"write": [uid...], "delete": [uid...], "unchanged": [uid...]}` (各リストは uid でソート済み)

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_set_sync.py`:

```python
#!/usr/bin/env python3
"""_lib.plan_set_sync の削除ガードのユニットテスト。
実行: python3 calendar/tests/test_set_sync.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "_lib.py")
loader = importlib.machinery.SourceFileLoader("_lib", SCRIPT)
spec = importlib.util.spec_from_loader("_lib", loader)
lib = importlib.util.module_from_spec(spec)
loader.exec_module(lib)

TODAY = "2026-06-01"


def test_new_events_are_written():
    got = lib.plan_set_sync(
        existing={},
        incoming={"chef-20260610-01@x": "h1"},
        dates={"chef-20260610-01@x": "2026-06-10"},
        today=TODAY)
    assert got["write"] == ["chef-20260610-01@x"], got
    assert got["delete"] == [], got


def test_unchanged_events_are_not_rewritten():
    got = lib.plan_set_sync(
        existing={"chef-20260610-01@x": "h1"},
        incoming={"chef-20260610-01@x": "h1"},
        dates={"chef-20260610-01@x": "2026-06-10"},
        today=TODAY)
    assert got["write"] == [], got
    assert got["unchanged"] == ["chef-20260610-01@x"], got


def test_changed_events_are_rewritten():
    got = lib.plan_set_sync(
        existing={"chef-20260610-01@x": "old"},
        incoming={"chef-20260610-01@x": "new"},
        dates={"chef-20260610-01@x": "2026-06-10"},
        today=TODAY)
    assert got["write"] == ["chef-20260610-01@x"], got


def test_future_event_gone_from_source_is_deleted():
    # 取得範囲 2026-06-05 〜 2026-06-20 の内側、かつ未来
    got = lib.plan_set_sync(
        existing={"chef-20260610-01@x": "h1", "chef-20260605-01@x": "h2"},
        incoming={"chef-20260605-01@x": "h2", "chef-20260620-01@x": "h3"},
        dates={"chef-20260610-01@x": "2026-06-10",
               "chef-20260605-01@x": "2026-06-05",
               "chef-20260620-01@x": "2026-06-20"},
        today=TODAY)
    assert got["delete"] == ["chef-20260610-01@x"], got


def test_past_event_is_never_deleted():
    # 取得範囲の内側だが today より前 → 記録として残す
    got = lib.plan_set_sync(
        existing={"chef-20260510-01@x": "h1"},
        incoming={"chef-20260501-01@x": "h2", "chef-20260620-01@x": "h3"},
        dates={"chef-20260510-01@x": "2026-05-10",
               "chef-20260501-01@x": "2026-05-01",
               "chef-20260620-01@x": "2026-06-20"},
        today=TODAY)
    assert got["delete"] == [], got


def test_event_outside_fetched_range_is_never_deleted():
    # 未来だが取得範囲の外 → ローリングウィンドウが縮んだだけかもしれない
    got = lib.plan_set_sync(
        existing={"chef-20261225-01@x": "h1"},
        incoming={"chef-20260605-01@x": "h2", "chef-20260620-01@x": "h3"},
        dates={"chef-20261225-01@x": "2026-12-25",
               "chef-20260605-01@x": "2026-06-05",
               "chef-20260620-01@x": "2026-06-20"},
        today=TODAY)
    assert got["delete"] == [], got


def test_empty_incoming_deletes_nothing():
    # パース失敗で 0 件になっても既存を消さない (日付範囲が定義できない)
    got = lib.plan_set_sync(
        existing={"chef-20260610-01@x": "h1"},
        incoming={},
        dates={"chef-20260610-01@x": "2026-06-10"},
        today=TODAY)
    assert got["delete"] == [], got
    assert got["write"] == [], got


def test_too_many_deletions_raises():
    existing = {f"chef-2026061{i}-01@x": "h" for i in range(10)}
    dates = {f"chef-2026061{i}-01@x": f"2026-06-1{i}" for i in range(10)}
    dates["chef-20260620-01@x"] = "2026-06-20"
    try:
        lib.plan_set_sync(
            existing=existing,
            incoming={"chef-20260620-01@x": "h"},
            dates=dates,
            today=TODAY,
            max_delete=3)
    except lib.SetSyncTooManyDeletions as e:
        assert "3" in str(e), str(e)
        return
    raise AssertionError("SetSyncTooManyDeletions が投げられなかった")


def test_deletion_at_the_cap_is_allowed():
    existing = {"chef-20260610-01@x": "h1", "chef-20260611-01@x": "h2"}
    dates = {"chef-20260610-01@x": "2026-06-10",
             "chef-20260611-01@x": "2026-06-11",
             "chef-20260620-01@x": "2026-06-20"}
    got = lib.plan_set_sync(
        existing=existing,
        incoming={"chef-20260620-01@x": "h"},
        dates=dates,
        today=TODAY,
        max_delete=2)
    assert len(got["delete"]) == 2, got


def test_event_on_today_is_deletable():
    # 境界: dtstart == today は「今日以降」に含む
    got = lib.plan_set_sync(
        existing={"chef-20260601-01@x": "h1"},
        incoming={"chef-20260530-01@x": "h2", "chef-20260620-01@x": "h3"},
        dates={"chef-20260601-01@x": "2026-06-01",
               "chef-20260530-01@x": "2026-05-30",
               "chef-20260620-01@x": "2026-06-20"},
        today=TODAY)
    assert got["delete"] == ["chef-20260601-01@x"], got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all set-sync tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_set_sync.py`
Expected: FAIL — `AttributeError: module '_lib' has no attribute 'plan_set_sync'`

- [ ] **Step 3: 最小実装を書く**

`calendar/bin/_lib.py` の末尾に追加:

```python
# ==================== 集合同期 (schedule set sync) ====================
# 「1 エンドポイントに全件が載る予定表」を扱う系統の中核。既存の追記型クローラ
# (記事 1 本 = イベント 1 個) と違い、取得側に無い = 予定から外れた と解釈できる
# ので、削除まで行える。設計:
# docs/superpowers/specs/2026-08-19-schedule-set-sync-design.md


class SetSyncTooManyDeletions(RuntimeError):
    """削除対象が上限を超えた。パース失敗でカレンダーが空になる事故を止める。"""


def plan_set_sync(existing: dict[str, str], incoming: dict[str, str],
                  dates: dict[str, str], today: str,
                  max_delete: int = 10) -> dict[str, list[str]]:
    """既存集合と取得集合を照合し、書き込み / 削除 / 据え置きを決める (純粋関数).

    existing / incoming: {uid: content_hash}
    dates:               {uid: "YYYY-MM-DD"}  (existing と incoming の両方を含む)
    today:               "YYYY-MM-DD"

    削除は以下を **すべて** 満たすときだけ:
      1. 既存側にあり取得側に無い
      2. dtstart が取得集合の日付範囲 [min, max] の内側
         → ソースはローリングウィンドウなので、範囲外の過去分を守る
      3. dtstart >= today
         → 時間が経って流れていった予定は記録として残す

    incoming が空なら日付範囲を定義できないので何も削除しない (パース失敗時の保険)。
    """
    write = sorted(uid for uid, h in incoming.items() if existing.get(uid) != h)
    unchanged = sorted(uid for uid, h in incoming.items() if existing.get(uid) == h)

    delete: list[str] = []
    if incoming:
        incoming_dates = [dates[uid] for uid in incoming if uid in dates]
        lo, hi = min(incoming_dates), max(incoming_dates)
        for uid in existing:
            if uid in incoming:
                continue
            d = dates.get(uid)
            if d is None:
                continue        # 日付不明は触らない
            if not (lo <= d <= hi):
                continue        # 取得範囲の外
            if d < today:
                continue        # 過去は残す
            delete.append(uid)
        delete.sort()

    if len(delete) > max_delete:
        raise SetSyncTooManyDeletions(
            f"{len(delete)} deletions exceed max_delete={max_delete}; "
            f"refusing to write. targets: {delete[:20]}")

    return {"write": write, "delete": delete, "unchanged": unchanged}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_set_sync.py`
Expected: `OK: all set-sync tests passed`

- [ ] **Step 5: コミット**

```bash
git add calendar/bin/_lib.py calendar/tests/test_set_sync.py
git commit -m "feat(calendar): 集合同期の削除ガード plan_set_sync を追加"
```

---

### Task 3: 集合同期の I/O `_lib.sync_set()`

Task 2 の決定を実際のファイル操作に落とす。UID 採番と `content_hash` 計算もここで行い、YAML の中身の組み立てだけ呼び出し側のコールバックに委ねる (ソースごとに YAML の形が違うため)。

**Files:**
- Modify: `calendar/bin/_lib.py` (`plan_set_sync` の直後)
- Test: `calendar/tests/test_sync_set_io.py`

**Interfaces:**
- Consumes: `_lib.plan_set_sync`, `_lib.UID_NAMESPACE`, `_lib.output_path_for`, `_lib.read_yaml_scalar`
- Produces:
  - `_lib.set_sync_uid(uid_prefix: str, date: str, seq: int) -> str`
  - `_lib.set_sync_hash(item: dict) -> str` — `"sha256-xxxxxxxxxxxxxxxx"`
  - `_lib.sync_set(out_dir, uid_prefix, items, render_doc, today=None, max_delete=10, dry_run=False) -> dict`
    - `items`: `[{"date": "YYYY-MM-DD", "summary": str, "description": str}, ...]`
    - `render_doc`: `(uid: str, item: dict, source_id: str, content_hash: str) -> str` — YAML 本文を返す
    - 返り値: `{"added": int, "updated": int, "deleted": int, "unchanged": int}`

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_sync_set_io.py`:

```python
#!/usr/bin/env python3
"""_lib.sync_set の I/O のユニットテスト (tmpdir、ネットワーク不使用)。
実行: python3 calendar/tests/test_sync_set_io.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import glob
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "_lib.py")
loader = importlib.machinery.SourceFileLoader("_lib", SCRIPT)
spec = importlib.util.spec_from_loader("_lib", loader)
lib = importlib.util.module_from_spec(spec)
loader.exec_module(lib)

TODAY = "2026-06-01"


def _render(uid, item, source_id, content_hash):
    return (f'uid: "{uid}"\n'
            f'summary: "{item["summary"]}"\n'
            f'dtstart: "{item["date"]}"\n'
            f'dtend: "{item["date"]}"\n'
            f"source:\n"
            f'  type: test-source\n'
            f'  id: "{source_id}"\n'
            f'  content_hash: "{content_hash}"\n')


def _items(*pairs):
    return [{"date": d, "summary": s, "description": ""} for d, s in pairs]


def _yaml_files(d):
    return sorted(os.path.relpath(p, d)
                  for p in glob.glob(os.path.join(d, "**", "*.yaml"), recursive=True))


def test_creates_files_at_expected_paths():
    with tempfile.TemporaryDirectory() as d:
        stats = lib.sync_set(d, "chef", _items(("2026-06-10", "北京ごはん")),
                             _render, today=TODAY)
        assert stats["added"] == 1, stats
        assert _yaml_files(d) == [os.path.join("2026", "06-10_chef-20260610-01.yaml")], _yaml_files(d)


def test_second_run_with_same_data_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        items = _items(("2026-06-10", "北京ごはん"))
        lib.sync_set(d, "chef", items, _render, today=TODAY)
        path = os.path.join(d, "2026", "06-10_chef-20260610-01.yaml")
        before = os.stat(path).st_mtime_ns
        stats = lib.sync_set(d, "chef", items, _render, today=TODAY)
        assert stats == {"added": 0, "updated": 0, "deleted": 0, "unchanged": 1}, stats
        assert os.stat(path).st_mtime_ns == before, "無変化なのに書き換えられた"


def test_changed_summary_updates_in_place():
    with tempfile.TemporaryDirectory() as d:
        lib.sync_set(d, "chef", _items(("2026-06-10", "北京ごはん")), _render, today=TODAY)
        stats = lib.sync_set(d, "chef", _items(("2026-06-10", "浮き雲")), _render, today=TODAY)
        assert stats["updated"] == 1, stats
        path = os.path.join(d, "2026", "06-10_chef-20260610-01.yaml")
        with open(path, encoding="utf-8") as f:
            assert "浮き雲" in f.read()


def test_removed_future_event_is_deleted():
    with tempfile.TemporaryDirectory() as d:
        lib.sync_set(d, "chef",
                     _items(("2026-06-05", "A"), ("2026-06-10", "B"), ("2026-06-20", "C")),
                     _render, today=TODAY)
        stats = lib.sync_set(d, "chef",
                             _items(("2026-06-05", "A"), ("2026-06-20", "C")),
                             _render, today=TODAY)
        assert stats["deleted"] == 1, stats
        assert not os.path.exists(os.path.join(d, "2026", "06-10_chef-20260610-01.yaml"))


def test_same_day_multiple_entries_get_stable_sequence():
    # 連番は summary のソート順で決まる = 入力順が変わっても UID が動かない
    with tempfile.TemporaryDirectory() as d:
        lib.sync_set(d, "chef", _items(("2026-06-10", "ZZZ"), ("2026-06-10", "AAA")),
                     _render, today=TODAY)
        assert _yaml_files(d) == [
            os.path.join("2026", "06-10_chef-20260610-01.yaml"),
            os.path.join("2026", "06-10_chef-20260610-02.yaml"),
        ], _yaml_files(d)
        with open(os.path.join(d, "2026", "06-10_chef-20260610-01.yaml"), encoding="utf-8") as f:
            assert "AAA" in f.read()


def test_other_prefix_yaml_is_untouched():
    # 同じ events/ にある別クローラ / 手動 YAML を巻き込まない
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "2026"))
        other = os.path.join(d, "2026", "06-10_evt-20260610-01.yaml")
        with open(other, "w", encoding="utf-8") as f:
            f.write('uid: "evt-20260610-01@hanno.city.tecoli.com"\ndtstart: "2026-06-10"\n')
        lib.sync_set(d, "chef", _items(("2026-06-05", "A"), ("2026-06-20", "C")),
                     _render, today=TODAY)
        assert os.path.exists(other), "別 prefix の YAML が消された"


def test_too_many_deletions_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        lib.sync_set(d, "chef",
                     _items(("2026-06-05", "A"), ("2026-06-10", "B"),
                            ("2026-06-11", "C"), ("2026-06-20", "D")),
                     _render, today=TODAY)
        before = _yaml_files(d)
        try:
            lib.sync_set(d, "chef", _items(("2026-06-05", "A"), ("2026-06-20", "D")),
                         _render, today=TODAY, max_delete=1)
        except lib.SetSyncTooManyDeletions:
            assert _yaml_files(d) == before, "例外を投げたのにファイルが変わった"
            return
        raise AssertionError("SetSyncTooManyDeletions が投げられなかった")


def test_dry_run_touches_nothing():
    with tempfile.TemporaryDirectory() as d:
        stats = lib.sync_set(d, "chef", _items(("2026-06-10", "北京ごはん")),
                             _render, today=TODAY, dry_run=True)
        assert stats["added"] == 1, stats
        assert _yaml_files(d) == [], _yaml_files(d)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all sync_set I/O tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_sync_set_io.py`
Expected: FAIL — `AttributeError: module '_lib' has no attribute 'sync_set'`

- [ ] **Step 3: 最小実装を書く**

`calendar/bin/_lib.py` の `plan_set_sync` の直後に追加。冒頭 import に `import hashlib`, `import json`, `import datetime` が無ければ足す (既に `datetime` は使われている)。

```python
def set_sync_uid(uid_prefix: str, date: str, seq: int) -> str:
    """集合同期系の UID. `{prefix}-{YYYYMMDD}-{NN}@{namespace}` (市民会館と同規約)."""
    return f"{uid_prefix}-{date.replace('-', '')}-{seq:02d}@{UID_NAMESPACE}"


def set_sync_hash(item: dict) -> str:
    """イベント 1 件の content_hash. **ページ単位ではなくイベント単位**で計算する.

    ページ単位にすると、1 件変わっただけで全件が書き換わり、git diff と
    Calendar の update が無用に膨らむ (cal-shiminkaikan-fetch の既知の弱点)。
    """
    canonical = json.dumps({k: item.get(k) for k in ("date", "summary", "description")},
                           ensure_ascii=False, sort_keys=True)
    return "sha256-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _scan_existing_set(out_dir: str, uid_prefix: str) -> dict[str, dict]:
    """out_dir 配下から uid が `{uid_prefix}-` で始まる YAML を集める.

    返り値: {uid: {"path": str, "dtstart": str, "content_hash": str}}
    """
    found: dict[str, dict] = {}
    for path in glob.glob(os.path.join(out_dir, "**", "*.yaml"), recursive=True):
        uid = read_yaml_scalar(path, "uid")
        if not uid or not uid.startswith(f"{uid_prefix}-"):
            continue
        found[uid] = {
            "path": path,
            "dtstart": (read_yaml_scalar(path, "dtstart") or "")[:10],
            "content_hash": read_yaml_scalar(path, "content_hash") or "",
        }
    return found


def sync_set(out_dir: str, uid_prefix: str, items: list[dict], render_doc,
             today: str | None = None, max_delete: int = 10,
             dry_run: bool = False) -> dict[str, int]:
    """予定表の集合を events/ に同期する (追加 / 更新 / 削除).

    items:      [{"date": "YYYY-MM-DD", "summary": str, "description": str}, ...]
    render_doc: (uid, item, source_id, content_hash) -> YAML 本文 (str)
    today:      "YYYY-MM-DD"。省略時は実日付 (テストのために注入可能にしてある)

    削除条件と安全弁は plan_set_sync() を参照。例外が飛ぶときは
    **1 バイトも書かない** (判定を全部済ませてから書き込む)。
    """
    if today is None:
        today = _date.today().isoformat()   # _lib は `from datetime import date as _date`

    # --- 採番: 同一日内は summary のソート順。入力順が変わっても UID が動かない ---
    by_date: dict[str, list[dict]] = {}
    for it in items:
        by_date.setdefault(it["date"], []).append(it)

    incoming: dict[str, str] = {}
    dates: dict[str, str] = {}
    item_by_uid: dict[str, dict] = {}
    source_id_by_uid: dict[str, str] = {}
    for date, group in by_date.items():
        for seq, it in enumerate(sorted(group, key=lambda x: x["summary"]), start=1):
            uid = set_sync_uid(uid_prefix, date, seq)
            incoming[uid] = set_sync_hash(it)
            dates[uid] = date
            item_by_uid[uid] = it
            source_id_by_uid[uid] = f"{date.replace('-', '')}-{seq:02d}"

    existing_info = _scan_existing_set(out_dir, uid_prefix)
    existing = {uid: info["content_hash"] for uid, info in existing_info.items()}
    for uid, info in existing_info.items():
        dates.setdefault(uid, info["dtstart"])

    # ここで例外が飛ぶ場合、まだ何も書いていない
    plan = plan_set_sync(existing, incoming, dates, today, max_delete=max_delete)

    added = updated = deleted = 0
    for uid in plan["write"]:
        it = item_by_uid[uid]
        doc = render_doc(uid, it, source_id_by_uid[uid], incoming[uid])
        is_new = uid not in existing_info
        if dry_run:
            added, updated = (added + 1, updated) if is_new else (added, updated + 1)
            continue
        # 既存があれば同じ path を使う (日付が変わっても UID に日付が入るので実質不変)
        path = existing_info[uid]["path"] if not is_new else output_path_for(out_dir, uid, dates[uid])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc)
        if is_new:
            added += 1
        else:
            updated += 1

    for uid in plan["delete"]:
        if dry_run:
            deleted += 1
            continue
        os.remove(existing_info[uid]["path"])
        deleted += 1

    return {"added": added, "updated": updated,
            "deleted": deleted, "unchanged": len(plan["unchanged"])}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_sync_set_io.py`
Expected: `OK: all sync_set I/O tests passed`

- [ ] **Step 5: 先行タスクのテストが壊れていないことを確認**

Run: `python3 calendar/tests/test_set_sync.py && python3 calendar/tests/run-golden`
Expected: 両方成功

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/_lib.py calendar/tests/test_sync_set_io.py
git commit -m "feat(calendar): 集合同期の I/O ラッパ sync_set を追加"
```

---

### Task 4: 商工会議所ページのパース

ページ本体の取得はまだしない。**HTML 文字列 → `items` の純粋関数**だけを作る。

**Files:**
- Create: `calendar/bin/cal-cci-chef-fetch`
- Test: `calendar/tests/test_chef_parse.py`

**Interfaces:**
- Consumes: `_lib.normalize_char_width`
- Produces (module scope、`run-golden` と test から `SourceFileLoader` で読める):
  - `extract_events_json(html: str) -> list[dict]` — FullCalendar の `events:` 配列を返す
  - `split_title(title: str) -> tuple[str, list[str]]` — `(店名, [メニュー行...])`
  - `build_items(html: str) -> list[dict]` — `[{"date","summary","description"}, ...]`

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_chef_parse.py`:

```python
#!/usr/bin/env python3
"""cal-cci-chef-fetch のパース部のユニットテスト。
実行: python3 calendar/tests/test_chef_parse.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-cci-chef-fetch")
loader = importlib.machinery.SourceFileLoader("cal_cci_chef_fetch", SCRIPT)
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


HTML = '''<html><body>
<script>
  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: 'dayGridMonth',
    events: [{"start":"2026-04-14","title":"\\u6d6e\\u304d\\u96f2\\n\\u30c0\\u30eb\\u30d0\\u30fc\\u30c8","allDay":true},{"start":"2026-04-02","title":"\\u5317\\u4eac\\u3054\\u306f\\u3093","allDay":true}],
    contentHeight: 'auto'
  });
</script>
</body></html>'''


def test_extract_events_json():
    got = m.extract_events_json(HTML)
    assert len(got) == 2, got
    assert got[0]["start"] == "2026-04-14", got[0]
    assert got[0]["title"] == "浮き雲\nダルバート", got[0]


def test_extract_raises_when_structure_changes():
    try:
        m.extract_events_json("<html><body>no calendar here</body></html>")
    except ValueError:
        return
    raise AssertionError("構造変化を検知できていない")


def test_split_title_newline_separated():
    name, menu = m.split_title("北京ごはん\n魯肉飯（ﾙｰﾛｰﾊﾝ）\nタピオカ\n他")
    assert name == "北京ごはん", name
    assert menu == ["魯肉飯（ルーローハン）", "タピオカ", "他"], menu


def test_split_title_ideographic_space_padded():
    src = "N.Teatime　　　　　日替わりランチ　　　　手網焙煎珈琲"
    name, menu = m.split_title(src)
    assert name == "N.Teatime", name
    assert menu == ["日替わりランチ", "手網焙煎珈琲"], menu


def test_split_title_keeps_single_space_inside_name():
    # 空白 1 個は区切りにしない (店名の一部)
    name, menu = m.split_title("Bouguet　Bagle　　　　　焼きたてﾍﾞｰｸﾞﾙ・ﾄﾞﾘﾝｸ")
    assert name == "Bouguet　Bagle", name
    assert menu == ["焼きたてベーグル・ドリンク"], menu


def test_split_title_name_only():
    name, menu = m.split_title("ひだまりcafeほわっと（認知症支援）")
    assert name == "ひだまりcafeほわっと（認知症支援）", name
    assert menu == [], menu


def test_split_title_normalizes_variants():
    for src in ["Ｎ．Ｔｅａｔｉｍｅ", "Ｎ．Teatime", "N．Teatime", "Ｎ.Teatime"]:
        name, _ = m.split_title(src)
        assert name == "N.Teatime", (src, name)


def test_build_items():
    got = m.build_items(HTML)
    assert got == [
        {"date": "2026-04-02", "summary": "北京ごはん", "description": ""},
        {"date": "2026-04-14", "summary": "浮き雲", "description": "ダルバート"},
    ], got


def test_non_chef_entries_are_kept():
    html = HTML.replace(
        '{"start":"2026-04-02","title":"\\u5317\\u4eac\\u3054\\u306f\\u3093","allDay":true}',
        '{"start":"2026-04-02","title":"\\u6bce\\u9031\\u706b\\u66dc\\u65e5\\u3000\\u3000\\u3000\\u51fa\\u5e97\\u8005\\u52df\\u96c6\\u4e2d","allDay":true}')
    got = m.build_items(html)
    assert {"date": "2026-04-02", "summary": "毎週火曜日",
            "description": "出店者募集中"} in got, got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all chef parse tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_chef_parse.py`
Expected: FAIL — ファイルが存在しない

- [ ] **Step 3: 最小実装を書く**

`calendar/bin/cal-cci-chef-fetch` を作成 (この時点ではパース部のみ。main は Task 5):

```python
#!/usr/bin/env python3
"""cal-cci-chef-fetch — 飯能商工会議所「日替わりシェフレストラン」当番表 → YAML.

Source: https://www.hanno-cci.or.jp/manage/founded/#02

ページの FullCalendar 初期化コードに、全期間の予定が JSON 配列として直接
埋め込まれている:

    events: [{"start":"2026-04-14","title":"浮き雲\\nダルバート（ネパール料理）","allDay":true}, …]

REST API も AJAX も要らず、HTML を 1 回取れば全件得られる。LLM 不使用。

**集合同期型クローラ**である (既存の追記型とは別系統)。取得側に無い予定は
「予定から外れた」と解釈して削除する。削除条件と安全弁は _lib.plan_set_sync()。
設計: docs/superpowers/specs/2026-08-19-schedule-set-sync-design.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (  # noqa: E402
    fetch_with_cache, load_http_cache, save_http_cache,
    load_source_config, normalize_char_width,
    sync_set, SetSyncTooManyDeletions,
    yaml_escape_str, yaml_block_scalar,
)


# ==================== Source ====================
SOURCE_KEY = "cci-chef"

# ==================== Logic ====================

# FullCalendar の設定オブジェクト内の `events: [ … ]`
_EVENTS_RE = re.compile(r"events:\s*\[")

# 区切り: 改行 または 空白 2 個以上 (半角・全角どちらでも)。
# 1 個の全角スペースを区切りにしないのは、"Bouguet　Bagle" のように
# 店名の一部であることがあるため。
_SPLIT_RE = re.compile(r"\n|[ 　]{2,}")


def extract_events_json(html: str) -> list[dict]:
    """FullCalendar の `events:` 配列を取り出す.

    ブラケットの対応を数えて配列の終端を見つける (正規表現では入れ子を扱えない)。
    見つからなければ ValueError — ページ構造の変化を静かに握り潰さない。
    """
    m = _EVENTS_RE.search(html)
    if not m:
        raise ValueError("FullCalendar の events: 配列が見つからない (ページ構造変化の可能性)")
    start = m.end() - 1
    depth = 0
    for i in range(start, len(html)):
        if html[i] == "[":
            depth += 1
        elif html[i] == "]":
            depth -= 1
            if depth == 0:
                return json.loads(html[start:i + 1])
    raise ValueError("events: 配列が閉じていない")


def split_title(title: str) -> tuple[str, list[str]]:
    """title を (店名, [メニュー行…]) に分ける.

    元データは 2 通りのレイアウト規約が混在する:
      - 改行区切り:       "北京ごはん\\n魯肉飯\\nタピオカ"
      - 全角スペース詰め: "N.Teatime　　　日替わりランチ　　　手網焙煎珈琲"

    どちらも「改行 または 空白 2 個以上」で切ると 1 行目が店名になる (実データ
    95 件で検証済み)。あわせて文字種正規化を掛け、表記揺れを減らす。
    """
    parts = [normalize_char_width(p).strip() for p in _SPLIT_RE.split(title)]
    parts = [p for p in parts if p]
    if not parts:
        return "", []
    return parts[0], parts[1:]


def build_items(html: str) -> list[dict]:
    """HTML から sync_set() に渡す items を作る (日付でソート)."""
    items: list[dict] = []
    for ev in extract_events_json(html):
        date = str(ev.get("start", ""))[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        name, menu = split_title(str(ev.get("title", "")))
        if not name:
            continue
        items.append({"date": date, "summary": name, "description": "\n".join(menu)})
    items.sort(key=lambda x: (x["date"], x["summary"]))
    return items
```

- [ ] **Step 4: 実行権限を付けてテストが通ることを確認**

Run: `chmod +x calendar/bin/cal-cci-chef-fetch && python3 calendar/tests/test_chef_parse.py`
Expected: `OK: all chef parse tests passed`

- [ ] **Step 5: 実データで目視確認**

Run:
```bash
python3 - <<'EOF'
import importlib.machinery, importlib.util, urllib.request
loader = importlib.machinery.SourceFileLoader("m", "calendar/bin/cal-cci-chef-fetch")
spec = importlib.util.spec_from_loader("m", loader)
m = importlib.util.module_from_spec(spec); loader.exec_module(m)
req = urllib.request.Request("https://www.hanno-cci.or.jp/manage/founded/",
                             headers={"User-Agent": "Mozilla/5.0"})
html = urllib.request.urlopen(req).read().decode("utf-8", "replace")
items = m.build_items(html)
print(len(items), items[0], items[-1])
EOF
```
Expected: 90 件以上。`{'date': '2026-03-01', 'summary': 'ひだまりCafeほわっと', 'description': ''}` のような形

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/cal-cci-chef-fetch calendar/tests/test_chef_parse.py
git commit -m "feat(calendar): 商工会議所 日替わりシェフ当番表のパーサを追加"
```

---

### Task 5: クローラの main と golden テスト

パース部に取得・YAML 生成・`sync_set()` 呼び出しを繋ぎ、golden で 4 シナリオを固定する。

**Files:**
- Modify: `calendar/bin/cal-cci-chef-fetch`
- Modify: `calendar/sources.yaml`
- Create: `calendar/tests/fixtures/cal-cci-chef-fetch/{page.html,manifest.json}`
- Create: `calendar/tests/seed/cal-cci-chef-{update,delete,keep-past}/`
- Modify: `calendar/tests/run-golden`

**Interfaces:**
- Consumes: `_lib.sync_set`, `_lib.SetSyncTooManyDeletions`, Task 4 の `build_items`
- Produces: `main()` (引数は `sys.argv` から)、`build_yaml_doc(uid, item, source_id, content_hash) -> str`

- [ ] **Step 1: `sources.yaml` に設定を足す**

`calendar/sources.yaml` の末尾に追加:

```yaml
# 飯能商工会議所「日替わりシェフレストラン」当番表。
# **集合同期型** — 1 ページに全期間の予定が JSON で埋め込まれており、取得側に
# 無い予定は削除する (既存の追記型クローラとは別系統)。
cci-chef:
  uid_prefix: chef
  source_type: hanno-cci-chef
  page_url: "https://www.hanno-cci.or.jp/manage/founded/"
  anchor: "02"
  location: "日替わりシェフレストラン"
  url_host_allowlist: www.hanno-cci.or.jp
  max_delete: 10
```

- [ ] **Step 2: fixture を採取する**

Run:
```bash
mkdir -p calendar/tests/fixtures/cal-cci-chef-fetch
curl -sL -A "Mozilla/5.0" "https://www.hanno-cci.or.jp/manage/founded/" \
  -o calendar/tests/fixtures/cal-cci-chef-fetch/page.html
cat > calendar/tests/fixtures/cal-cci-chef-fetch/manifest.json <<'EOF'
{
  "https://www.hanno-cci.or.jp/manage/founded/": "page.html"
}
EOF
```
Expected: `page.html` が 50KB 以上

- [ ] **Step 3: main を実装する**

`calendar/bin/cal-cci-chef-fetch` の末尾に追加:

```python
def build_yaml_doc(uid: str, item: dict, source_id: str, content_hash: str) -> str:
    """1 イベントの YAML 本文を組み立てる (sync_set の render_doc コールバック).

    summary に絵文字 prefix は付けない: 専用カレンダーなので全件同じ prefix に
    なり情報量がない (既存クローラの 📢/🎪/ℹ️/📝 は 1 カレンダーに複数ソースが
    混ざるための識別子)。
    """
    cfg = load_source_config(SOURCE_KEY)
    source_url = f"{cfg['page_url']}#{cfg['anchor']}"

    desc_parts = []
    if item["description"]:
        desc_parts.append(item["description"])
    desc_parts.append(source_url)
    description = "\n\n".join(desc_parts)

    lines = [
        f"uid: {yaml_escape_str(uid)}",
        f"summary: {yaml_escape_str(item['summary'])}",
        f"location: {yaml_escape_str(cfg['location'])}",
        f"url: {yaml_escape_str(source_url)}",
        f"dtstart: {yaml_escape_str(item['date'])}",
        f"dtend: {yaml_escape_str(item['date'])}",
        "description: " + yaml_block_scalar(description, indent=2),
        "",
        "render:",
        "  gcal:",
        "    mode: single-allday",
        "",
        "source:",
        f"  type: {cfg['source_type']}",
        f"  id: {yaml_escape_str(source_id)}",
        f"  url: {yaml_escape_str(source_url)}",
        f"  content_hash: {yaml_escape_str(content_hash)}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    default_out_dir = os.path.join(here, "..", "events")
    cfg = load_source_config(SOURCE_KEY)

    ap = argparse.ArgumentParser(
        description="飯能商工会議所 日替わりシェフレストラン当番表 → YAML (LLM 不使用)")
    ap.add_argument("--out-dir", default=default_out_dir)
    ap.add_argument("--uid-prefix", default=cfg["uid_prefix"])
    ap.add_argument("--dry-run", action="store_true", help="書き込まずに件数だけ出す")
    ap.add_argument("--min-events", type=int, default=20,
                    help="抽出件数がこれ未満なら exit 2 (CI 暴走防止、default: 20)")
    ap.add_argument("--max-delete", type=int, default=cfg.get("max_delete", 10),
                    help="削除がこれを超えたら何も書かずに exit 3")
    ap.add_argument("--today", default=None, help="削除判定の基準日 (テスト用)")
    args = ap.parse_args()

    url = cfg["page_url"]
    host = url.split("/")[2]
    if host != cfg["url_host_allowlist"]:
        sys.exit(f"URL outside allowlist: {url}")

    # HTTP Conditional GET: 304 なら parse も write も全 skip
    http_cache = load_http_cache()
    entry = http_cache.get(url, {})
    html, etag, lm = fetch_with_cache(url, entry.get("etag"), entry.get("last_modified"))
    if html is None:
        print(f"304 not modified, skip: {url}", file=sys.stderr)
        return
    http_cache[url] = {"etag": etag, "last_modified": lm}
    save_http_cache(http_cache)

    items = build_items(html)
    print(f"Extracted {len(items)} events from {url}", file=sys.stderr)
    if len(items) < args.min_events:
        sys.exit(f"only {len(items)} events (< --min-events {args.min_events}); "
                 f"page structure may have changed")

    try:
        stats = sync_set(args.out_dir, args.uid_prefix, items, build_yaml_doc,
                         today=args.today, max_delete=args.max_delete,
                         dry_run=args.dry_run)
    except SetSyncTooManyDeletions as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(3)

    print(f"Done. added={stats['added']} updated={stats['updated']} "
          f"deleted={stats['deleted']} unchanged={stats['unchanged']}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: `run-golden` にシナリオを登録する**

`calendar/tests/run-golden` の `_setup_tourism_news` の後に setup を足す:

```python
def _setup_cci_chef(m, crawler, manifest):
    """HTTP を fixture に差し替え、削除判定の基準日を固定する。

    today を固定しないと、fixture 内の予定が日々「過去」に流れて削除判定が
    変わり、golden が壊れる。
    """
    m.fetch_with_cache = lambda url, etag, lm: (
        (_read_fixture(crawler, manifest[url]), None, None) if url in manifest
        else (None, None, None))
    m.load_http_cache = lambda: {}
    m.save_http_cache = lambda c: None
```

`CRAWLERS` に 4 行追加:

```python
    # 集合同期型。update/delete/keep-past は seed で既存 YAML を置いてから走らせる。
    ("cal-cci-chef-fetch", "cal-cci-chef-fetch", _setup_cci_chef, None),
    ("cal-cci-chef-update", "cal-cci-chef-fetch", _setup_cci_chef, "cal-cci-chef-update"),
    ("cal-cci-chef-delete", "cal-cci-chef-fetch", _setup_cci_chef, "cal-cci-chef-delete"),
    ("cal-cci-chef-keep-past", "cal-cci-chef-fetch", _setup_cci_chef, "cal-cci-chef-keep-past"),
```

`DETERMINISTIC_DATE_CRAWLERS` に `"cal-cci-chef-fetch"` を追加する (dtstart は
ソースの日付そのもので実行日に依存しないため、正規化せず回帰対象にする)。

`_run_crawler` の `sys.argv` 組み立てに `--today` を渡す。`cal-cci-chef-fetch` 以外は
この引数を持たないので、クローラ名で分岐する:

```python
            sys.argv = [crawler, "--out-dir", d]
            if crawler == "cal-cci-chef-fetch":
                # 削除判定の基準日を固定 (fixture の予定が日々過去に流れないように)
                sys.argv += ["--today", "2026-06-01"]
```

- [ ] **Step 5: seed を作る**

```bash
mkdir -p calendar/tests/seed/cal-cci-chef-update/2026 \
         calendar/tests/seed/cal-cci-chef-delete/2026 \
         calendar/tests/seed/cal-cci-chef-keep-past/2026
```

`calendar/tests/seed/cal-cci-chef-update/2026/06-05_chef-20260605-01.yaml`
— fixture 内に実在する日付の YAML を、`summary` と `content_hash` を意図的に
食い違わせて置く (更新経路を通す)。実際の日付は fixture を見て決める:

```bash
python3 - <<'EOF'
import importlib.machinery, importlib.util
loader = importlib.machinery.SourceFileLoader("m", "calendar/bin/cal-cci-chef-fetch")
spec = importlib.util.spec_from_loader("m", loader)
m = importlib.util.module_from_spec(spec); loader.exec_module(m)
html = open("calendar/tests/fixtures/cal-cci-chef-fetch/page.html", encoding="utf-8").read()
items = m.build_items(html)
future = [i for i in items if i["date"] >= "2026-06-01"]
print("最初の未来イベント:", future[0])
print("未来イベント数:", len(future))
EOF
```

上で表示された日付を使って seed を書く。`cal-cci-chef-update` は既存の 1 件を
`summary: "古い名前"` / `content_hash: "sha256-0000000000000000"` にしたもの。

`cal-cci-chef-delete` は、fixture に**存在しない未来日**の YAML を置く:

```yaml
uid: "chef-20260615-01@hanno.city.tecoli.com"
summary: "消えるはずの予定"
location: "日替わりシェフレストラン"
url: "https://www.hanno-cci.or.jp/manage/founded/#02"
dtstart: "2026-06-15"
dtend: "2026-06-15"
description: |-
  https://www.hanno-cci.or.jp/manage/founded/#02

render:
  gcal:
    mode: single-allday

source:
  type: hanno-cci-chef
  id: "20260615-01"
  url: "https://www.hanno-cci.or.jp/manage/founded/#02"
  content_hash: "sha256-1111111111111111"
```

**注意**: `2026-06-15` が fixture 内に実在する日付なら、実在しない未来日に
差し替えること (上のスクリプトで未来イベントの日付一覧を確認する)。

`cal-cci-chef-keep-past` は、fixture に存在しない**過去日** (`2026-03-15` 等、
かつ `--today 2026-06-01` より前で fixture の日付範囲内) の同形 YAML を置く。

- [ ] **Step 6: golden を生成して中身を目視確認**

Run: `python3 calendar/tests/run-golden --update && ls calendar/tests/golden/cal-cci-chef-*`

確認事項:
- `cal-cci-chef-fetch/` に fixture の全イベント分の YAML がある
- `cal-cci-chef-delete/` に `chef-20260615-01.yaml` が**無い** (削除された)
- `cal-cci-chef-keep-past/` に過去日の YAML が**ある** (残った)
- `cal-cci-chef-update/` の該当ファイルが新しい `summary` になっている

- [ ] **Step 7: golden が安定していることを確認**

Run: `python3 calendar/tests/run-golden`
Expected: `All golden checks passed.`

- [ ] **Step 8: コミット**

```bash
git add calendar/bin/cal-cci-chef-fetch calendar/sources.yaml calendar/tests/
git commit -m "feat(calendar): 日替わりシェフ当番表クローラの main と golden テスト"
```

---

### Task 6: `cal-myhanno prune`

YAML に対応が無い Calendar イベントを削除する。**対象の特定は iCalUID の prefix。**
Google 側のイベントは `source.type` を持たないため、prefix が唯一の確実な手掛かり。

**Files:**
- Modify: `calendar/bin/cal-myhanno` (`cmd_wipe` の直後に `cmd_prune`、arg parser に登録)

**Interfaces:**
- Consumes: `list_all_events`, `load_yaml`, `cmd_snapshot`, `CALENDARS`
- Produces: `cal-myhanno prune --uid-prefix <prefix> [-d events] [--dry-run] [--max-delete N]`

- [ ] **Step 1: `cmd_prune` を実装する**

`calendar/bin/cal-myhanno` の `cmd_wipe` の直後に追加:

```python
# ---------- prune: delete calendar events whose YAML is gone ----------


def cmd_prune(args: argparse.Namespace) -> None:
    """YAML に対応が無い Calendar イベントを削除する (UID prefix 限定).

    集合同期型クローラ (cal-cci-chef-fetch 等) が YAML を消したとき、その削除を
    Calendar まで通すための経路。apply-all は insert/update しか行わないので、
    これが無いと消したはずの予定がカレンダーに残り続ける。

    **CI では fetch --update-manual より前に実行しなければならない。** 後に置くと、
    Calendar に残った孤児を fetch が source: なしの YAML として拾い、以後
    「手動キュレーション = 不可侵」扱いになって二度と消せなくなる。

    --uid-prefix は必須。指定しない限り 1 件も消えない (既存カレンダーへの誤爆を
    構造的に防ぐ)。prefix が一致しないイベント (= 手で足した予定) は対象外。
    """
    import glob
    prefix = args.uid_prefix + "-"

    pattern = os.path.join(args.events_dir, "**", "*.yaml")
    yaml_uids = set()
    for f in sorted(glob.glob(pattern, recursive=True)):
        uid = (load_yaml(f) or {}).get("uid")
        if uid:
            yaml_uids.add(uid)

    targets: list[tuple[str, str, dict]] = []   # (cal_key, cal_id, event)
    for cal_key, cal_id_val in CALENDARS.items():
        for e in list_all_events(cal_id_val):
            uid = e.get("iCalUID")
            if not uid or not uid.startswith(prefix):
                continue
            if uid in yaml_uids:
                continue
            targets.append((cal_key, cal_id_val, e))

    if not targets:
        print(f"prune: nothing to delete (uid prefix '{args.uid_prefix}')")
        return

    print(f"prune: {len(targets)} orphan event(s) with uid prefix '{args.uid_prefix}'")
    for cal_key, _, e in targets:
        print(f"  [{cal_key}] {e.get('iCalUID')}  {e.get('summary','')[:40]}")

    if len(targets) > args.max_delete:
        die(f"{len(targets)} deletions exceed --max-delete {args.max_delete}; refusing")

    if args.dry_run:
        print("dry-run: nothing deleted")
        return

    print(f"\n=== taking pre-prune snapshot to {args.snapshot_dir}/ ===")
    cmd_snapshot(argparse.Namespace(output=args.snapshot_dir))

    # gws delete は cwd に download.html を書く副作用がある — /tmp で実行
    orig_cwd = os.getcwd()
    ok = err = 0
    try:
        os.chdir("/tmp")
        for cal_key, cal_id_val, e in targets:
            cmd = ["gws", "calendar", "events", "delete",
                   "--params", json.dumps({"calendarId": cal_id_val, "eventId": e["id"]}),
                   "--format", "json"]
            p = subprocess.run(cmd, capture_output=True, text=True)
            if p.returncode != 0:
                err += 1
                print(f"  DELETE FAIL  [{cal_key}] {e.get('iCalUID')}: {p.stderr.strip()[:200]}")
            else:
                ok += 1
                print(f"  DELETED  [{cal_key}] {e.get('iCalUID')}")
    finally:
        os.chdir(orig_cwd)
        try:
            os.remove("/tmp/download.html")
        except FileNotFoundError:
            pass

    print(f"\nsummary: deleted={ok}  failed={err}  total={len(targets)}")
    if err:
        sys.exit(1)
```

- [ ] **Step 2: arg parser に登録する**

`calendar/bin/cal-myhanno` の `wipe` の `add_parser` の直後に追加:

```python
    sp = sub.add_parser("prune",
        help="YAML に無い Calendar event を削除 (--uid-prefix で対象を限定、必須)")
    sp.add_argument("--uid-prefix", required=True,
                    help="対象の iCalUID prefix (例: chef)。必須 — 誤爆防止")
    sp.add_argument("-d", "--events-dir", default="events", help="events directory")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--max-delete", type=int, default=10,
                    help="削除がこれを超えたら中止 (default: 10)")
    sp.add_argument("--snapshot-dir", default="snapshots",
                    help="削除前 snapshot の出力先 (default: snapshots)")
    sp.set_defaults(func=cmd_prune)
```

- [ ] **Step 3: `--uid-prefix` が必須であることを確認**

Run: `./calendar/bin/cal-myhanno prune 2>&1 | head -3`
Expected: `error: the following arguments are required: --uid-prefix`

- [ ] **Step 4: dry-run で誤爆しないことを確認**

Run: `GOOGLE_APPLICATION_CREDENTIALS=~/.config/myhanno/sa.json ./calendar/bin/cal-myhanno prune --uid-prefix chef -d calendar/events --dry-run`
Expected: `prune: nothing to delete (uid prefix 'chef')` — この時点で `chef-*` のイベントはまだカレンダーに存在しない

- [ ] **Step 5: 既存カレンダーに影響が無いことを確認**

Run: `GOOGLE_APPLICATION_CREDENTIALS=~/.config/myhanno/sa.json ./calendar/bin/cal-myhanno diff -d calendar/events; echo "exit=$?"`
Expected: `exit=0` (in sync)。prune の追加で既存の diff 判定が変わっていないこと

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/cal-myhanno
git commit -m "feat(calendar): cal-myhanno prune を追加 (UID prefix 限定の孤児削除)"
```

---

### Task 7: routing と英訳除外

**Files:**
- Modify: `calendar/bin/cal-myhanno` (`CALENDARS` 42 行目付近、`SOURCE_TYPE_TO_CALENDAR` 53 行目付近)
- Modify: `calendar/bin/cal-translate-en`

**Interfaces:**
- Consumes: Task 5 が生成する `source.type: hanno-cci-chef` の YAML
- Produces: `chef` カレンダーへの routing、`hanno-cci-chef` の翻訳スキップ

- [ ] **Step 1: `CALENDARS` に `chef` を足す**

`calendar/bin/cal-myhanno`:

```python
CALENDARS: dict[str, str] = {
    ...
    # 飯能商工会議所「日替わりシェフレストラン」当番表。
    # tecolicom@gmail.com 所有、city-tecoli のアプリが商工会議所の店舗ページ
    # (place_id: ChIJ_aM0DDcmGWAR3KV7H6eOrIs) から作成したもの。
    # EN 版は作らない: 店舗ページに i18n が無く、読む場所が存在しないため。
    "chef": "ae1577f36d2b51db208baec59cc84e90ceab25d41bad166b42c37fb7063f4a46@group.calendar.google.com",
}
```

- [ ] **Step 2: routing を足す**

```python
SOURCE_TYPE_TO_CALENDAR: dict[str, str] = {
    "city-hanno-gikai":       "gikai",
    "city-hanno-shicho-blog": "gikai",
    "city-hanno-oshirase":    "gikai",
    "hanno-cci-chef":         "chef",
}
```

- [ ] **Step 3: `--lang en` が `chef` を巻き込まないことを確認**

`cmd_diff` / `cmd_apply_all` は `lang == "default"` のとき `[k for k in CALENDARS if "." not in k]` を対象にするので、`chef` は JP 側にだけ入り、`en` 側には `chef.en` が無いので現れない。

Run: `GOOGLE_APPLICATION_CREDENTIALS=~/.config/myhanno/sa.json ./calendar/bin/cal-myhanno diff -d calendar/events --lang en; echo "exit=$?"`
Expected: `exit=0`。出力に `chef` が現れないこと

- [ ] **Step 4: `cal-translate-en` に除外を足す**

まず module scope (定数定義のあたり、`EN_DISCLAIMER` の近く) に追加:

```python
# 翻訳しない source.type。EN カレンダーを持たない (= 訳しても読む場所が無い)
# ソースを除外する。書かないと translations.en.* が付き、毎日 LLM を無駄に呼ぶ。
NO_TRANSLATION_SOURCE_TYPES = frozenset({"hanno-cci-chef"})
```

次に走査ループ内。`calendar/bin/cal-translate-en:292` の `only_uid` チェックの
直後に挿入する (既存コードの変数名は `doc` / `path` / `skipped`):

```python
        if args.only_uid and doc.get("uid") != args.only_uid:
            continue
        # ↓ ここに追加
        if (doc.get("source") or {}).get("type") in NO_TRANSLATION_SOURCE_TYPES:
            skipped += 1
            continue
        summary = doc.get("summary", "")
```

`translation_hash` の計算より前に置くこと。後ろに置くと、既に `translations.en`
が付いてしまった YAML を rehash してしまう。

- [ ] **Step 5: 翻訳がスキップされることを確認**

Run: `./calendar/bin/cal-translate-en --events-dir calendar/events 2>&1 | tail -3`
Expected: `translated=0` (chef の YAML がまだ無いか、あってもスキップされる)。
`ANTHROPIC_API_KEY` 未設定でも skip 扱いで exit 0 になる

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/cal-myhanno calendar/bin/cal-translate-en
git commit -m "feat(calendar): chef カレンダーの routing と英訳除外"
```

---

### Task 8: CI 配線とドキュメント

**ステップの順序が設計の一部。** prune は `fetch --update-manual` より**前**でなければならない (蘇生ループの防止)。

**Files:**
- Modify: `.github/workflows/cal-daily.yml`
- Modify: `.github/workflows/cal-golden-test.yml`
- Modify: `README.md`
- Modify: `calendar/README.md`

**Interfaces:**
- Consumes: Task 5 の `cal-cci-chef-fetch`、Task 6 の `cal-myhanno prune`
- Produces: なし (最終タスク)

- [ ] **Step 1: `cal-daily.yml` に crawl と prune を足す**

`Crawl city-hanno-oshirase` ステップの後、`Fetch manual Calendar additions` ステップの**前**に挿入:

```yaml
      - name: Crawl hanno-cci-chef
        # 集合同期型。取得側に無い予定は YAML から削除される (削除ガードは
        # _lib.plan_set_sync: 取得範囲内かつ今日以降のみ、上限超過で中止)。
        run: ./calendar/bin/cal-cci-chef-fetch --out-dir calendar/events --min-events 20 || echo "hanno-cci-chef" >> "$RUNNER_TEMP/crawl-failures.txt"

      - name: Prune removed chef events from Calendar
        # **このステップは次の "Fetch manual Calendar additions" より前でなければ
        # ならない。** 後ろに置くと、YAML を消したのに Calendar に残った孤児を
        # fetch --update-manual が source: なしの YAML として拾い、以後
        # 「手動キュレーション = 不可侵」扱いになって二度と削除できなくなる。
        env:
          GOOGLE_APPLICATION_CREDENTIALS: /tmp/sa.json
        run: ./calendar/bin/cal-myhanno prune --uid-prefix chef -d calendar/events --snapshot-dir calendar/snapshots
```

- [ ] **Step 2: 順序を目視で確認**

Run: `grep -n "name: Crawl\|name: Prune\|name: Fetch manual" .github/workflows/cal-daily.yml`
Expected: `Prune removed chef events` の行番号が `Fetch manual Calendar additions` より小さいこと

- [ ] **Step 3: `cal-golden-test.yml` でユニットテストも走らせる**

現状このワークフローは `run-golden` しか実行しておらず、`calendar/tests/test_*.py` は
CI で一度も走っていない。本設計の安全性は `plan_set_sync` のユニットテストに
依存しているので、走らせる。`Run golden test` ステップの後に追加:

```yaml
      - name: Run unit tests
        # test_*.py は個別に自己実行できる (pytest 非依存)。golden 網とは別に
        # 純粋関数を検証しており、集合同期の削除ガードもここで守られている。
        run: |
          fail=0
          for t in calendar/tests/test_*.py; do
            echo "--- $t"
            python3 "$t" || fail=1
          done
          exit $fail
```

- [ ] **Step 4: ローカルで同じことを実行して通ることを確認**

Run:
```bash
fail=0; for t in calendar/tests/test_*.py; do echo "--- $t"; python3 "$t" || fail=1; done; echo "fail=$fail"
```
Expected: `fail=0`

- [ ] **Step 5: `calendar/README.md` を更新する**

「ディレクトリ構成」の `bin/` 一覧に追加:

```
│   ├── cal-cci-chef-fetch       飯能商工会議所 日替わりシェフ当番表、集合同期型 (LLM 不使用)
```

「カレンダー構成」の表に行を追加:

```
| `chef` | 日替わりシェフレストラン | 商工会議所の当番表 (EN なし) | hanno-cci-chef |
```

`bin/_lib.py` のヘルパ表に行を追加:

```
| 集合同期 | `plan_set_sync(existing, incoming, dates, today, max_delete)` — 削除可否の判定 (純粋関数) / `sync_set(out_dir, uid_prefix, items, render_doc, …)` — その実行 / `set_sync_uid` / `set_sync_hash` / `SetSyncTooManyDeletions` |
| 文字種正規化 | `normalize_char_width(s)` — 全角 ASCII → 半角、半角カナ → 全角 (括弧と U+3000 は保つ) |
```

「テスト (golden 網)」の節に、追加した 4 シナリオと 4 つのユニットテストを列挙する。

さらに「クローラの 2 系統」という節を新設し、追記型と集合同期型の違い、および
**prune を `fetch --update-manual` より前に置かねばならない理由**を書く。設計書
`docs/superpowers/specs/2026-08-19-schedule-set-sync-design.md` へリンクする。

- [ ] **Step 6: ルート `README.md` を更新する**

「Myはんのうカレンダー」節の「主なソース」に追加:

```
- **飯能商工会議所 / 日替わりシェフレストラン** (`cal-cci-chef-fetch`): 当番表を集合として同期する新系統。ページに埋め込まれた FullCalendar の JSON を決定論パース (LLM 不使用)。取得側に無い予定は削除する (取得範囲内かつ今日以降のみ、上限超過で中止)
```

CI 自動化の節の `cal-daily.yml` の説明に、prune が `fetch --update-manual` より前に
入ることを追記する。

- [ ] **Step 7: 最終確認**

Run:
```bash
python3 calendar/tests/run-golden && \
for t in calendar/tests/test_*.py; do python3 "$t" || exit 1; done && \
echo "ALL GREEN"
```
Expected: `ALL GREEN`

- [ ] **Step 8: コミット**

```bash
git add .github/workflows/cal-daily.yml .github/workflows/cal-golden-test.yml README.md calendar/README.md
git commit -m "ci+docs: 集合同期型クローラの CI 配線とドキュメント"
```

---

## 実装後の初回反映 (手動で行う)

CI 任せにせず、初回だけは目で確認する。

1. **ローカルで dry-run**

```bash
./calendar/bin/cal-cci-chef-fetch --out-dir calendar/events --dry-run
```
95 件前後が `added` になることを確認する。

2. **実際に生成して差分を読む**

```bash
./calendar/bin/cal-cci-chef-fetch --out-dir calendar/events
git status --short calendar/events | head -20
git diff --stat calendar/events
```

3. **Calendar への反映を dry-run で確認**

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/myhanno/sa.json
rm -f ~/.config/gws/sa_token_cache.json   # 古いトークンで source が欠ける既知の罠
./calendar/bin/cal-myhanno diff -d calendar/events
./calendar/bin/cal-myhanno apply-all -d calendar/events --only-managed --dry-run
```

4. **反映**

```bash
./calendar/bin/cal-myhanno apply-all -d calendar/events --only-managed
./calendar/bin/cal-myhanno diff -d calendar/events
```

5. **店舗ページで表示を確認**

`https://city.tecoli.com/shop/ChIJ_aM0DDcmGWAR3KV7H6eOrIs/?cb=1`
— キャッシュで古い内容が出ることがあるので `?cb=` を付ける。

6. **コミットして push**

```bash
git add calendar/events calendar/.http-cache.json
git commit -m "calendar: 日替わりシェフレストラン当番表の初回取込"
```
