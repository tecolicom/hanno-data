# 飯能市立図書館カレンダー 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 飯能市立図書館の休館日とイベントを取り込み、館ごとの Google Calendar
(本館 / こども図書館、各 JP/EN) に配信する。

**Architecture:** クローラを 2 本に分ける。休館日は `cal.php` (JSON) から取る
**集合同期型** (`_lib.sync_set()`)、イベントは `cal.php` の `event_day` →
`events.php` → 詳細ページと辿る**追記型**。両者が同じ `cal.php` を叩くので、
取得と JSON 解析だけを共有モジュール `_hanno_lib.py` に置く。

**Tech Stack:** Python 3.10+、`pyyaml`、`httpx` (LLM 要約のみ)、`gws` (カレンダー
作成)、GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-08-24-hanno-lib-calendar-design.md`

## Global Constraints

- **UID を後から変えない。** 変えると全イベントが作り直しになる。
- **1 リクエスト 1 館。** `cal.php?libraries=01,02` とまとめると `event_day` が
  空で返る (2026-08-23 実測)。
- **取得ウィンドウは今月から 12 か月を要求し、返った分だけ扱う。** 配信元の
  データは年度末で終わるので、返る月数は 1〜12 か月と変動する。固定の月数や
  総件数を前提にしない。
- **`status: canceled` を使わない。** 消えた理由を我々は知り得ない。
- **画像は取り込まない。** 詳細ページの `/calendar/images/*.jpg` は無視する。
- **golden のスタブは URL → テキストの層に当てる。** JSON 解析も HTML 解析も
  本物を走らせる。
- **`.http-cache.json` の新規エントリを commit しない。** 最初の CI 実行が 304 で
  全 skip する。
- コメント・ログ・コミットメッセージは日本語。既存クローラの文体に合わせる。

## File Structure

| ファイル | 責務 |
|---|---|
| `calendar/bin/_hanno_lib.py` (新規) | `cal.php` の取得と JSON 解析、期間計算。2 クローラが共有 |
| `calendar/bin/cal-lib-closed-fetch` (新規) | 休館日 → YAML (集合同期型、LLM 不使用) |
| `calendar/bin/cal-lib-event-fetch` (新規) | イベント → YAML (追記型、LLM 要約あり) |
| `calendar/sources.yaml` | `lib-closed` / `lib-event` の 2 節 |
| `calendar/city.yaml` | カレンダー 4 つと routing 4 行 |
| `.github/workflows/cal-daily.yml` | Crawl 2 ステップ + prune 2 つ |
| `calendar/tests/test_hanno_lib.py` (新規) | 期間計算・JSON 解析のユニット |
| `calendar/tests/test_lib_closed.py` (新規) | 休館日 items 生成・件数チェック |
| `calendar/tests/test_lib_event.py` (新規) | `events.php` / 詳細ページの HTML 解析 |
| `calendar/tests/run-golden` | `_setup_lib_*` + 4 シナリオ |
| `calendar/tests/fixtures/cal-lib-*/` (新規) | 実データを固めた fixture |
| `calendar/tests/seed/cal-lib-closed-*/` (新規) | 削除ガード検証用の既存 YAML |

**設計書に無い判断が 1 つある**: `_hanno_lib.py` の新設。設計書は「クローラ 2 本」
としか書いていないが、両者が同じ `cal.php` を同じ形で読むため、置き場を分けると
「後日片方だけ直る」事故になる (`_lib` に `drop_unchanged_claims` を移した理由と
同じ)。都市非依存の `_lib.py` とは分ける — こちらは配信元固有。

---

### Task 1: カレンダー 4 つを作成し city.yaml に登録

**Files:**
- Modify: `calendar/city.yaml`

**Interfaces:**
- Produces: 論理名 `lib-main` / `lib-main.en` / `lib-kids` / `lib-kids.en` と、
  `source_type_to_calendar` の 4 行。以降のタスクはこの論理名に依存する。

このタスクだけ Google 側の状態を変える。**取り消しにくいので、実行前にユーザに
確認を取ること。**

- [ ] **Step 1: 認証情報を確認する**

```bash
ls -l ~/.config/city-tecoli/calendar-sa.json
```

期待: ファイルが存在する。無ければ止めてユーザに聞く。

- [ ] **Step 2: カレンダーを 4 つ作成する**

`gws` を使うときは SA 認証がユーザー OAuth に上書きされないよう
`GOOGLE_APPLICATION_CREDENTIALS` を明示する。

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/city-tecoli/calendar-sa.json
for NAME in "飯能市立図書館" "飯能市立図書館（EN）" "こども図書館" "こども図書館（EN）"; do
  echo "--- $NAME"
  gws calendar calendars insert --format json \
    --json "{\"summary\":\"$NAME\",\"timeZone\":\"Asia/Tokyo\"}"
done
```

返る JSON の `id` を 4 つ控える。

- [ ] **Step 3: 一般公開 + SA に writer 委託**

4 つの ID それぞれについて実行する (`<ID>` を置き換える)。

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/city-tecoli/calendar-sa.json
gws calendar acl insert --format json --params '{"calendarId":"<ID>"}' \
  --json '{"role":"reader","scope":{"type":"default"}}'
gws calendar acl insert --format json --params '{"calendarId":"<ID>"}' \
  --json '{"role":"writer","scope":{"type":"user","value":"myhanno-bot@city-tecoli.iam.gserviceaccount.com"}}'
```

- [ ] **Step 4: ACL を確認する**

```bash
gws calendar acl list --format json --params '{"calendarId":"<ID>"}'
```

期待: `reader`/`default` と `writer`/`user` の 2 件が入っている。

- [ ] **Step 5: city.yaml に登録する**

`calendars:` の `cci.en` の行の後ろに追記する。

```yaml
  # 飯能市立図書館 (山手町19-5)。city-tecoli の施設ページ
  # place_id: ChIJo0ygjPCcJhURjglJPLfCYRs に紐づける。
  # tecolicom@gmail.com 所有、一般公開、SA に writer を委託。gws CLI で作成。
  lib-main: "<Step 2 で返った ID>"        # 飯能市立図書館
  lib-main.en: "<Step 2 で返った ID>"     # 飯能市立図書館（EN）
  # こども図書館 (稲荷町25-8)。place_id: ChIJyVn5ejkmGWARKQvc2xVW-F4
  lib-kids: "<Step 2 で返った ID>"        # こども図書館
  lib-kids.en: "<Step 2 で返った ID>"     # こども図書館（EN）
```

`source_type_to_calendar:` の末尾に追記する。

```yaml
  hanno-lib-main-closed: lib-main
  hanno-lib-main-event: lib-main
  hanno-lib-kids-closed: lib-kids
  hanno-lib-kids-event: lib-kids
```

- [ ] **Step 6: YAML が壊れていないことを確認する**

```bash
python3 -c "
import yaml
c = yaml.safe_load(open('calendar/city.yaml'))
for k in ['lib-main','lib-main.en','lib-kids','lib-kids.en']:
    assert c['calendars'].get(k), k
for k in ['hanno-lib-main-closed','hanno-lib-main-event','hanno-lib-kids-closed','hanno-lib-kids-event']:
    assert c['source_type_to_calendar'].get(k), k
print('OK')"
```

期待: `OK`

- [ ] **Step 7: Commit**

```bash
git add calendar/city.yaml
git commit -m "feat(calendar): 図書館カレンダー 4 つを作成して city.yaml に登録"
```

---

### Task 2: 共有モジュール `_hanno_lib.py` と sources.yaml

**Files:**
- Create: `calendar/bin/_hanno_lib.py`
- Create: `calendar/tests/test_hanno_lib.py`
- Modify: `calendar/sources.yaml`

**Interfaces:**
- Consumes: `_lib.USER_AGENT`, `_lib.fetch`
- Produces:
  - `month_window(today: str, months_ahead: int) -> tuple[str, str]`
  - `fetch_text(url: str) -> str` — **golden はここを差し替える**
  - `fetch_cal(cal_url: str, lib_code: str, term_from: str, term_to: str) -> dict`
  - `terms_of(cal_json: dict, lib_code: str) -> list[dict]`
  - `days_of(terms: list[dict], key: str) -> list[str]`
  - `sources.yaml` の `lib-closed` / `lib-event` 節

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_hanno_lib.py`:

```python
#!/usr/bin/env python3
"""_hanno_lib のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_hanno_lib.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "_hanno_lib.py")
loader = importlib.machinery.SourceFileLoader("_hanno_lib", SCRIPT)
spec = importlib.util.spec_from_loader("_hanno_lib", loader)
hl = importlib.util.module_from_spec(spec)
loader.exec_module(hl)


def test_month_window_same_year():
    assert hl.month_window("2026-08-24", 12) == ("202608", "202708")


def test_month_window_crosses_year():
    assert hl.month_window("2026-12-01", 1) == ("202612", "202701")


def test_month_window_zero_ahead():
    assert hl.month_window("2026-01-31", 0) == ("202601", "202601")


_SAMPLE = {
    "libraries": [
        {"code": "01", "name": "市立図書館",
         "term": [{"month": "202608", "closing_day": ["2026/08/03"], "event_day": []}]},
        {"code": "02", "name": "こども図書館",
         "term": [{"month": "202608",
                   "closing_day": ["2026/08/03", "2026/08/12"],
                   "event_day": ["2026/08/01"]},
                  {"month": "202609", "closing_day": ["2026/09/07"]}]},
    ]
}


def test_terms_of_picks_the_right_library():
    terms = hl.terms_of(_SAMPLE, "02")
    assert [t["month"] for t in terms] == ["202608", "202609"], terms


def test_terms_of_raises_for_unknown_library():
    try:
        hl.terms_of(_SAMPLE, "99")
    except ValueError:
        return
    raise AssertionError("館が無いのに ValueError が飛ばない")


def test_terms_of_raises_when_shape_is_wrong():
    """取得層が死んだことを「0 件」と区別できなくしない。"""
    try:
        hl.terms_of({"error": "blocked"}, "02")
    except ValueError:
        return
    raise AssertionError("libraries が無いのに ValueError が飛ばない")


def test_days_of_normalizes_and_sorts():
    terms = hl.terms_of(_SAMPLE, "02")
    assert hl.days_of(terms, "closing_day") == ["2026-08-03", "2026-08-12", "2026-09-07"]


def test_days_of_missing_key_is_empty():
    terms = hl.terms_of(_SAMPLE, "02")
    assert hl.days_of(terms, "event_day") == ["2026-08-01"]
    assert hl.days_of([{"month": "202610"}], "closing_day") == []


def test_fetch_cal_sends_one_library_per_request():
    seen = []

    def _fake(url):
        seen.append(url)
        return json.dumps(_SAMPLE)

    hl.fetch_text = _fake
    got = hl.fetch_cal("https://example.test/cal.php", "02", "202608", "202708")
    assert got == _SAMPLE, got
    assert seen == ["https://example.test/cal.php"
                    "?libraries=02&term_from=202608&term_to=202708"], seen


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all _hanno_lib tests passed")
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `python3 calendar/tests/test_hanno_lib.py`
Expected: FAIL — `FileNotFoundError` (まだ `_hanno_lib.py` が無い)

- [ ] **Step 3: `_hanno_lib.py` を書く**

Create `calendar/bin/_hanno_lib.py`:

```python
"""_hanno_lib — 飯能市立図書館 (www.hanno-lib.jp) の 2 クローラが共有する取得層.

cal-lib-closed-fetch (休館日) と cal-lib-event-fetch (イベント) は同じ cal.php を
叩き、同じ JSON を読む。片方にだけ置くと後日片方だけ直る事故になるのでここに
集約する (_lib に drop_unchanged_claims を移したのと同じ理由)。

都市非依存の _lib.py とは分ける — こちらは配信元固有。

設計: docs/superpowers/specs/2026-08-24-hanno-lib-calendar-design.md
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import fetch as _fetch  # noqa: E402


def month_window(today: str, months_ahead: int) -> tuple[str, str]:
    """cal.php に渡す (term_from, term_to) を "YYYYMM" で返す.

    今月から months_ahead か月先まで。**多めに要求して返った分だけ扱う**のが
    前提。配信元の休館日は年度単位で登録されており、取れる月数は観測時期で
    1〜12 か月に変わる (2026-08-24 実測: term_from=202704 は term 空で返る)。
    """
    y, m = int(today[:4]), int(today[5:7])
    total = y * 12 + (m - 1) + months_ahead
    return f"{y:04d}{m:02d}", f"{total // 12:04d}{total % 12 + 1:02d}"


def fetch_text(url: str) -> str:
    """HTTP GET してテキストを返す。**golden はこの関数を差し替える** (最下層)."""
    return _fetch(url)


def fetch_cal(cal_url: str, lib_code: str, term_from: str, term_to: str) -> dict:
    """cal.php を 1 館分叩いて JSON を返す.

    **1 リクエスト 1 館。** libraries=01,02 とまとめて指定すると event_day が
    空で返る (2026-08-23 実測)。
    """
    url = (f"{cal_url}?libraries={lib_code}"
           f"&term_from={term_from}&term_to={term_to}")
    return json.loads(fetch_text(url))


def terms_of(cal_json: dict, lib_code: str) -> list[dict]:
    """cal.php の応答から指定館の term 配列を返す.

    期待の形でなければ ValueError。**空リストで握り潰さない** — 取得層が死んだ
    ことと「休館日 0 件」を区別できなくなる (イベント側は 0 件が正常なので、
    疎通の判定をここに寄せている)。
    """
    libs = cal_json.get("libraries") if isinstance(cal_json, dict) else None
    if not isinstance(libs, list):
        raise ValueError("cal.php: libraries が無い (取得経路の異常)")
    for lib in libs:
        if lib.get("code") == lib_code:
            terms = lib.get("term")
            if not isinstance(terms, list):
                raise ValueError(f"cal.php: 館 {lib_code} に term が無い")
            return terms
    raise ValueError(f"cal.php: 館 {lib_code} が応答に含まれない")


def days_of(terms: list[dict], key: str) -> list[str]:
    """term 配列から closing_day / event_day を "YYYY-MM-DD" の昇順で集める.

    配信元は "2026/08/03" 形式で返す。重複は潰す。
    """
    out: set[str] = set()
    for t in terms:
        for d in t.get(key) or []:
            out.add(str(d).replace("/", "-"))
    return sorted(out)
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `python3 calendar/tests/test_hanno_lib.py`
Expected: `OK: all _hanno_lib tests passed`

- [ ] **Step 5: sources.yaml に 2 節を足す**

`calendar/sources.yaml` の末尾に追記する。

```yaml
# 飯能市立図書館の休館日。**集合同期型** — cal.php が月ごとに「その月の全休館日」
# を返すので、取得側に無い日は削除する。LLM 不使用。
#
# **取得できる範囲は年度末までで、固定の月数ではない。** 休館日は年度単位で
# 登録されており、取れる月数は観測時期で 1〜12 か月に変わる。months_ahead は
# 「配信元が持ちうる最大」で、返った分だけを扱う。
#
# min_days_per_month は **館ごと・返ってきた月ごと**の下限。総数の固定値だと
# (a) 年度末に近づくと正常時でも赤になり、(b) 片方の館が丸ごと空でも
# もう片方の分で閾値を超えて半分の欠落が静かに通る。
lib-closed:
  cal_url: "https://www.hanno-lib.jp/cal.php"
  page_url: "https://www.hanno-lib.jp/calendar/"
  url_host_allowlist: www.hanno-lib.jp
  summary_prefix: "🏛 "
  months_ahead: 12
  min_days_per_month: 3
  max_delete: 10
  libraries:
    - code: "01"
      name: "飯能市立図書館"
      uid_prefix: libmain-closed
      source_type: hanno-lib-main-closed
    - code: "02"
      name: "こども図書館"
      uid_prefix: libkids-closed
      source_type: hanno-lib-kids-closed

# 飯能市立図書館のイベント。追記型。
# cal.php の event_day → events.php (その日の記事一覧) → 詳細ページ、の 3 段。
# events.php は term_to を無視するので 1 日 1 リクエスト。max_event_days は
# その暴走防止 (cci-event の max_pages と同じ発想)。
#
# **件数では異常を測れない。** event_day が 0 件の期間は普通にある
# (本館 01 は 2026-08 時点で全月 0 件)。疎通の判定は cal.php の応答が JSON として
# 読めるかで行う (_hanno_lib.terms_of が ValueError を投げる)。
lib-event:
  cal_url: "https://www.hanno-lib.jp/cal.php"
  events_url: "https://www.hanno-lib.jp/events.php"
  site_url: "https://www.hanno-lib.jp/"
  url_host_allowlist: www.hanno-lib.jp
  url_path_prefix: "/calendar/"
  summary_prefix: "📚 "
  months_ahead: 12
  max_event_days: 60
  libraries:
    - code: "01"
      name: "飯能市立図書館"
      uid_prefix: libmain-event
      source_type: hanno-lib-main-event
    - code: "02"
      name: "こども図書館"
      uid_prefix: libkids-event
      source_type: hanno-lib-kids-event
```

- [ ] **Step 6: sources.yaml が読めることを確認する**

```bash
python3 -c "
import sys; sys.path.insert(0, 'calendar/bin')
from _lib import load_source_config
for k in ('lib-closed', 'lib-event'):
    c = load_source_config(k)
    print(k, [l['code'] for l in c['libraries']], c['months_ahead'])"
```

期待:
```
lib-closed ['01', '02'] 12
lib-event ['01', '02'] 12
```

- [ ] **Step 7: Commit**

```bash
git add calendar/bin/_hanno_lib.py calendar/tests/test_hanno_lib.py calendar/sources.yaml
git commit -m "feat(calendar): 図書館クローラの共有取得層と sources.yaml"
```

---

### Task 3: `cal-lib-closed-fetch` (休館日、集合同期型)

**Files:**
- Create: `calendar/bin/cal-lib-closed-fetch`
- Create: `calendar/tests/test_lib_closed.py`
- Create: `calendar/tests/fixtures/cal-lib-closed-fetch/manifest.json` ほか
- Create: `calendar/tests/seed/cal-lib-closed-delete/`, `.../cal-lib-closed-keep-past/`
- Modify: `calendar/tests/run-golden`

**Interfaces:**
- Consumes: `_hanno_lib.month_window` / `fetch_cal` / `terms_of` / `days_of`、
  `_lib.sync_set` / `SetSyncTooManyDeletions` / `load_source_config` /
  `yaml_escape_str` / `yaml_block_scalar`
- Produces:
  - `closing_items(days: list[str], lib: dict, page_url: str) -> list[dict]`
  - `check_min_days(terms: list[dict], lib_code: str, min_per_month: int) -> None`
  - CLI: `cal-lib-closed-fetch [--out-dir] [--dry-run] [--today] [--min-days-per-month] [--max-delete]`

`sync_set()` が UID を `{uid_prefix}-{YYYYMMDD}-{NN}@{namespace}` の形で自前採番
する。休館日は 1 館 1 日 1 件なので `NN` は常に `01` になる。

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_lib_closed.py`:

```python
#!/usr/bin/env python3
"""cal-lib-closed-fetch の純粋関数のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_lib_closed.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-lib-closed-fetch")
loader = importlib.machinery.SourceFileLoader("cal_lib_closed_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_lib_closed_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

_LIB = {"code": "02", "name": "こども図書館",
        "uid_prefix": "libkids-closed", "source_type": "hanno-lib-kids-closed"}
_PAGE = "https://www.hanno-lib.jp/calendar/"


def test_closing_items_shape():
    got = mod.closing_items(["2026-08-03", "2026-08-12"], _LIB, _PAGE, "🏛 ")
    assert got == [
        {"date": "2026-08-03", "summary": "🏛 こども図書館 休館",
         "description": "こども図書館は休館です。"},
        {"date": "2026-08-12", "summary": "🏛 こども図書館 休館",
         "description": "こども図書館は休館です。"},
    ], got


def test_closing_items_keeps_館名_in_summary():
    """カレンダーが分かれていても日次表示では混ざるので「休館」だけにしない。"""
    got = mod.closing_items(["2026-08-03"], _LIB, _PAGE, "🏛 ")
    assert "こども図書館" in got[0]["summary"], got


def test_closing_items_empty():
    assert mod.closing_items([], _LIB, _PAGE, "🏛 ") == []


def test_check_min_days_passes():
    terms = [{"month": "202608", "closing_day": ["a", "b", "c", "d"]},
             {"month": "202609", "closing_day": ["a", "b", "c"]}]
    mod.check_min_days(terms, "02", 3)   # 例外が飛ばなければ OK


def test_check_min_days_flags_a_thin_month():
    """月ごとに見る。合計で見ると 1 か月の欠落が隠れる。"""
    terms = [{"month": "202608", "closing_day": ["a", "b", "c", "d", "e", "f"]},
             {"month": "202609", "closing_day": ["a"]}]
    try:
        mod.check_min_days(terms, "02", 3)
    except ValueError as e:
        assert "202609" in str(e), e
        return
    raise AssertionError("薄い月があるのに ValueError が飛ばない")


def test_check_min_days_rejects_empty_terms():
    """term が 1 つも無いのは異常 (今月分は必ず返るはず)。"""
    try:
        mod.check_min_days([], "02", 3)
    except ValueError:
        return
    raise AssertionError("term 空なのに ValueError が飛ばない")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all lib-closed tests passed")
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `python3 calendar/tests/test_lib_closed.py`
Expected: FAIL — `FileNotFoundError` (まだクローラが無い)

- [ ] **Step 3: クローラを書く**

Create `calendar/bin/cal-lib-closed-fetch` (実行権限を付ける):

```python
#!/usr/bin/env python3
"""cal-lib-closed-fetch — 飯能市立図書館の休館日 → YAML.

Source: https://www.hanno-lib.jp/cal.php (JSON)

/calendar/ の HTML には空の <table id="opac-calendar"> があるだけで、中身は JS が
この cal.php から取って描画している。**休館日の入手経路はこれしかない。**

**集合同期型クローラ**である。取得側に無い休館日は「取り消された」と解釈して
削除する。削除条件と安全弁は _lib.plan_set_sync()。

館ごとに uid_prefix を分けて sync_set() を呼ぶので、削除ガードも館ごとに閉じる。

LLM 不使用 — cal.php が返すのは日付だけで、要約する本文が無い。決定論的に作れる
ものに LLM を挟むと content_hash が揺れる余地を増やすだけ。

設計: docs/superpowers/specs/2026-08-24-hanno-lib-calendar-design.md
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (  # noqa: E402
    load_source_config, sync_set, SetSyncTooManyDeletions,
    yaml_escape_str, yaml_block_scalar,
)
from _hanno_lib import month_window, fetch_cal, terms_of, days_of  # noqa: E402


SOURCE_KEY = "lib-closed"


def closing_items(days: list[str], lib: dict, page_url: str,
                  summary_prefix: str) -> list[dict]:
    """休館日のリストを sync_set() に渡す items にする.

    summary に館名を残すのは、city-tecoli の日次表示が購読カレンダーのイベントを
    所属に関わらず混ぜて出すため。「休館」だけでは意味が通らない。
    """
    return [{"date": d,
             "summary": f"{summary_prefix}{lib['name']} 休館",
             "description": f"{lib['name']}は休館です。"}
            for d in days]


def check_min_days(terms: list[dict], lib_code: str, min_per_month: int) -> None:
    """**館ごと・月ごと**に休館日の下限を検査する。割ったら ValueError.

    総数の固定値では測れない: 取れる月数が観測時期で 1〜12 か月に変わるので
    年度末に近づくと正常時でも下回る。館ごとに見ないと、片方が丸ごと空でも
    もう片方の分で閾値を超えて半分の欠落が静かに通る。
    """
    if not terms:
        raise ValueError(f"館 {lib_code}: term が 1 つも無い (今月分は必ず返るはず)")
    thin = [f"{t.get('month')}={len(t.get('closing_day') or [])}"
            for t in terms if len(t.get("closing_day") or []) < min_per_month]
    if thin:
        raise ValueError(
            f"館 {lib_code}: 休館日が月 {min_per_month} 日未満の月がある: "
            f"{', '.join(thin)}")


def build_yaml_doc_for(lib: dict, cfg: dict):
    """sync_set の render_doc コールバックを館ごとに作る."""
    page_url = cfg["page_url"]

    def _render(uid: str, item: dict, source_id: str, content_hash: str) -> str:
        description = f"{item['description']}\n\n{page_url}"
        lines = [
            f"uid: {yaml_escape_str(uid)}",
            f"summary: {yaml_escape_str(item['summary'])}",
            f"location: {yaml_escape_str(lib['name'])}",
            f"url: {yaml_escape_str(page_url)}",
            f"dtstart: {yaml_escape_str(item['date'])}",
            f"dtend: {yaml_escape_str(item['date'])}",
            "description: " + yaml_block_scalar(description, indent=2),
            "",
            "render:",
            "  gcal:",
            "    mode: single-allday",
            "",
            "source:",
            f"  type: {lib['source_type']}",
            f"  id: {yaml_escape_str(source_id)}",
            f"  url: {yaml_escape_str(page_url)}",
            f"  content_hash: {yaml_escape_str(content_hash)}",
        ]
        return "\n".join(lines) + "\n"

    return _render


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    default_out_dir = os.path.join(here, "..", "events")
    cfg = load_source_config(SOURCE_KEY)

    ap = argparse.ArgumentParser(
        description="飯能市立図書館の休館日 → YAML (集合同期型、LLM 不使用)")
    ap.add_argument("--out-dir", default=default_out_dir)
    ap.add_argument("--dry-run", action="store_true", help="書き込まずに件数だけ出す")
    ap.add_argument("--today", default=None,
                    help="取得ウィンドウと削除判定の基準日 (テスト用)")
    ap.add_argument("--min-days-per-month", type=int,
                    default=cfg.get("min_days_per_month", 3),
                    help="館ごと・月ごとの休館日の下限。割ったら exit 2")
    ap.add_argument("--max-delete", type=int, default=cfg.get("max_delete", 10),
                    help="削除がこれを超えたら何も書かずに exit 3")
    args = ap.parse_args()

    host = cfg["cal_url"].split("/")[2]
    if host != cfg["url_host_allowlist"]:
        sys.exit(f"URL outside allowlist: {cfg['cal_url']}")

    today = args.today or _date.today().isoformat()
    term_from, term_to = month_window(today, int(cfg["months_ahead"]))

    total = {"added": 0, "updated": 0, "deleted": 0, "unchanged": 0}
    for lib in cfg["libraries"]:
        code = lib["code"]
        # 取得層が死んだら terms_of が ValueError を投げる。握り潰さない。
        cal_json = fetch_cal(cfg["cal_url"], code, term_from, term_to)
        terms = terms_of(cal_json, code)
        try:
            check_min_days(terms, code, args.min_days_per_month)
        except ValueError as e:
            sys.exit(f"{e}")

        days = days_of(terms, "closing_day")
        items = closing_items(days, lib, cfg["page_url"], cfg["summary_prefix"])
        print(f"{code} {lib['name']}: {len(terms)} months, {len(items)} closing days",
              file=sys.stderr)

        try:
            stats = sync_set(args.out_dir, lib["uid_prefix"], items,
                             build_yaml_doc_for(lib, cfg),
                             today=today, max_delete=args.max_delete,
                             dry_run=args.dry_run)
        except SetSyncTooManyDeletions as e:
            print(f"ERROR: {code} {e}", file=sys.stderr)
            sys.exit(3)
        for k in total:
            total[k] += stats[k]

    print(f"Done. added={total['added']} updated={total['updated']} "
          f"deleted={total['deleted']} unchanged={total['unchanged']}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
```

```bash
chmod +x calendar/bin/cal-lib-closed-fetch
```

- [ ] **Step 4: ユニットテストが通ることを確認する**

Run: `python3 calendar/tests/test_lib_closed.py`
Expected: `OK: all lib-closed tests passed`

- [ ] **Step 5: 実データで一度動かす (手元、書き込みなし)**

```bash
./calendar/bin/cal-lib-closed-fetch --out-dir /tmp/libtest --dry-run
```

期待: 2 館分の行が出て `Done.` で終わる。エラーが出たら止めて原因を調べる。

- [ ] **Step 6: fixture を採る**

```bash
mkdir -p calendar/tests/fixtures/cal-lib-closed-fetch
UA="myhanno-calendar-fetcher/0.1 (+https://city.tecoli.com)"
for C in 01 02; do
  curl -s -A "$UA" \
    "https://www.hanno-lib.jp/cal.php?libraries=$C&term_from=202608&term_to=202708" \
    -o "calendar/tests/fixtures/cal-lib-closed-fetch/cal-$C.json"
done
cat > calendar/tests/fixtures/cal-lib-closed-fetch/manifest.json <<'JSON'
{
  "https://www.hanno-lib.jp/cal.php?libraries=01&term_from=202608&term_to=202708": "cal-01.json",
  "https://www.hanno-lib.jp/cal.php?libraries=02&term_from=202608&term_to=202708": "cal-02.json"
}
JSON
```

URL が `--today 2026-08-24` から作られる `month_window("2026-08-24", 12)` =
`("202608", "202708")` と一致していること。ずれると golden が「fixture 外の URL」
で落ちる。

- [ ] **Step 7: run-golden に配線する**

`calendar/tests/run-golden` の `SET_SYNC_TODAY` / `SET_SYNC_CRAWLERS` を、
クローラごとに基準日を持てる形に置き換える。

置換前:
```python
SET_SYNC_TODAY = "2026-06-01"
SET_SYNC_CRAWLERS = {"cal-cci-chef-fetch"}
```

置換後:
```python
# --today を渡すクローラと、その基準日。固定しないと fixture 内の予定が日々
# 「過去」に流れ、削除の可否や取得ウィンドウが変わって golden が壊れる。
# 図書館クローラは取得ウィンドウ (cal.php の term_from/term_to) も today から
# 作るので、fixture の URL と一致する日付を選ぶこと。
TODAY_BY_CRAWLER = {
    "cal-cci-chef-fetch": "2026-06-01",
    "cal-lib-closed-fetch": "2026-08-24",
}
```

`_run_crawler` の中:

置換前:
```python
            if crawler in SET_SYNC_CRAWLERS:
                sys.argv += ["--today", SET_SYNC_TODAY]
```

置換後:
```python
            if crawler in TODAY_BY_CRAWLER:
                sys.argv += ["--today", TODAY_BY_CRAWLER[crawler]]
```

`DETERMINISTIC_DATE_CRAWLERS` に足す (dtstart は fixture 由来で実行日に依存しない):

```python
DETERMINISTIC_DATE_CRAWLERS = {"cal-tourism-news-fetch", "cal-cci-chef-fetch",
                               "cal-cci-event-fetch", "cal-lib-closed-fetch"}
```

`_setup_cci_chef` の下に setup を足す:

```python
def _setup_lib(m, crawler, manifest):
    """URL → テキストの層だけ fixture に差し替える (最下層).

    _hanno_lib.fetch_text を潰すので、JSON 解析 (terms_of / days_of) も
    items 生成も本物が走る。上位を差し替えると今回書いた解析コードが 1 行も
    走らないまま緑になる。
    """
    sys.path.insert(0, BIN)
    import _hanno_lib
    _hanno_lib.fetch_text = lambda url: _read_fixture(crawler, manifest[url])
    m.fetch_with_cache = lambda url, etag, lm: (
        (_read_fixture(crawler, manifest[url]), None, None) if url in manifest
        else (None, None, None))
    m.load_http_cache = lambda: {}
    m.save_http_cache = lambda c: None
```

`CRAWLERS` に 3 本足す:

```python
    # 図書館の休館日 (集合同期型)。seed 付きの 2 本が削除ガードの回帰を見る:
    #   delete    … 取得側に無い「未来」の休館日が消えること (golden に無い = 消えた)
    #   keep-past … 取得側に無くても「過去」の休館日は残ること
    ("cal-lib-closed-fetch", "cal-lib-closed-fetch", _setup_lib, None),
    ("cal-lib-closed-delete", "cal-lib-closed-fetch", _setup_lib, "cal-lib-closed-delete"),
    ("cal-lib-closed-keep-past", "cal-lib-closed-fetch", _setup_lib, "cal-lib-closed-keep-past"),
```

- [ ] **Step 8: seed を作る**

削除ガードの 2 本ぶん。`--today` は `2026-08-24`、取得範囲は fixture の
`closing_day` の最小〜最大。

```bash
mkdir -p calendar/tests/seed/cal-lib-closed-delete/2026
cat > calendar/tests/seed/cal-lib-closed-delete/2026/09-15_libkids-closed-20260915-01.yaml <<'YAML'
uid: "libkids-closed-20260915-01@hanno.city.tecoli.com"
summary: "🏛 こども図書館 休館"
location: "こども図書館"
url: "https://www.hanno-lib.jp/calendar/"
dtstart: "2026-09-15"
dtend: "2026-09-15"
description: |-
  こども図書館は休館です。

  https://www.hanno-lib.jp/calendar/

render:
  gcal:
    mode: single-allday

source:
  type: hanno-lib-kids-closed
  id: "20260915-01"
  url: "https://www.hanno-lib.jp/calendar/"
  content_hash: "sha256-0000000000000000"
YAML

mkdir -p calendar/tests/seed/cal-lib-closed-keep-past/2026
sed -e 's/20260915/20260601/g' -e 's/2026-09-15/2026-06-01/g' \
    calendar/tests/seed/cal-lib-closed-delete/2026/09-15_libkids-closed-20260915-01.yaml \
  > calendar/tests/seed/cal-lib-closed-keep-past/2026/06-01_libkids-closed-20260601-01.yaml
```

`delete` 側の 2026-09-15 は取得範囲の内側かつ `today` (2026-08-24) 以降なので
消える。`keep-past` 側の 2026-06-01 は `today` より前なので残る。**fixture の
`closing_day` に 2026-09-15 が含まれていないことを確認すること** — 含まれていたら
別の日付に変える。

```bash
python3 -c "
import json
d = json.load(open('calendar/tests/fixtures/cal-lib-closed-fetch/cal-02.json'))
days = [x for t in d['libraries'][0]['term'] for x in (t.get('closing_day') or [])]
print('2026/09/15 in closing_day:', '2026/09/15' in days)
print('range:', min(days), '-', max(days))"
```

期待: `False` と、2026-09-15 を含む範囲。

- [ ] **Step 9: golden を生成して中身を目で見る**

```bash
python3 calendar/tests/run-golden --update
git status --short calendar/tests/golden/
```

生成された `calendar/tests/golden/cal-lib-closed-fetch/` の YAML を 1 つ開き、
summary・dtstart・source.type が想定どおりか確認する。
`cal-lib-closed-delete` に 09-15 の YAML が**無い**こと、
`cal-lib-closed-keep-past` に 06-01 の YAML が**ある**ことを確認する。

```bash
ls calendar/tests/golden/cal-lib-closed-delete/ | grep 09-15 && echo "NG: 消えていない" || echo "OK: 消えた"
ls calendar/tests/golden/cal-lib-closed-keep-past/ | grep 06-01 && echo "OK: 残った" || echo "NG: 消えた"
```

- [ ] **Step 10: テスト一式を通す**

```bash
python3 calendar/tests/run-golden
for t in calendar/tests/test_*.py; do echo "--- $t"; python3 "$t" || break; done
```

Expected: `All golden checks passed` と全ユニットテストの `OK:`

- [ ] **Step 11: Commit**

```bash
git add calendar/bin/cal-lib-closed-fetch calendar/tests/test_lib_closed.py \
        calendar/tests/fixtures/cal-lib-closed-fetch calendar/tests/seed/cal-lib-closed-* \
        calendar/tests/golden/cal-lib-closed-* calendar/tests/run-golden
git commit -m "feat(calendar): 図書館の休館日クローラ (集合同期型)"
```

---

### Task 4: `cal-lib-event-fetch` (イベント、追記型)

**Files:**
- Create: `calendar/bin/cal-lib-event-fetch`
- Create: `calendar/tests/test_lib_event.py`
- Create: `calendar/tests/fixtures/cal-lib-event-fetch/`
- Modify: `calendar/tests/run-golden`

**Interfaces:**
- Consumes: Task 2 の `_hanno_lib.*`、`_lib.fetch_with_cache` /
  `load_http_cache` / `save_http_cache` / `strip_html` / `collapse_space` /
  `normalize_body` / `output_path_for` / `existing_content_hash_matches` /
  `call_llm` / `llm_available` / `UID_NAMESPACE` / `AI_DISCLAIMER_JP`
- Produces:
  - `parse_events_page(html: str) -> list[tuple[str, str]]` — `(詳細 URL, タイトル)`
  - `parse_detail(html: str) -> tuple[str, str]` — `(見出し, 本文)`
  - `page_name(url: str) -> str`
  - `content_hash_for(title: str, body: str, day: str) -> str`

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_lib_event.py`:

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `python3 calendar/tests/test_lib_event.py`
Expected: FAIL — `FileNotFoundError`

- [ ] **Step 3: クローラを書く**

Create `calendar/bin/cal-lib-event-fetch` (実行権限を付ける):

```python
#!/usr/bin/env python3
"""cal-lib-event-fetch — 飯能市立図書館のイベント → YAML.

3 段で辿る:
  1. cal.php の event_day  … その館でイベントがある日
  2. events.php?term_from=<日>  … その日の記事タイトルと詳細 URL
     (term_to は無視されるので 1 日 1 リクエスト)
  3. /calendar/<page>.html  … 本文 (静的・Last-Modified あり → 条件付き GET)

**追記型クローラ**。events.php は当月以外も返すが、過去に流れた記事が一覧から
消えても削除しない (集合同期型ではない)。

**1 記事 1 件ではなく日ごとに 1 件**作る。「8月のおはなしのじかん(8月1・2…日)」
のような記事は events.php が該当日それぞれで返しており、配信元が「その日の
イベント」として出している形をそのまま写す。

**件数では異常を測れない。** event_day が 0 件の期間は普通にある。疎通の判定は
_hanno_lib.terms_of() が cal.php の応答形を検査することで行う。

設計: docs/superpowers/specs/2026-08-24-hanno-lib-calendar-design.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (  # noqa: E402
    UID_NAMESPACE, AI_DISCLAIMER_JP,
    load_source_config, load_http_cache, save_http_cache, fetch_with_cache,
    strip_html, collapse_space, normalize_body, strip_markdown,
    call_llm, llm_available, output_path_for, existing_content_hash_matches,
    yaml_escape_str, yaml_block_scalar,
)
from _hanno_lib import month_window, fetch_cal, terms_of, days_of, fetch_text  # noqa: E402


SOURCE_KEY = "lib-event"

MIN_BODY_CHARS = 30          # これ未満なら LLM を呼ばない
FULL_TEXT_THRESHOLD = 400    # これ以下は全文掲載 (引用扱い、AI ラベル無し)

LLM_MODEL = "claude-haiku-4-5"
LLM_MAX_TOKENS = 1024

SUMMARY_SYSTEM_PROMPT = """あなたは飯能市立図書館のイベント記事から、市民向けカレンダーに載せる要約を作るアシスタントです。

これは自動パイプラインの一部で、あなたの出力はプログラムがそのまま解釈します。人間との対話ではありません。前置き・後書き・質問はしないでください。

- 全体で 200〜400 字程度の日本語。
- 日時・場所・対象・持ち物・申込方法など、市民の行動に関わる事実は省略しない。本文に書かれていないことは書かない (推測禁止)。
- 日付は本文表記のまま (令和8年8月22日 等)。
- 出だしに「お知らせ:」のような冗語は不要。本題から始める。
- 末尾に URL や「詳細は〜」を付けない。呼出側で付与する。
- **Markdown 記法は一切使わない**。出力先は Google カレンダーの予定欄で、literal なテキストとして表示される。箇条書きは行頭「・」、見出しは「【見出し】」。
"""

_ARTICLE_RE = re.compile(r"<article.*?</article>", re.S)
_LINK_RE = re.compile(r"""<a\s+href=["']([^"']+)["']\s*>(.*?)</a>""", re.S)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_IMG_RE = re.compile(r"<img[^>]*>", re.I)


def parse_events_page(html: str) -> list[tuple[str, str]]:
    """events.php の <article> から (詳細 URL, タイトル) を返す.

    <article> が無ければ ValueError — ページ構造の変化を静かに握り潰さない。
    <article> はあるがリンクが無いのは正常 (イベント 0 件の日)。
    """
    m = _ARTICLE_RE.search(html)
    if not m:
        raise ValueError("events.php: <article> が無い (ページ構造変化の可能性)")
    out: list[tuple[str, str]] = []
    for url, raw_title in _LINK_RE.findall(m.group(0)):
        title = collapse_space(strip_html(raw_title))
        if url and title:
            out.append((url, title))
    return out


def parse_detail(html: str) -> tuple[str, str]:
    """詳細ページから (見出し, 本文テキスト) を返す.

    見出しは本文から取り除く (summary に使うので description で重複させない)。
    画像は取り込まない (利用条件の記載が無く、この repo は CC0)。
    """
    m = _ARTICLE_RE.search(html)
    if not m:
        raise ValueError("詳細ページ: <article> が無い (ページ構造変化の可能性)")
    art = m.group(0)
    h1 = _H1_RE.search(art)
    title = collapse_space(strip_html(h1.group(1))) if h1 else ""
    body_html = _H1_RE.sub("", art)
    body_html = _IMG_RE.sub("", body_html)
    return title, normalize_body(strip_html(body_html))


def page_name(url: str) -> str:
    """詳細ページ URL から UID に使う識別子を取る (末尾の .html を落とす).

    タイトルから作らないのは、タイトルが直ると UID が変わって別イベントに
    なってしまうため。
    """
    last = url.rstrip("/").split("/")[-1]
    return last[:-5] if last.endswith(".html") else last


def content_hash_for(title: str, body: str, day: str) -> str:
    """イベント 1 件の content_hash. **要約手法や生成条件は混ぜない.**

    混ぜると手法を変えた瞬間に全件のハッシュが変わり、カレンダーが氾濫する。
    """
    canonical = json.dumps({"title": title, "body": body, "day": day},
                           ensure_ascii=False, sort_keys=True)
    return "sha256-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def summarize(title: str, body: str) -> str | None:
    raw = call_llm(SUMMARY_SYSTEM_PROMPT, f"# {title}\n\n{body}",
                   model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS)
    return strip_markdown(raw.strip(), bullet="・") if raw else None


def build_description(title: str, body: str, url: str) -> tuple[str, str]:
    """(description, summary_method) を返す."""
    if not body or len(body) < MIN_BODY_CHARS:
        return url, "url-only"
    if len(body) <= FULL_TEXT_THRESHOLD:
        return f"{body}\n\n{url}", "full"
    s = summarize(title, body) if llm_available() else None
    if s:
        return f"{AI_DISCLAIMER_JP}\n\n{s}\n\n{url}", "llm-haiku-4-5"
    # LLM 不可 / 失敗時は full。method を full にしておけば content_hash は
    # 変わらない (hash に method を含めていないため)。
    return f"{body}\n\n{url}", "full"


def build_yaml_doc(uid: str, lib: dict, summary: str, url: str, day: str,
                   description: str, method: str, content_hash: str,
                   page: str) -> str:
    lines = [
        f"uid: {yaml_escape_str(uid)}",
        f"summary: {yaml_escape_str(summary)}",
        f"location: {yaml_escape_str(lib['name'])}",
        f"url: {yaml_escape_str(url)}",
        f"dtstart: {yaml_escape_str(day)}",
        f"dtend: {yaml_escape_str(day)}",
        "description: " + yaml_block_scalar(description, indent=2),
        "",
        "render:",
        "  gcal:",
        "    mode: single-allday",
        "",
        "source:",
        f"  type: {lib['source_type']}",
        f"  id: {yaml_escape_str(page)}",
        f"  url: {yaml_escape_str(url)}",
        f"  content_hash: {yaml_escape_str(content_hash)}",
        f"  summary_method: {yaml_escape_str(method)}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    default_out_dir = os.path.join(here, "..", "events")
    cfg = load_source_config(SOURCE_KEY)

    ap = argparse.ArgumentParser(description="飯能市立図書館のイベント → YAML")
    ap.add_argument("--out-dir", default=default_out_dir)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--today", default=None, help="取得ウィンドウの基準日 (テスト用)")
    ap.add_argument("--max-event-days", type=int,
                    default=int(cfg.get("max_event_days", 60)),
                    help="events.php を叩く日数の上限 (暴走防止)")
    args = ap.parse_args()

    host = cfg["cal_url"].split("/")[2]
    if host != cfg["url_host_allowlist"]:
        sys.exit(f"URL outside allowlist: {cfg['cal_url']}")

    today = args.today or _date.today().isoformat()
    term_from, term_to = month_window(today, int(cfg["months_ahead"]))

    http_cache = load_http_cache()
    written = skipped = 0

    for lib in cfg["libraries"]:
        code = lib["code"]
        # 取得層が死んだら terms_of が ValueError を投げる (件数では測れないので
        # ここが疎通の判定)。
        cal_json = fetch_cal(cfg["cal_url"], code, term_from, term_to)
        terms = terms_of(cal_json, code)
        days = days_of(terms, "event_day")
        if len(days) > args.max_event_days:
            print(f"  WARN: {code} event_day {len(days)} 日 > "
                  f"--max-event-days {args.max_event_days}、先頭だけ処理する",
                  file=sys.stderr)
            days = days[:args.max_event_days]
        print(f"{code} {lib['name']}: {len(days)} event days", file=sys.stderr)

        for day in days:
            ymd = day.replace("-", "")
            ev_url = (f"{cfg['events_url']}?kind=2&target=general"
                      f"&libraries={code}&term_from={ymd}")
            for detail_url, list_title in parse_events_page(fetch_text(ev_url)):
                if (detail_url.split("/")[2] != cfg["url_host_allowlist"]
                        or cfg["url_path_prefix"] not in detail_url):
                    print(f"  WARN: allowlist 外、skip: {detail_url}", file=sys.stderr)
                    continue
                page = page_name(detail_url)
                entry = http_cache.get(detail_url, {})
                html, etag, lm = fetch_with_cache(
                    detail_url, entry.get("etag"), entry.get("last_modified"))
                if html is None:
                    # 304。ただし同じ記事が別の日に新しく載ることがあるので、
                    # その日の YAML が無ければ本文を取り直す。
                    html = fetch_text(detail_url)
                else:
                    http_cache[detail_url] = {"etag": etag, "last_modified": lm}

                title, body = parse_detail(html)
                title = title or list_title
                ch = content_hash_for(title, body, day)
                uid = f"{lib['uid_prefix']}-{page}-{ymd}@{UID_NAMESPACE}"
                out_path = output_path_for(args.out_dir, uid, day)
                if existing_content_hash_matches(out_path, ch):
                    skipped += 1
                    continue

                description, method = build_description(title, body, detail_url)
                doc = build_yaml_doc(uid, lib,
                                     f"{cfg['summary_prefix']}{title}",
                                     detail_url, day, description, method, ch, page)
                if args.dry_run:
                    written += 1
                    continue
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(doc)
                written += 1

    if not args.dry_run:
        save_http_cache(http_cache)
    print(f"Done. written={written} skipped={skipped}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

```bash
chmod +x calendar/bin/cal-lib-event-fetch
```

- [ ] **Step 4: ユニットテストが通ることを確認する**

Run: `python3 calendar/tests/test_lib_event.py`
Expected: `OK: all lib-event tests passed`

- [ ] **Step 5: 実データで一度動かす (書き込みなし)**

```bash
source ~/.setenv 2>/dev/null
export ANTHROPIC_API_KEY=$(grep '^setenv ANTHROPIC_API_KEY' ~/.setenv | tail -1 | awk '{print $3}')
./calendar/bin/cal-lib-event-fetch --out-dir /tmp/libevtest --dry-run
```

期待: 02 の event days が十数件、`Done. written=… skipped=0`。

- [ ] **Step 6: fixture を採る**

`--today 2026-08-24` で走らせたときに叩く URL をすべて固める。実際に叩かれる
URL は上の dry-run の出力から分かるが、確実を期すため取得をログに出して集める。

```bash
mkdir -p calendar/tests/fixtures/cal-lib-event-fetch
python3 - <<'PY'
import json, os, sys, urllib.request
BIN = "calendar/bin"
sys.path.insert(0, BIN)
import _hanno_lib
FIX = "calendar/tests/fixtures/cal-lib-event-fetch"
UA = "myhanno-calendar-fetcher/0.1 (+https://city.tecoli.com)"
manifest, n = {}, [0]

def save(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    text = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    n[0] += 1
    name = f"f{n[0]:03d}." + ("json" if "cal.php" in url else "html")
    open(os.path.join(FIX, name), "w", encoding="utf-8").write(text)
    manifest[url] = name
    return text

orig = _hanno_lib.fetch_text
_hanno_lib.fetch_text = save
import importlib.machinery, importlib.util
ldr = importlib.machinery.SourceFileLoader("m", os.path.join(BIN, "cal-lib-event-fetch"))
spec = importlib.util.spec_from_loader("m", ldr)
m = importlib.util.module_from_spec(spec); ldr.exec_module(m)
m.fetch_text = save
m.fetch_with_cache = lambda url, e, l: (save(url), None, None)
m.load_http_cache = lambda: {}
m.save_http_cache = lambda c: None
m.llm_available = lambda: False      # fixture 採取では LLM を呼ばない
sys.argv = ["m", "--out-dir", "/tmp/libevfix", "--today", "2026-08-24", "--dry-run"]
m.main()
json.dump(manifest, open(os.path.join(FIX, "manifest.json"), "w"),
          ensure_ascii=False, indent=1, sort_keys=True)
print(f"saved {len(manifest)} fixtures")
PY
```

- [ ] **Step 7: run-golden に配線する**

`TODAY_BY_CRAWLER` に足す:

```python
    "cal-lib-event-fetch": "2026-08-24",
```

`DETERMINISTIC_DATE_CRAWLERS` に足す (dtstart は event_day 由来で実行日に依存
しない):

```python
                               "cal-cci-event-fetch", "cal-lib-closed-fetch",
                               "cal-lib-event-fetch"}
```

`_setup_lib` に LLM 無効化を足す (要約は非決定的なので golden では呼ばない。
本文が短い記事は `full` なので解析経路はそのまま走る):

```python
    m.llm_available = lambda: False
```

`CRAWLERS` に 1 本足す:

```python
    # 図書館のイベント (追記型)。event_day → events.php → 詳細ページの 3 段を
    # 通す。要約は LLM 無効化で full 経路に倒している。
    ("cal-lib-event-fetch", "cal-lib-event-fetch", _setup_lib, None),
```

- [ ] **Step 8: golden を生成して中身を目で見る**

```bash
python3 calendar/tests/run-golden --update
ls calendar/tests/golden/cal-lib-event-fetch/
```

YAML を 1 つ開き、`summary` に `📚 ` が付き、`dtstart` が `event_day` の日付で、
`description` の末尾に詳細 URL があることを確認する。**同じ記事が複数日ぶん
別ファイルで出ていること**も確認する (「8月のおはなしのじかん」)。

- [ ] **Step 9: テスト一式を通す**

```bash
python3 calendar/tests/run-golden
for t in calendar/tests/test_*.py; do echo "--- $t"; python3 "$t" || break; done
```

Expected: `All golden checks passed` と全ユニットテストの `OK:`

- [ ] **Step 10: httpx 不在でも import できることを確認する**

golden 網は `pyyaml` しか入れない。`_lib` の httpx は guard 済みだが、新しい
クローラが裸で httpx を import していないことを確かめる。

```bash
mkdir -p /tmp/nohttpx
cat > /tmp/nohttpx/sitecustomize.py <<'PY'
import sys
class _Block:
    def find_module(self, name, path=None):
        return self if name == "httpx" else None
    def load_module(self, name):
        raise ImportError(f"No module named {name!r}")
sys.meta_path.insert(0, _Block())
PY
PYTHONPATH=/tmp/nohttpx python3 calendar/tests/run-golden
for t in calendar/tests/test_*.py; do PYTHONPATH=/tmp/nohttpx python3 "$t" >/dev/null || echo "FAIL $t"; done
```

Expected: golden が通り、`FAIL` が 1 つも出ない。

- [ ] **Step 11: Commit**

```bash
git add calendar/bin/cal-lib-event-fetch calendar/tests/test_lib_event.py \
        calendar/tests/fixtures/cal-lib-event-fetch calendar/tests/golden/cal-lib-event-fetch \
        calendar/tests/run-golden
git commit -m "feat(calendar): 図書館のイベントクローラ (追記型)"
```

---

### Task 5: CI 配線と初回取込

**Files:**
- Modify: `.github/workflows/cal-daily.yml`
- Modify: `calendar/README.md`
- Delete: `.github/workflows/probe-lib-endpoints.yml`
- Modify: `calendar/events/**` (初回取込の結果)

**Interfaces:**
- Consumes: Task 1〜4 のすべて

- [ ] **Step 1: 初回取込を手元で実行する**

**CI に初回を任せない。** 差分を目で見る。

```bash
export ANTHROPIC_API_KEY=$(grep '^setenv ANTHROPIC_API_KEY' ~/.setenv | tail -1 | awk '{print $3}')
./calendar/bin/cal-lib-closed-fetch --out-dir calendar/events
./calendar/bin/cal-lib-event-fetch  --out-dir calendar/events
git status --short calendar/events | head -30
git status --short calendar/events | wc -l
```

期待: 休館日が 100 件前後、イベントが十数件。想定と桁が違ったら止める。

- [ ] **Step 2: `.http-cache.json` の新規エントリを外す**

```bash
git diff calendar/.http-cache.json | head -20
git checkout calendar/.http-cache.json
```

commit すると最初の CI 実行が 304 で全 skip する。**必ず戻す。**

- [ ] **Step 3: 生成された YAML を目で見る**

```bash
ls calendar/events/2026 | grep -c libkids-closed
cat "$(ls calendar/events/2026/*libkids-closed* | head -1)"
cat "$(ls calendar/events/2026/*libkids-event* | head -1)"
```

`uid` / `summary` / `source.type` が Task 1 で登録した `source_type` と一致して
いることを確認する。ずれていると YAML は増えるがカレンダーに出ない。

- [ ] **Step 4: cal-daily.yml に Crawl 2 ステップを足す**

`Crawl hanno-cci-event` ステップの**後ろ**に追記する。新顔を先頭に置くと、
遮断されたときに既存クローラを人質に取ることになる。

```yaml
      # 注: 図書館は cci-event の後ろに置く。新しい配信元が遮断されると同一 IP
      # からの他クローラまで巻き添えで落ちるため (2026-08-20 実測)、先に既存を通す。
      - name: Crawl hanno-lib-closed
        # 図書館の休館日。集合同期型。取得側に無い日は YAML から削除される。
        # 削除ガードは _lib.plan_set_sync (取得範囲内かつ今日以降のみ、上限超過なら
        # exit 3 で何も書かない)。LLM 不使用なので API キーは要らない。
        #
        # 件数チェックは館ごと・月ごと (--min-days-per-month)。総数の固定値は使えない
        # — 休館日は年度単位で登録されており、取れる月数が観測時期で 1〜12 か月に
        # 変わるため、年度末に近づくと正常時でも下回る。
        run: ./calendar/bin/cal-lib-closed-fetch --out-dir calendar/events || echo "hanno-lib-closed" >> "$RUNNER_TEMP/crawl-failures.txt"

      - name: Crawl hanno-lib-event
        # 図書館のイベント。追記型。cal.php の event_day → events.php → 詳細ページ。
        # ANTHROPIC_API_KEY が無いと長文記事の description が要約から本文そのままに
        # 変わる。content_hash には method を含めていないのでハッシュは動かないが、
        # ローカルと CI で出力が変わるのは避ける。
        #
        # --min-items 相当の件数チェックは持たない。event_day が 0 件の期間は普通に
        # あり (本館 01 は 2026-08 時点で全月 0)、0 を異常とすると常時赤になる。
        # 疎通は _hanno_lib.terms_of() が cal.php の応答形を検査して担保している。
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: ./calendar/bin/cal-lib-event-fetch --out-dir calendar/events || echo "hanno-lib-event" >> "$RUNNER_TEMP/crawl-failures.txt"
```

- [ ] **Step 5: prune を `--update-manual` より前に足す**

`Prune removed chef events from Calendar` ステップの**直後**、
`Fetch manual Calendar additions` の**前**に追記する。

```yaml
      - name: Prune removed library closures from Calendar
        # chef と同じ理由でこの位置。**"Fetch manual Calendar additions" より前**
        # でなければならない。後ろに置くと、YAML を消したのに Calendar に残った
        # 孤児を fetch --update-manual が source: なしの YAML として拾い、以後
        # 「手動キュレーション = 不可侵」扱いになって二度と削除できなくなる。
        env:
          GOOGLE_APPLICATION_CREDENTIALS: /tmp/sa.json
        run: |
          ./calendar/bin/cal-gcal prune --uid-prefix libmain-closed -d calendar/events --snapshot-dir calendar/snapshots
          ./calendar/bin/cal-gcal prune --uid-prefix libkids-closed -d calendar/events --snapshot-dir calendar/snapshots
```

- [ ] **Step 6: ワークフローの YAML を検証する**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('.github/workflows/cal-daily.yml'))
names = [s.get('name') for s in d['jobs']['daily']['steps']]
i_prune = names.index('Prune removed library closures from Calendar')
i_fetch = names.index('Fetch manual Calendar additions + sync manual edits')
assert i_prune < i_fetch, (i_prune, i_fetch)
assert names.index('Crawl hanno-cci-event') < names.index('Crawl hanno-lib-closed')
print('OK: ステップ順序')"
```

期待: `OK: ステップ順序`

- [ ] **Step 7: README に節を足す**

`calendar/README.md` の `## bin/cal-translate-en` の**前**に追記する。

````markdown
## bin/cal-lib-closed-fetch / bin/cal-lib-event-fetch

飯能市立図書館 (`www.hanno-lib.jp`) の休館日とイベント。館ごとに独立した
カレンダー (`lib-main` / `lib-kids`、各 `.en`) へ配信する。
設計: `docs/superpowers/specs/2026-08-24-hanno-lib-calendar-design.md`

取得層は `bin/_hanno_lib.py` に集約している (2 クローラが同じ `cal.php` を読む)。

```
cal.php?libraries=<館>&term_from=YYYYMM&term_to=YYYYMM  → closing_day[] / event_day[]
events.php?kind=2&target=general&libraries=<館>&term_from=YYYYMMDD → その日の記事
/calendar/<page>.html                                    → 本文 (Last-Modified あり)
```

**1 リクエスト 1 館。** `libraries=01,02` とまとめると `event_day` が空で返る。

**取得できる範囲は年度末までで固定の月数ではない。** 休館日は年度単位で登録され、
取れる月数は観測時期で 1〜12 か月に変わる。`months_ahead: 12` は「配信元が持ちうる
最大」で、返った分だけを扱う。この性質があるので、休館日の件数チェックは
**館ごと・月ごと** (`--min-days-per-month`) で見る。総数の固定値だと年度末に
近づいたとき正常時でも赤になる。

**イベントは件数で異常を測れない。** `event_day` が 0 件の期間は普通にある
(本館 01 は 2026-08 時点で全月 0 件)。疎通は `_hanno_lib.terms_of()` が `cal.php`
の応答形を検査して担保している。

`rrule` は使わない。ページに規則が書いてあるが、`closing_day` には規則から導け
ない日 (祝日の翌日など) が入っており、配信元は個別の日付を列挙している。
````

- [ ] **Step 8: probe ワークフローを消す**

判定は付いた (設計書 3 節に結果を記録済み)。

```bash
git rm .github/workflows/probe-lib-endpoints.yml
```

- [ ] **Step 9: テスト一式を通す**

```bash
python3 calendar/tests/run-golden
for t in calendar/tests/test_*.py; do echo "--- $t"; python3 "$t" || break; done
```

Expected: すべて緑

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(calendar): 図書館クローラを CI に配線し初回取込"
```

- [ ] **Step 11: push して CI を見る**

**push はユーザの確認を取ってから。**

```bash
git push origin main
gh run list --limit 3
```

`Calendar daily` が緑で、ログに `hanno-lib-closed` / `hanno-lib-event` の行が
出ていることを確認する。赤なら `gh run view <id> --log-failed` で原因を見る。

- [ ] **Step 12: カレンダーに出ていることを確認する**

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/city-tecoli/calendar-sa.json
./calendar/bin/cal-gcal snapshot -o /tmp/libsnap
ls /tmp/libsnap
```

`lib-main` / `lib-kids` のスナップショットにイベントが入っていることを確認する。
入っていなければ `city.yaml` の `source_type_to_calendar` を疑う (**ここが
抜けていると YAML は増えるがカレンダーに出ない**)。

---

## 自己レビュー結果

**1. スペック網羅:** 設計書 13 節すべてにタスクを当てた。
2 節 (取り込み方針) はコード上の帰結が「画像を取り込まない」だけなので
Task 4 の `parse_detail` (`_IMG_RE` で除去) と Global Constraints に落とした。
4 節の place_id は Task 1 Step 5 のコメントに残す。

**2. プレースホルダ:** `<Step 2 で返った ID>` と `<ID>` は Task 1 の実行結果を
貼る箇所で、値を先に書けない性質のもの。それ以外に TBD / TODO は無い。

**3. 型の一貫性:** `_hanno_lib` の 5 関数名は Task 2 の定義と Task 3/4 の呼出で
一致。`closing_items` の引数は 4 つ (`days, lib, page_url, summary_prefix`) で
テストと実装で一致。`content_hash_for(title, body, day)` の順序もテストと実装で
一致。`sync_set` の `render_doc` は `(uid, item, source_id, content_hash)` の
4 引数で、`_lib.sync_set` の呼出規約と一致。

**4. スペックとのずれ (意図的、1 件):** 設計書は「クローラ 2 本」としか書いて
いないが、共有モジュール `_hanno_lib.py` を足した。理由は File Structure 節に
記載。
