# apply-all の高速化と events.list ページング対応 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cal-myhanno apply-all` が YAML 1 件ごとに `events.list` を呼ぶのをやめ、カレンダー単位の一括取得 + 索引引きに置き換えて、日次 CI の apply (135 秒) を数秒台にする。

**Architecture:** ページング対応の共通取得 `list_all_events()` を作り、既存 4 箇所の `maxResults:500` 固定・ページング未処理も同時に解消する。その上に `EventIndex`（カレンダー別 uid→event 索引）を載せ、`cmd_apply` が索引を任意で受け取れるようにする。索引は実行開始時のスナップショットなので、実際に書き込むイベントだけ直前に 1 件取り直して競合窓を塞ぐ。

**Tech Stack:** Python 3（標準ライブラリのみ + PyYAML）、`gws` CLI 経由の Google Calendar API

**Spec:** `docs/superpowers/specs/2026-08-08-calendar-apply-speedup-design.md`

## Global Constraints

- **`gws --page-all` は使わない。** 出力が NDJSON になり既存 `gws()` で扱えず、`--page-limit` 既定 10 での静かな切り捨てという、今直しているのと同種の依存を増やすため。手動 `nextPageToken` ループを使う。
- `maxResults` は **2500**（Calendar API の上限。既定 250）。
- **`--dry-run` では書き込み前の再確認をしない。** 書かないので不要で、計測もぶれない。
- **書き込み後に索引を更新しない。** 1 回の `apply-all` で同じ uid は 1 度しか処理されない。
- `cmd_apply` 単体経路（`apply <file>`）の挙動は変えない。索引が無ければ従来どおり `find_event_by_uid()`。
- コメント・docstring は既存コードと同じく日本語。
- ローカルで実 API を叩くときは CI と同じ経路でサービスアカウントを渡すこと:
  `export GOOGLE_APPLICATION_CREDENTIALS=/Users/utashiro/Git/tecolicom/city-tecoli/city-tecoli-f79904a70941.json`
  （未指定だとユーザー OAuth にフォールバックして `invalid_grant: invalid_rapt` で失敗する）
- `gws` は起動時に `Using keyring backend: keyring` を **stderr** に出す。`gws()` は `capture_output=True` で分離しているので実害はないが、手で叩いて JSON をパースするときに `2>&1` すると壊れる。

## 実機で検証済みの前提（2026-08-08、`gikai` 248 件）

| 前提 | 結果 |
|---|---|
| `gws` のレスポンスに `nextPageToken` が含まれる | ✅ トップレベルキーに存在 |
| `pageToken` を渡すと次ページが取れる | ✅ 2 ページ目に別イベント、`nextPageToken` も継続 |
| `maxResults: 2500` なら現状 1 ページで収まる | ✅ 248 件を 1 ページ、`nextPageToken` なし |

## テストの土台

`cal-myhanno` には現在テストが 1 本も無い。全タスクで以下のローダを使う（実機で読み込み確認済み）:

```python
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_myhanno",
                                              os.path.join(BIN, "cal-myhanno"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
```

`mod.gws` を差し替えればネットワークに出ない。

---

### Task 1: `list_all_events()` を作り、既存 4 箇所の切り捨てを解消する

**Files:**
- Modify: `calendar/bin/cal-myhanno` （`find_event_by_uid` の直前に追加 + 4 箇所を置換）
- Create: `calendar/tests/test_calendar_paging.py`

**Interfaces:**
- Consumes: `gws(*args, params=...)`（既存）
- Produces: `list_all_events(calendar_id: str) -> list[dict]`

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_calendar_paging.py`:

```python
#!/usr/bin/env python3
"""cal-myhanno の events.list ページングのユニットテスト。gws を差し替えるので
ネットワーク非依存。
実行: python3 calendar/tests/test_calendar_paging.py
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_myhanno",
                                              os.path.join(BIN, "cal-myhanno"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


class FakeGws:
    """pages: [(items, next_token)] を順に返す gws のフェイク。"""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []          # 各呼び出しの params を記録

    def __call__(self, *args, params=None, body=None):
        self.calls.append(params)
        items, token = self.pages[len(self.calls) - 1]
        res = {"items": items}
        if token:
            res["nextPageToken"] = token
        return res


def _ev(uid):
    return {"iCalUID": uid, "id": uid.replace("@", "_")}


def test_single_page():
    fake = FakeGws([([_ev("a@x"), _ev("b@x")], None)])
    mod.gws = fake
    got = mod.list_all_events("cal-1")
    assert [e["iCalUID"] for e in got] == ["a@x", "b@x"]
    assert len(fake.calls) == 1
    assert "pageToken" not in fake.calls[0]


def test_empty():
    fake = FakeGws([([], None)])
    mod.gws = fake
    assert mod.list_all_events("cal-1") == []


def test_follows_next_page_token():
    fake = FakeGws([
        ([_ev("a@x")], "TOK1"),
        ([_ev("b@x")], "TOK2"),
        ([_ev("c@x")], None),
    ])
    mod.gws = fake
    got = mod.list_all_events("cal-1")
    assert [e["iCalUID"] for e in got] == ["a@x", "b@x", "c@x"]
    assert len(fake.calls) == 3
    assert "pageToken" not in fake.calls[0]
    assert fake.calls[1]["pageToken"] == "TOK1"
    assert fake.calls[2]["pageToken"] == "TOK2"


def test_does_not_truncate_beyond_500():
    """現行バグの回帰テスト: maxResults:500 固定 + ページング未処理で
    501 件目以降を静かに切り捨てていた。"""
    page1 = [_ev(f"e{i}@x") for i in range(500)]
    page2 = [_ev(f"e{i}@x") for i in range(500, 620)]
    fake = FakeGws([(page1, "TOK1"), (page2, None)])
    mod.gws = fake
    got = mod.list_all_events("cal-1")
    assert len(got) == 620
    assert got[-1]["iCalUID"] == "e619@x"


def test_request_params():
    fake = FakeGws([([], None)])
    mod.gws = fake
    mod.list_all_events("cal-42")
    p = fake.calls[0]
    assert p["calendarId"] == "cal-42"
    assert p["maxResults"] == 2500      # Calendar API の上限
    assert p["singleEvents"] is False
    assert p["showDeleted"] is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all calendar-paging tests passed")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_calendar_paging.py`
Expected: FAIL — `AttributeError: module 'cal_myhanno' has no attribute 'list_all_events'`

- [ ] **Step 3: `list_all_events()` を実装する**

`calendar/bin/cal-myhanno` の `def find_event_by_uid(` の直前に追加:

```python
def list_all_events(calendar_id: str) -> list[dict]:
    """指定カレンダーの全イベントを nextPageToken を辿って取得する。

    maxResults は Calendar API の上限 2500 (既定 250)。現在の最大カレンダーは
    248 件なので通常 1 ページで収まるが、増えても取りこぼさないようページングする。
    従来は各所が maxResults:500 固定で nextPageToken を見ておらず、501 件目以降を
    静かに切り捨てていた。

    gws --page-all は使わない: 出力が NDJSON になり gws() で扱えず、--page-limit
    既定 10 に達すると同じく静かに切り捨てるため。
    """
    params: dict[str, Any] = {
        "calendarId": calendar_id,
        "singleEvents": False,
        "maxResults": 2500,
        "showDeleted": False,
    }
    items: list[dict] = []
    while True:
        res = gws("calendar", "events", "list", params=params)
        items.extend(res.get("items", []))
        token = res.get("nextPageToken")
        if not token:
            return items
        params["pageToken"] = token
```

- [ ] **Step 4: テストを実行して通ることを確認**

Run: `python3 calendar/tests/test_calendar_paging.py`
Expected: PASS — `OK: all calendar-paging tests passed`

- [ ] **Step 5: `cmd_fetch` の取得を置き換える**

`calendar/bin/cal-myhanno` の `cmd_fetch` 内:

```python
    items = gws("calendar", "events", "list", params={
        "calendarId": cal_id(),
        "singleEvents": False,
        "maxResults": 500,
        "showDeleted": False,
    }).get("items", [])
```

を以下に置換:

```python
    items = list_all_events(cal_id())
```

- [ ] **Step 6: `cmd_diff` の取得を置き換える**

`calendar/bin/cal-myhanno` の `cmd_diff` 内:

```python
        res = gws("calendar", "events", "list", params={
            "calendarId": cal_id_val, "singleEvents": False, "maxResults": 500, "showDeleted": False,
        })
        cal_events = res.get("items", [])
```

を以下に置換:

```python
        cal_events = list_all_events(cal_id_val)
```

- [ ] **Step 7: `cmd_snapshot` の取得を置き換える**

`calendar/bin/cal-myhanno` の `cmd_snapshot` 内:

```python
        res = gws("calendar", "events", "list", params={
            "calendarId": cal_id_val,
            "singleEvents": False,
            "maxResults": 500,
            "showDeleted": False,
        })
        items = res.get("items", [])
```

を以下に置換:

```python
        items = list_all_events(cal_id_val)
```

- [ ] **Step 8: `cmd_wipe` の取得を置き換える**

`calendar/bin/cal-myhanno` の `cmd_wipe` 内:

```python
    res = gws("calendar", "events", "list", params={
        "calendarId": cal_id(),
        "singleEvents": False,
        "maxResults": 500,
        "showDeleted": False,
    })
    items = res.get("items", [])
```

を以下に置換:

```python
    items = list_all_events(cal_id())
```

- [ ] **Step 9: `maxResults: 500` が残っていないことを確認**

Run: `grep -n 'maxResults' calendar/bin/cal-myhanno`
Expected: 2 行のみ。`list_all_events` の `"maxResults": 2500` と、`cmd_find` の `"maxResults": args.max_results`（ユーザ指定の検索件数なので対象外）。`500` は 1 つも残っていないこと。

- [ ] **Step 10: 実 API に対して snapshot が壊れていないことを確認**

Run:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/Users/utashiro/Git/tecolicom/city-tecoli/city-tecoli-f79904a70941.json
python3 calendar/bin/cal-myhanno snapshot -o calendar/snapshots
git status --porcelain calendar/snapshots/
```
Expected: 4 カレンダー分の件数が表示され、`git status` は空（= 既存 snapshot とバイト一致）。

- [ ] **Step 11: Commit**

```bash
git add calendar/bin/cal-myhanno calendar/tests/test_calendar_paging.py
git commit -m "fix(cal): events.list をページング対応の共通ヘルパに集約

4 箇所すべてが maxResults:500 固定で nextPageToken を見ておらず、
501 件目以降を静かに切り捨てていた (現在の最大は gikai の 248 件)。

list_all_events() を追加して cmd_fetch / cmd_diff / cmd_snapshot / cmd_wipe を
これに寄せる。maxResults は API 上限の 2500。"
```

---

### Task 2: 判定とマージを純粋関数に切り出す

`cmd_apply` に索引と再確認を入れる前に、比較とマージのロジックを取り出しておく。
Task 4 で再確認のたびに同じ判定を使うので、重複を避けるための準備。**挙動は変えない。**

**Files:**
- Modify: `calendar/bin/cal-myhanno`（`COMPARE_FIELDS` / `normalize_for_diff` の直後に追加、`cmd_apply` から呼ぶ）
- Create: `calendar/tests/test_apply_helpers.py`

**Interfaces:**
- Consumes: `COMPARE_FIELDS`, `normalize_for_diff()`, `READ_ONLY_FIELDS`（すべて既存）
- Produces:
  - `events_in_sync(existing: dict, new_body: dict) -> bool`
  - `merge_for_update(existing: dict, new_body: dict) -> dict`

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_apply_helpers.py`:

```python
#!/usr/bin/env python3
"""cal-myhanno の apply 判定・マージ関数のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_apply_helpers.py
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_myhanno",
                                              os.path.join(BIN, "cal-myhanno"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def _existing(**over):
    e = {
        "id": "evt1",
        "etag": '"abc"',
        "iCalUID": "u@x",
        "summary": "タイトル",
        "description": "本文",
        "start": {"date": "2026-08-08"},
        "end": {"date": "2026-08-08"},
        "source": {"title": "src", "url": "https://e.com/a"},
    }
    e.update(over)
    return e


def _new_body(**over):
    b = {
        "summary": "タイトル",
        "description": "本文",
        "start": {"date": "2026-08-08"},
        "end": {"date": "2026-08-08"},
        "source": {"title": "src", "url": "https://e.com/a"},
    }
    b.update(over)
    return b


def test_in_sync_when_identical():
    assert mod.events_in_sync(_existing(), _new_body()) is True


def test_not_in_sync_when_description_differs():
    assert mod.events_in_sync(_existing(), _new_body(description="別の本文")) is False


def test_in_sync_ignores_read_only_fields():
    # etag / id が違っても COMPARE_FIELDS 外なので in-sync
    assert mod.events_in_sync(_existing(etag='"zzz"', id="other"), _new_body()) is True


def test_in_sync_treats_missing_and_empty_as_same():
    # location は両方とも未設定 (normalize_for_diff が None と "" を同一視)
    assert mod.events_in_sync(_existing(location=""), _new_body()) is True


def test_merge_drops_read_only_fields():
    merged = mod.merge_for_update(_existing(), _new_body(summary="新タイトル"))
    for k in mod.READ_ONLY_FIELDS:
        assert k not in merged, f"{k} should be dropped"
    assert merged["summary"] == "新タイトル"


def test_merge_clears_fields_absent_from_new_body():
    # Calendar 側に location があり YAML に無い → 消す
    existing = _existing(location="飯能市役所")
    merged = mod.merge_for_update(existing, _new_body())
    assert "location" not in merged


def test_merge_keeps_unrelated_existing_fields():
    existing = _existing(colorId="5")
    merged = mod.merge_for_update(existing, _new_body())
    assert merged["colorId"] == "5"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all apply-helper tests passed")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_apply_helpers.py`
Expected: FAIL — `AttributeError: module 'cal_myhanno' has no attribute 'events_in_sync'`

- [ ] **Step 3: 2 つの純粋関数を追加する**

`calendar/bin/cal-myhanno` の `def normalize_for_diff(v):` 定義の直後に追加:

```python
def events_in_sync(existing: dict, new_body: dict) -> bool:
    """既存イベントと新 body が実質同じか判定する。

    判定基準は COMPARE_FIELDS + normalize_for_diff で、cmd_diff が exit 0 を返す
    状態と一致させる (= 真の差分が無ければ events.update を呼ばず、Calendar の
    updated timestamp を bump させない / quota も使わない)。
    """
    return all(normalize_for_diff(existing.get(k)) == normalize_for_diff(new_body.get(k))
               for k in COMPARE_FIELDS)


def merge_for_update(existing: dict, new_body: dict) -> dict:
    """既存イベントに新 body を上書きした events.update 用の body を作る。

    YAML が真なので、YAML に無いフィールドは明示的に消す (Calendar 側にだけ
    location が残る等を防ぐ)。READ_ONLY_FIELDS は API が受け付けないので落とす。
    """
    merged = {k: v for k, v in existing.items() if k not in READ_ONLY_FIELDS}
    merged.update(new_body)
    for k in ("location", "description", "recurrence", "source"):
        if k not in new_body and k in merged:
            merged.pop(k, None)
    return merged
```

- [ ] **Step 4: テストを実行して通ることを確認**

Run: `python3 calendar/tests/test_apply_helpers.py`
Expected: PASS — `OK: all apply-helper tests passed`

- [ ] **Step 5: `cmd_apply` から新関数を呼ぶ（挙動不変）**

`calendar/bin/cal-myhanno` の `cmd_apply` 内、`if existing:` ブロック冒頭のこの部分:

```python
    if existing:
        # update: 既存 body を新 body で上書き (YAML が真)
        merged = {k: v for k, v in existing.items() if k not in READ_ONLY_FIELDS}
        merged.update(new_body)
        # YAML に無いフィールドは消す対象なので明示クリア
        # location 等はもし YAML に無くて Calendar に有ったら、削除すべき
        # (今は location/description のみ対象とする)
        for k in ("location", "description", "recurrence", "source"):
            if k not in new_body and k in merged:
                merged.pop(k, None)

        # 冪等性チェック: cmd_diff と同じ判定方式で existing vs new_body を比較し、
        # 真の差分が無ければ events.update API を呼ばない (= Calendar の updated
        # timestamp を bump させない、quota も消費しない)。
        # cmd_diff が exit 0 を返す状態とこの skip 条件が一致するように、
        # 判定基準は COMPARE_FIELDS + normalize_for_diff (cmd_diff と同一) を使う。
        if all(normalize_for_diff(existing.get(k)) == normalize_for_diff(new_body.get(k))
               for k in COMPARE_FIELDS):
```

を以下に置換:

```python
    if existing:
        merged = merge_for_update(existing, new_body)
        if events_in_sync(existing, new_body):
```

- [ ] **Step 6: 挙動が変わっていないことを実 API で確認**

Run:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/Users/utashiro/Git/tecolicom/city-tecoli/city-tecoli-f79904a70941.json
python3 calendar/bin/cal-myhanno apply-all -d calendar/events --only-managed --dry-run 2>&1 | tail -3
```
Expected: `summary: imported=0 updated=0 in-sync=383 no-translation=0 err=0 no-source=54 total=437` の形。
**`updated=0`（前回の遡及分は既に反映済みなので 0）で、`err=0` であること。** 件数の内訳が
`in-sync` に寄っていれば挙動不変。`updated` が 2 桁以上出たら判定ロジックが壊れている。

- [ ] **Step 7: 全テストを回す**

Run: `python3 calendar/tests/test_apply_helpers.py && python3 calendar/tests/test_calendar_paging.py && python3 calendar/tests/run-golden 2>&1 | tail -2`
Expected: すべて PASS

- [ ] **Step 8: Commit**

```bash
git add calendar/bin/cal-myhanno calendar/tests/test_apply_helpers.py
git commit -m "refactor(cal): apply の同期判定とマージを純粋関数に切り出す

events_in_sync() / merge_for_update() を抽出。cmd_apply の挙動は不変で、
書き込み前の再確認で同じ判定を使い回すための準備。"
```

---

### Task 3: `EventIndex`（カレンダー別 uid → event 索引）

**Files:**
- Modify: `calendar/bin/cal-myhanno`（`list_all_events` の直後に追加）
- Create: `calendar/tests/test_event_index.py`

**Interfaces:**
- Consumes: `list_all_events(calendar_id: str) -> list[dict]`（Task 1）
- Produces: `EventIndex` — メソッドは `get(calendar_id: str, uid: str) -> dict | None` のみ

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_event_index.py`:

```python
#!/usr/bin/env python3
"""cal-myhanno の EventIndex のユニットテスト。list_all_events を差し替えるので
ネットワーク非依存。
実行: python3 calendar/tests/test_event_index.py
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_myhanno",
                                              os.path.join(BIN, "cal-myhanno"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


class FakeList:
    """calendar_id → events を返す list_all_events のフェイク。呼び出しを記録する。"""

    def __init__(self, by_cal):
        self.by_cal = by_cal
        self.calls = []

    def __call__(self, calendar_id):
        self.calls.append(calendar_id)
        return self.by_cal.get(calendar_id, [])


def _ev(uid, **over):
    e = {"iCalUID": uid, "id": uid.replace("@", "_"), "summary": uid}
    e.update(over)
    return e


def test_get_returns_event_by_uid():
    mod.list_all_events = FakeList({"cal-A": [_ev("a@x"), _ev("b@x")]})
    idx = mod.EventIndex()
    got = idx.get("cal-A", "b@x")
    assert got is not None
    assert got["iCalUID"] == "b@x"


def test_get_returns_none_for_unknown_uid():
    mod.list_all_events = FakeList({"cal-A": [_ev("a@x")]})
    idx = mod.EventIndex()
    assert idx.get("cal-A", "nosuch@x") is None


def test_fetches_each_calendar_only_once():
    fake = FakeList({"cal-A": [_ev("a@x"), _ev("b@x")]})
    mod.list_all_events = fake
    idx = mod.EventIndex()
    idx.get("cal-A", "a@x")
    idx.get("cal-A", "b@x")
    idx.get("cal-A", "nosuch@x")
    assert fake.calls == ["cal-A"]      # 3 回引いても fetch は 1 回


def test_fetches_each_calendar_separately():
    fake = FakeList({"cal-A": [_ev("a@x")], "cal-B": [_ev("b@x")]})
    mod.list_all_events = fake
    idx = mod.EventIndex()
    assert idx.get("cal-A", "a@x") is not None
    assert idx.get("cal-B", "b@x") is not None
    assert idx.get("cal-A", "b@x") is None      # カレンダーをまたがない
    assert sorted(fake.calls) == ["cal-A", "cal-B"]


def test_skips_events_without_ical_uid():
    fake = FakeList({"cal-A": [{"id": "no-uid", "summary": "手動作成"}, _ev("a@x")]})
    mod.list_all_events = fake
    idx = mod.EventIndex()
    assert idx.get("cal-A", "a@x") is not None
    # uid 無しイベントで索引が壊れていないこと (例外が出ないこと自体が検証)


def test_empty_calendar():
    mod.list_all_events = FakeList({})
    idx = mod.EventIndex()
    assert idx.get("cal-empty", "a@x") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all event-index tests passed")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_event_index.py`
Expected: FAIL — `AttributeError: module 'cal_myhanno' has no attribute 'EventIndex'`

- [ ] **Step 3: `EventIndex` を実装する**

`calendar/bin/cal-myhanno` の `list_all_events` 定義の直後に追加:

```python
class EventIndex:
    """calendar_id ごとに全イベントを 1 回だけ取得し、iCalUID で引ける索引。

    apply-all が YAML 1 件ごとに events.list を呼ぶのを避けるための読み取り
    キャッシュ (437 件 × 2 言語 = 約 874 回 → カレンダー数回)。カレンダー単位の
    遅延取得なので、触らないカレンダーは fetch しない。

    書き込み後に索引を更新しない: 1 回の apply-all で同じ uid は 1 度しか処理
    されず、言語ごとに別プロセスで走るため。実行中の手編集との競合は cmd_apply が
    書き込み直前に 1 件取り直して防ぐ。
    """

    def __init__(self) -> None:
        self._by_cal: dict[str, dict[str, dict]] = {}

    def _load(self, calendar_id: str) -> dict[str, dict]:
        if calendar_id not in self._by_cal:
            self._by_cal[calendar_id] = {
                e["iCalUID"]: e
                for e in list_all_events(calendar_id)
                if e.get("iCalUID")
            }
        return self._by_cal[calendar_id]

    def get(self, calendar_id: str, uid: str) -> dict | None:
        """索引から uid のイベントを引く。無ければ None。"""
        return self._load(calendar_id).get(uid)
```

- [ ] **Step 4: テストを実行して通ることを確認**

Run: `python3 calendar/tests/test_event_index.py`
Expected: PASS — `OK: all event-index tests passed`

- [ ] **Step 5: Commit**

```bash
git add calendar/bin/cal-myhanno calendar/tests/test_event_index.py
git commit -m "feat(cal): カレンダー別 uid→event 索引 EventIndex を追加

list_all_events を使ったカレンダー単位の遅延取得キャッシュ。
まだ誰も使っていない (次のコミットで cmd_apply に結線する)。"
```

---

### Task 4: `cmd_apply` を索引対応にし、書き込み直前に再確認する

**Files:**
- Modify: `calendar/bin/cal-myhanno`（`cmd_apply` 本体、`cmd_apply_all` の Namespace 生成）
- Create: `calendar/tests/test_apply_recheck.py`

**Interfaces:**
- Consumes: `EventIndex.get()`（Task 3）、`events_in_sync()` / `merge_for_update()`（Task 2）、`find_event_by_uid()`（既存）
- Produces: `cmd_apply` が `args.index`（`EventIndex | None`）を任意で受け取る。`cmd_apply_all` が `EventIndex` を 1 個作って全呼び出しに渡す。

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_apply_recheck.py`:

```python
#!/usr/bin/env python3
"""cal-myhanno の「書き込み直前の再確認」のユニットテスト。
索引構築後に Calendar 側が変わった状況を作って、正しく振る舞うか検証する。
gws / find_event_by_uid を差し替えるのでネットワーク非依存。
実行: python3 calendar/tests/test_apply_recheck.py
"""
import argparse
import importlib.machinery
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_myhanno",
                                              os.path.join(BIN, "cal-myhanno"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

# 注: この YAML に対する render_yaml_to_event() の実出力は実機で確認済み:
#   {"summary": "ℹ️ テスト記事", "description": "新しい本文",
#    "start": {"date": "2026-08-08"}, "end": {"date": "2026-08-09"}}
# - end.date は排他的終端なので dtstart の翌日になる
# - source: は YAML のメタ情報で、イベント body には出ない
# _calendar_event() はこれに合わせること。ずれると events_in_sync が常に False になり、
# 「in-sync なら書かない」系のテストが誤って落ちる。
YAML_DOC = '''uid: "oshirase-1@hanno.city.tecoli.com"
summary: "ℹ️ テスト記事"
dtstart: "2026-08-08"
dtend: "2026-08-08"
description: |-
  新しい本文

render:
  gcal:
    mode: single-allday

source:
  type: city-hanno-oshirase
  id: "1"
  url: "https://example.com/1.html"
'''

UID = "oshirase-1@hanno.city.tecoli.com"


def _write_yaml():
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(YAML_DOC)
    return path


class StubIndex:
    """EventIndex の代わり。固定の 1 件を返す (または None)。"""

    def __init__(self, event):
        self.event = event

    def get(self, calendar_id, uid):
        return self.event


def _calendar_event(description):
    """Calendar 側にあるイベントを模した dict (render_yaml_to_event の実出力に合わせる)。"""
    return {
        "id": "evt-1",
        "etag": '"e1"',
        "iCalUID": UID,
        "summary": "ℹ️ テスト記事",
        "description": description,
        "start": {"date": "2026-08-08"},
        "end": {"date": "2026-08-09"},   # 終日イベントの end は排他的
    }


def _run(index_event, refetch_event, dry_run=False):
    """cmd_apply を走らせ、(結果 dict, gws 呼び出しログ) を返す。"""
    calls = []

    def fake_gws(*args, params=None, body=None):
        calls.append({"args": args, "params": params, "body": body})
        return {"summary": (body or {}).get("summary", ""), "id": "evt-1"}

    mod.gws = fake_gws
    mod.find_event_by_uid = lambda uid, cal=None: refetch_event

    path = _write_yaml()
    try:
        ns = argparse.Namespace(yaml_file=path, dry_run=dry_run, lang="default",
                                silent=True, index=StubIndex(index_event))
        return mod.cmd_apply(ns), calls
    finally:
        os.remove(path)


def test_skips_write_when_recheck_says_in_sync():
    """索引では差分ありだが、取り直すと既に最新 → 書かない。"""
    stale = _calendar_event("古い本文")        # 索引の値 (差分あり)
    fresh = _calendar_event("新しい本文")      # 実際の値 (差分なし)
    res, calls = _run(stale, fresh)
    assert res["action"] == "in-sync", res
    assert calls == [], "events.update を呼んではいけない"


def test_merges_onto_refetched_event_not_stale_one():
    """再取得しても差分あり → 取り直した方をマージ元にする。"""
    stale = _calendar_event("古い本文")
    fresh = _calendar_event("別の古い本文")
    fresh["colorId"] = "9"                     # 索引には無く、実際の Calendar にはある
    res, calls = _run(stale, fresh)
    assert res["action"] == "updated", res
    assert len(calls) == 1
    body = calls[0]["body"]
    assert body["description"] == "新しい本文"   # YAML の値で上書きされている
    assert body["colorId"] == "9", "取り直した方の値が残っていない = 古い索引をマージ元にしている"


def test_falls_back_to_import_when_event_vanished():
    """索引にはあったが、取り直すと消えている → import に落ちる。"""
    stale = _calendar_event("古い本文")
    res, calls = _run(stale, None)
    assert res["action"] == "imported", res
    assert len(calls) == 1
    assert calls[0]["args"][2] == "import"
    assert calls[0]["body"]["iCalUID"] == UID


def test_promotes_to_update_when_event_appeared():
    """索引には無いが、取り直すと既にある → update に回す (重複作成を防ぐ)。"""
    fresh = _calendar_event("古い本文")
    res, calls = _run(None, fresh)
    assert res["action"] == "updated", res
    assert len(calls) == 1
    assert calls[0]["args"][2] == "update"


def test_dry_run_does_not_refetch():
    """--dry-run は再確認しない (書かないので不要、計測もぶれない)。"""
    stale = _calendar_event("古い本文")
    refetched = {"called": False}

    def spy(uid, cal=None):
        refetched["called"] = True
        return stale

    mod.gws = lambda *a, **kw: {}
    mod.find_event_by_uid = spy
    path = _write_yaml()
    try:
        ns = argparse.Namespace(yaml_file=path, dry_run=True, lang="default",
                                silent=True, index=StubIndex(stale))
        res = mod.cmd_apply(ns)
    finally:
        os.remove(path)
    assert res["action"] == "updated", res
    assert refetched["called"] is False, "dry-run で再取得してはいけない"


def test_without_index_uses_find_event_by_uid_once():
    """索引を渡さない単体 apply は従来どおり 1 回だけ引く (再確認しない)。"""
    fresh = _calendar_event("古い本文")
    lookups = []

    def spy(uid, cal=None):
        lookups.append(uid)
        return fresh

    mod.gws = lambda *a, **kw: {"summary": "", "id": "evt-1"}
    mod.find_event_by_uid = spy
    path = _write_yaml()
    try:
        ns = argparse.Namespace(yaml_file=path, dry_run=False, lang="default",
                                silent=True)
        res = mod.cmd_apply(ns)
    finally:
        os.remove(path)
    assert res["action"] == "updated", res
    assert lookups == [UID], f"1 回だけ引くはず: {lookups}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all apply-recheck tests passed")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_apply_recheck.py`
Expected: FAIL — `test_skips_write_when_recheck_says_in_sync` が `AssertionError`（現状は索引を見ないので、`StubIndex` が無視されて `find_event_by_uid` の結果で動く、または `args.index` を見ないまま update を呼ぶ）

- [ ] **Step 3: `cmd_apply` の本体を書き換える**

`calendar/bin/cal-myhanno` の `cmd_apply` 内、`existing = find_event_by_uid(uid, target_cal_id)` の行から関数末尾までを以下に置換:

```python
    # 索引 (apply-all が渡す) があれば読み取りはそこから。無ければ従来どおり 1 件引く。
    index = getattr(args, "index", None)
    if index is not None:
        existing = index.get(target_cal_id, uid)
    else:
        existing = find_event_by_uid(uid, target_cal_id)

    if existing and events_in_sync(existing, new_body):
        if args.dry_run and not silent:
            print(json.dumps({"action": "in-sync (skip)", "uid": uid}, ensure_ascii=False))
        return {"action": "in-sync", "uid": uid,
                "summary": new_body.get("summary", ""), "cal_key": cal_key}

    if args.dry_run:
        # dry-run は書かないので再確認しない (計測もぶれない)
        if existing:
            if not silent:
                print(json.dumps({
                    "action": "update",
                    "id": existing["id"],
                    "uid": uid,
                    "summary": new_body.get("summary"),
                    "start": new_body.get("start"),
                    "end": new_body.get("end"),
                }, ensure_ascii=False, indent=2))
            return {"action": "updated", "uid": uid,
                    "summary": new_body.get("summary", ""), "cal_key": cal_key}
        if not silent:
            print(json.dumps({
                "action": "import",
                "uid": uid,
                "calendar": cal_key,
                "summary": new_body.get("summary"),
                "start": new_body.get("start"),
                "end": new_body.get("end"),
            }, ensure_ascii=False, indent=2))
        return {"action": "imported", "uid": uid,
                "summary": new_body.get("summary", ""), "cal_key": cal_key}

    # ここから書き込み経路。索引は実行開始時のスナップショットなので、apply 中に
    # 人が Calendar を手編集していると見落とす。書くイベントだけ 1 件取り直して
    # 最新状態で判定し直す (書き込みは通常 1 日数件なのでコストはほぼゼロ)。
    if index is not None:
        existing = find_event_by_uid(uid, target_cal_id)
        if existing and events_in_sync(existing, new_body):
            return {"action": "in-sync", "uid": uid,
                    "summary": new_body.get("summary", ""), "cal_key": cal_key}

    if existing:
        # update: 既存 body を新 body で上書き (YAML が真)
        updated = gws(
            "calendar", "events", "update",
            params={"calendarId": target_cal_id, "eventId": existing["id"]},
            body=merge_for_update(existing, new_body),
        )
        if not silent:
            print(f"UPDATED  {uid}  ({updated.get('summary','')[:50]})  [{cal_key}]")
        return {"action": "updated", "uid": uid,
                "summary": updated.get("summary", ""), "cal_key": cal_key}

    # import: 新規作成 with iCalUID
    new_body["iCalUID"] = uid
    new_body.setdefault("status", "confirmed")
    imported = gws(
        "calendar", "events", "import",
        params={"calendarId": target_cal_id},
        body=new_body,
    )
    if not silent:
        print(f"IMPORTED {uid}  ({imported.get('summary','')[:50]})  [{cal_key}]")
    return {"action": "imported", "uid": uid,
            "summary": imported.get("summary", ""), "cal_key": cal_key}
```

- [ ] **Step 4: テストを実行して通ることを確認**

Run: `python3 calendar/tests/test_apply_recheck.py`
Expected: PASS — `OK: all apply-recheck tests passed`

- [ ] **Step 5: `cmd_apply_all` で索引を作って渡す**

`calendar/bin/cal-myhanno` の `cmd_apply_all` 内、この部分:

```python
    DETAIL_THRESHOLD = 5  # 1 種 action がこの件数を超えたら集計のみ表示
    results: list[dict] = []
```

を以下に置換:

```python
    DETAIL_THRESHOLD = 5  # 1 種 action がこの件数を超えたら集計のみ表示
    # 読み取りをカレンダー単位の一括取得にまとめる (1 件ごとの events.list を廃止)
    index = EventIndex()
    results: list[dict] = []
```

同じ関数内の Namespace 生成:

```python
            ns = argparse.Namespace(yaml_file=f, dry_run=args.dry_run,
                                    lang=getattr(args, "lang", "default"),
                                    silent=True)
```

を以下に置換:

```python
            ns = argparse.Namespace(yaml_file=f, dry_run=args.dry_run,
                                    lang=getattr(args, "lang", "default"),
                                    silent=True, index=index)
```

- [ ] **Step 6: 全テストを回す**

Run: `python3 calendar/tests/test_apply_recheck.py && python3 calendar/tests/test_event_index.py && python3 calendar/tests/test_apply_helpers.py && python3 calendar/tests/test_calendar_paging.py`
Expected: すべて PASS

Run: `python3 calendar/tests/run-golden 2>&1 | tail -2`
Expected: `All golden checks passed.`（クローラ側は無変更なので当然だが、壊していないことの確認）

- [ ] **Step 7: 実 API に対して結果が変わらないことを確認**

Run:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/Users/utashiro/Git/tecolicom/city-tecoli/city-tecoli-f79904a70941.json
python3 calendar/bin/cal-myhanno apply-all -d calendar/events --only-managed --dry-run 2>&1 | tail -3
```
Expected: Task 2 Step 6 で記録した件数と**完全に一致**すること
（`imported` / `updated` / `in-sync` / `no-translation` / `err` / `no-source` / `total` のすべて）。
一致しなければ索引引きが取りこぼしている。

- [ ] **Step 8: Commit**

```bash
git add calendar/bin/cal-myhanno calendar/tests/test_apply_recheck.py
git commit -m "perf(cal): apply-all の読み取りを EventIndex に集約

YAML 1 件ごとの events.list (437件 × 2言語 = 約874回) をやめ、カレンダー単位の
一括取得 + 索引引きにする。

索引は実行開始時のスナップショットなので、実際に書き込むイベントだけ直前に
1 件取り直して最新状態で判定し直す。取り直した方をマージ元にするので、
apply 中の手編集を古い値で潰さない。--dry-run では再確認しない。
単体の apply <file> は索引を受け取らず従来どおり。"
```

---

### Task 5: 実測して README に記録する

**Files:**
- Modify: `calendar/README.md`（`## bin/cal-myhanno` セクション、テスト一覧）

**Interfaces:**
- Consumes: Task 1〜4 の全成果
- Produces: なし（最終タスク）

- [ ] **Step 1: 高速化後の apply-all を実測する**

Run:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/Users/utashiro/Git/tecolicom/city-tecoli/city-tecoli-f79904a70941.json
time python3 calendar/bin/cal-myhanno apply-all -d calendar/events --only-managed --dry-run 2>&1 | tail -2
```

実測値（`real` の秒数）を記録する。改善前は同じコマンドで 2 分以上かかっていた
（CI 実測では JP 63〜89 秒 + EN 72〜101 秒）。

**数秒台に落ちていなければ先に進まない。** 落ちていない場合、`EventIndex` が
`cmd_apply` に渡っていないか（Task 4 Step 5 の Namespace 生成漏れ）、
`index.get()` ではなく `find_event_by_uid()` が呼ばれている。

- [ ] **Step 2: README のテスト一覧を更新する**

`calendar/README.md` の `## テスト (golden 網)` セクション末尾（`- 現状 oshirase / shicho-blog の 2 クローラのみ対象 (Phase 1)。` の後）に追記:

```markdown
### ユニットテスト

golden 網とは別に、純粋関数・API ラッパのユニットテストがある。すべて
ネットワーク非依存で、`python3 calendar/tests/<file>` で個別に走る。

| ファイル | 対象 |
|---|---|
| `test_last_modified_dating.py` | `_lib` の Last-Modified → dtstart 変換 |
| `test_tourism_discovery.py` | tourism の一覧ページ自動発見 |
| `test_description_parts.py` | `_lib` の description 分解 (block 読み出し / status 行 / disclaimer) |
| `test_generation_index.py` | oshirase の page_id 別世代索引 |
| `test_diff_line.py` | oshirase の差分要約行 (LLM は差し替え) |
| `test_backfill_rewrite.py` | oshirase の in-place 書き換えヘルパ |
| `test_calendar_paging.py` | `cal-myhanno` の `events.list` ページング |
| `test_apply_helpers.py` | `cal-myhanno` の同期判定 / マージ |
| `test_event_index.py` | `cal-myhanno` の `EventIndex` |
| `test_apply_recheck.py` | `cal-myhanno` の書き込み前再確認 |
```

- [ ] **Step 3: README に apply の性質を書く**

`calendar/README.md` の既存セクション `### apply / apply-all の動作`（`calendar/README.md:142`）
の末尾、この行の直後に新しい小見出しを挿入する:

```markdown
**削除は行わない** (YAML 側で削除しても Calendar event は残る、安全策)。
```

挿入する内容:

```markdown
### apply-all の読み取り (EventIndex)

`apply-all` は起動時に**カレンダー単位で全イベントを一括取得**し、
`iCalUID → event` の索引 (`EventIndex`) を作って反映要否を判定する。
以前は YAML 1 件ごとに `events.list` を呼んでいたため、437 件 × JP/EN で
約 874 回の API 往復が発生し、日次 CI の所要時間の約半分 (135 秒) を占めていた。

索引は実行開始時のスナップショットなので、apply 中 (数秒) に人が Calendar を
手編集すると見落としうる。そのため**実際に書き込むイベントだけ、`events.update` /
`events.import` の直前に 1 件取り直して**判定し直す:

- 取り直した結果が in-sync なら書かない
- 差分が残るなら**取り直した方**をマージ元にする (古い索引の値で手編集を潰さない)
- 索引にあったが消えていれば import、索引に無いが存在すれば update に回す

書き込みは通常 1 日 0〜数件なので追加コストはほぼゼロ。`--dry-run` では再確認しない。
単体の `apply <file>` は索引を使わず、従来どおり `find_event_by_uid()` で 1 件引く。

`events.list` は `list_all_events()` に集約され、`nextPageToken` を辿って全件取得する
(`maxResults` は API 上限の 2500)。`gws --page-all` は使わない — 出力が NDJSON になり
`gws()` で扱えず、`--page-limit` 既定 10 で静かに切り捨てるため。
```

- [ ] **Step 4: 実測値を README に反映する**

Step 3 で書いた文章の「約 874 回の API 往復が発生し、日次 CI の所要時間の約半分
(135 秒) を占めていた」の直後に、Step 1 で得た実測値を 1 文で追記する。例:

```markdown
現在は同じ `apply-all --dry-run` が <実測秒数> 秒で完了する。
```

`<実測秒数>` は Step 1 の `real` の値に置き換えること。推測値を書かない。

- [ ] **Step 5: Commit**

```bash
git add calendar/README.md
git commit -m "docs(cal): apply-all の EventIndex とユニットテスト一覧を README に追記"
```

- [ ] **Step 6: CI で実測を確認する**

push 後、`Calendar daily` の run が走る（`calendar/bin/**` の変更が push trigger）。

Run:
```bash
gh run list --limit 3
```

完了後、apply ステップの所要時間を確認:

```bash
gh run view <RUN_ID> --json jobs --jq '.jobs[].steps[] | select(.name|test("Apply")) | "\(.name)\t\(.startedAt)\t\(.completedAt)"'
```

Expected: `Apply events to Calendar` と `Apply EN events to Calendar` がいずれも
**10 秒未満**（改善前は 63〜101 秒）。全体も 6 分台から 4 分前後に落ちるはず。

**`conclusion` が `success` でなければ、原因を報告して止まること。** 特に
`imported` が想定外に増えていたら索引の取りこぼしを疑う（Calendar に重複イベントが
作られる恐れがあるため、その場でロールバックを検討する）。

---

## 完了条件

- [ ] `calendar/tests/test_calendar_paging.py` / `test_apply_helpers.py` / `test_event_index.py` / `test_apply_recheck.py` がすべて緑
- [ ] 既存のユニットテスト 6 本と `run-golden` 3 シナリオが緑
- [ ] `grep -n 'maxResults' calendar/bin/cal-myhanno` に `500` が 1 つも残っていない
- [ ] `apply-all --dry-run` の件数内訳が Task 2 Step 6 の記録と完全一致
- [ ] `apply-all --dry-run` が数秒台で完了する（実測値を README に記録済み）
- [ ] CI の `Apply events to Calendar` / `Apply EN events to Calendar` がいずれも 10 秒未満で `success`
- [ ] `calendar/README.md` に `EventIndex` / 再確認 / ページング / ユニットテスト一覧が載っている
