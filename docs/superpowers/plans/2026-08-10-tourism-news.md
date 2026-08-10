# hanno-tourism.jp `news` 投稿タイプ対応 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** hanno-tourism.jp の `news` 投稿タイプを巡回し、告知 (掲載日) と本番 (開催日) の 2 系統のイベント YAML を生成する。

**Architecture:** 新規スクリプト `calendar/bin/cal-tourism-news-fetch` が WordPress REST API から全件を取得し (HTML 取得なし)、変更分だけ Haiku 4.5 に投げて `{summary, event_date, event_end_date, date_evidence, status}` の JSON を得る。開催日は LLM 抽出 + 機械検証 5 項目の二重チェックを通過した場合のみ本番エントリにする。LLM 呼び出しは `_lib.call_llm()` に共通化し `cal-oshirase-fetch` も載せ替える。

**Tech Stack:** Python 3.10、標準ライブラリ + `httpx` (LLM 呼び出し) + `pyyaml` (設定読み込みのみ)。テストは pytest を使わない素の assert。

**設計仕様:** `docs/superpowers/specs/2026-08-10-tourism-news-design.md`

## Global Constraints

- **Python 3.10 系**。`from __future__ import annotations` を先頭に置く (既存クローラ全てが従っている)。
- **テストに pytest を使わない。** `calendar/tests/test_*.py` は素の `assert` と、末尾の `if __name__ == "__main__":` で `test_` 接頭辞の関数を全て回す形式。実行は `python3 calendar/tests/test_xxx.py`。
- **テストはネットワークを使わない。** モジュールは `importlib.machinery.SourceFileLoader` で読み込み、`fetch` / `fetch_json` / `call_llm` を属性代入で差し替える。
- **LLM をテストで実呼び出ししない。** 記録済み応答を再生する。
- **`ANTHROPIC_API_KEY` が無いと `content_hash` が変動して重複イベントが大量発生する** (2026-05-26 の oshirase 障害)。CI ステップには必ず `env: ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` を付ける。
- **既存クローラの出力をバイト単位で変えない。** Task 1 の `cal-oshirase-fetch` 載せ替えは `python3 calendar/tests/run-golden` が通ることで担保する。
- モデル ID は `claude-haiku-4-5`。
- コミットは各タスク末尾で 1 回。

### 仕様書からの訂正 1 件

仕様書は 137 件の API レスポンス corpus を `calendar/tests/seed/` に置くと書いているが、
このリポジトリの `calendar/tests/seed/` は**「out-dir に事前展開する既存 YAML」**という
別の意味で既に使われている (`run-golden` の `CRAWLERS` 第 4 要素)。
corpus は `calendar/tests/corpus/` に置く。

---

### Task 1: `_lib.call_llm()` を追加し `cal-oshirase-fetch` を載せ替える

LLM 呼び出しが 3 本目になるので共通化する。**このタスクは新機能を足さない。**
`cal-oshirase-fetch` の出力がバイト単位で変わらないことが完了条件。

**Files:**
- Modify: `calendar/bin/_lib.py` (末尾に追記)
- Modify: `calendar/bin/cal-oshirase-fetch:222-298` (`summarize_with_llm` / `diff_with_llm`)
- Test: `calendar/tests/test_call_llm.py` (新規)

**Interfaces:**
- Consumes: なし (最初のタスク)
- Produces: `_lib.call_llm(system: str, user: str, *, model: str, max_tokens: int, temperature: float | None = None, timeout: int = 60) -> str | None`
  — 成功時は応答テキスト (strip 済み)、失敗・`httpx` 不在・API キー不在では `None`。
  Markdown 除去は行わない (呼び出し側の責務)。
- Produces: `_lib.llm_available() -> bool` — `httpx` が import でき、かつ `ANTHROPIC_API_KEY` が設定されているか。

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_call_llm.py`:

```python
#!/usr/bin/env python3
"""_lib.call_llm のユニットテスト。httpx を差し替えるのでネットワーク非依存。
実行: python3 calendar/tests/test_call_llm.py
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


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHttpx:
    """httpx.post を記録して固定応答を返す。"""

    def __init__(self, text="こんにちは"):
        self.calls = []
        self._text = text

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json,
                           "timeout": timeout})
        return _FakeResponse({"content": [{"text": self._text}]})


def _with_key(fn):
    old = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old


def test_call_llm_passes_system_and_user():
    fake = _FakeHttpx(text="  要約テキスト  ")
    lib.httpx = fake
    got = _with_key(lambda: lib.call_llm("SYS", "USER", model="claude-haiku-4-5",
                                         max_tokens=1024))
    assert got == "要約テキスト", got
    body = fake.calls[0]["json"]
    assert body["system"] == "SYS", body
    assert body["messages"] == [{"role": "user", "content": "USER"}], body
    assert body["model"] == "claude-haiku-4-5", body
    assert body["max_tokens"] == 1024, body
    assert "temperature" not in body, body
    assert fake.calls[0]["headers"]["x-api-key"] == "sk-test"
    assert fake.calls[0]["timeout"] == 60


def test_call_llm_includes_temperature_when_given():
    fake = _FakeHttpx()
    lib.httpx = fake
    _with_key(lambda: lib.call_llm("S", "U", model="m", max_tokens=256,
                                   temperature=0))
    assert fake.calls[0]["json"]["temperature"] == 0, fake.calls[0]["json"]


def test_call_llm_returns_none_without_api_key():
    lib.httpx = _FakeHttpx()
    old = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        assert lib.call_llm("S", "U", model="m", max_tokens=10) is None
    finally:
        if old is not None:
            os.environ["ANTHROPIC_API_KEY"] = old


def test_call_llm_returns_none_when_httpx_missing():
    lib.httpx = None
    assert _with_key(lambda: lib.call_llm("S", "U", model="m", max_tokens=10)) is None


def test_call_llm_returns_none_on_exception():
    class _Boom:
        def post(self, *a, **kw):
            raise RuntimeError("boom")

    lib.httpx = _Boom()
    assert _with_key(lambda: lib.call_llm("S", "U", model="m", max_tokens=10)) is None


def test_llm_available():
    lib.httpx = _FakeHttpx()
    assert _with_key(lib.llm_available) is True
    lib.httpx = None
    assert _with_key(lib.llm_available) is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all call_llm tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_call_llm.py`
Expected: FAIL — `AttributeError: module '_lib' has no attribute 'call_llm'`

- [ ] **Step 3: `_lib.py` に実装を追加**

`calendar/bin/_lib.py` の import 群に `httpx` の任意 import を足す (既存に無ければ):

```python
try:
    import httpx
except ImportError:  # CI/最小環境では未インストールのことがある
    httpx = None
```

ファイル末尾に追記:

```python
# ==================== LLM 呼び出し ====================

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def llm_available() -> bool:
    """この環境で LLM 呼出が可能か (CI 等で httpx 無 / API key 無 を事前検知)."""
    return httpx is not None and bool(os.environ.get("ANTHROPIC_API_KEY"))


def call_llm(system: str, user: str, *, model: str, max_tokens: int,
             temperature: float | None = None, timeout: int = 60) -> str | None:
    """Anthropic Messages API を 1 回叩き、応答テキストを返す。失敗時 None。

    Markdown 除去や後処理は行わない (呼出側が strip_markdown 等を掛ける)。
    temperature は省略時リクエストに含めない (API 既定に委ねる)。
    """
    if httpx is None:
        print("  WARN: httpx not installed, skipping LLM call", file=sys.stderr)
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  WARN: ANTHROPIC_API_KEY not set, skipping LLM call", file=sys.stderr)
        return None
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if temperature is not None:
        payload["temperature"] = temperature
    try:
        r = httpx.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"  WARN: LLM call failed: {e}", file=sys.stderr)
        return None
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_call_llm.py`
Expected: PASS — `OK: all call_llm tests passed`

- [ ] **Step 5: `cal-oshirase-fetch` を載せ替える**

`summarize_with_llm` の本体を差し替える。**安全装置 (`MIN_BODY_CHARS` 未満で呼ばない)
と `strip_markdown` は呼出側に残す**:

```python
def summarize_with_llm(title: str, body: str) -> str | None:
    """Claude Haiku 4.5 で要約。失敗時 None を返す (呼出側で fallback)."""
    if not body or len(body) < MIN_BODY_CHARS:
        # 安全装置: 空 body で LLM を呼ばない (ハルシネーション防止)
        return None
    text = call_llm(LLM_SYSTEM_PROMPT, f"# {title}\n\n{body}",
                    model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS)
    if text is None:
        return None
    return strip_markdown(text, bullet="・")
```

`diff_with_llm` も同様に。**`temperature=0` を落とさないこと** (差分判定のブレ対策で
意図的に入っている):

```python
def diff_with_llm(title: str, prev_summary: str, new_body: str) -> str | None:
    """前回の要約と今回の本文を比較し「主な変更」の本文を返す。失敗/変更なしは None。"""
    if not prev_summary.strip() or not new_body or len(new_body) < MIN_BODY_CHARS:
        # 安全装置: 材料が薄い状態で LLM を呼ばない (ハルシネーション防止)
        return None
    user = (f"# {title}\n\n"
            f"## 前回の要約\n\n{prev_summary}\n\n"
            f"## 今回の本文\n\n{new_body}")
    # 差分判定は創造性が不要で、ブレると「変わっていない値を変更と断定する」誤りが
    # 混入する (実測: 同一入力で 2 回中 1 回発生)。temperature を 0 に固定して抑える。
    text = call_llm(DIFF_SYSTEM_PROMPT, user, model=LLM_MODEL,
                    max_tokens=DIFF_LLM_MAX_TOKENS, temperature=0)
    if text is None:
        return None
    text = strip_markdown(text, bullet="・")
    # 改行は status header を壊すので 1 行に畳む
    return " ".join(text.split()) or None
```

`_llm_available()` は `_lib.llm_available` に委譲する。**`run-golden` が
`m._llm_available = lambda: False` で差し替えているので、この名前を残すこと**:

```python
def _llm_available() -> bool:
    """この環境で LLM 呼出が可能か。run-golden がこの名前を差し替えるので残す。"""
    return llm_available()
```

`cal-oshirase-fetch` 側で不要になった `httpx` の直接 import は残してよい
(他で使っていれば)。使っていなければ削除する。

- [ ] **Step 6: golden テストで出力不変を確認**

Run: `python3 calendar/tests/run-golden`
Expected: PASS (差分なし)。**ここで差分が出たら載せ替えを間違えている。**
`--update` で golden を書き換えてはいけない。

- [ ] **Step 7: 既存テストの回帰確認**

Run: `for t in calendar/tests/test_*.py; do echo "== $t"; python3 "$t" || break; done`
Expected: 全て PASS

- [ ] **Step 8: コミット**

```bash
git add calendar/bin/_lib.py calendar/bin/cal-oshirase-fetch calendar/tests/test_call_llm.py
git commit -m "refactor(lib): LLM 呼び出しを _lib.call_llm に共通化

news クローラで 3 本目になるため。API 呼び出し部の修正が片方だけ当たる
事故を防ぐ。cal-oshirase-fetch の出力は golden テストで不変を確認済み。"
```

---

### Task 2: 囲み曜日文字の正規化を `_lib.py` に追加

「飯能河原6/27㈯・28㈰の営業について」のような囲み曜日文字が実データに存在する。
機械検証の曜日一致判定がこれを読めないと本番を作り損ねる。

**Files:**
- Modify: `calendar/bin/_lib.py`
- Test: `calendar/tests/test_normalize_weekday.py` (新規)

**Interfaces:**
- Consumes: なし
- Produces: `_lib.normalize_circled_weekday(s: str) -> str`
  — `㈪㈫㈬㈭㈮㈯㈰` および `㊊㊋㊌㊍㊎㊏㊐` を `(月)`〜`(日)` に変換する。

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_normalize_weekday.py`:

```python
#!/usr/bin/env python3
"""_lib.normalize_circled_weekday のユニットテスト。
実行: python3 calendar/tests/test_normalize_weekday.py
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


def test_parenthesized_form():
    # 実データ: 「飯能河原6/27㈯・28㈰の営業について」
    got = lib.normalize_circled_weekday("飯能河原6/27㈯・28㈰の営業について")
    assert got == "飯能河原6/27(土)・28(日)の営業について", got


def test_circled_kanji_form():
    got = lib.normalize_circled_weekday("3月21日㊏案内業務お休み")
    assert got == "3月21日(土)案内業務お休み", got


def test_all_seven_days():
    src = "㈪㈫㈬㈭㈮㈯㈰"
    assert lib.normalize_circled_weekday(src) == "(月)(火)(水)(木)(金)(土)(日)"


def test_leaves_other_text_untouched():
    src = "日時:2026年8月8日(土) 午後5時〜"
    assert lib.normalize_circled_weekday(src) == src


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all normalize-weekday tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_normalize_weekday.py`
Expected: FAIL — `AttributeError: module '_lib' has no attribute 'normalize_circled_weekday'`

- [ ] **Step 3: 実装**

`calendar/bin/_lib.py` の `normalize_tilde` の直後に追加:

```python
# U+3288-U+328D (㈈〜㈍ 系) のうち曜日を表すもの、および U+328A-U+3290 の丸囲み漢字。
# 実データに「6/27㈯・28㈰」「3月21日㊏」の両形式が出現する。
_CIRCLED_WEEKDAY = {
    "㈪": "(月)", "㈫": "(火)", "㈬": "(水)", "㈭": "(木)",
    "㈮": "(金)", "㈯": "(土)", "㈰": "(日)",
    "㊊": "(月)", "㊋": "(火)", "㊌": "(水)", "㊍": "(木)",
    "㊎": "(金)", "㊏": "(土)", "㊐": "(日)",
}


def normalize_circled_weekday(s: str) -> str:
    """囲み曜日文字 (㈯ / ㊏ 等) を `(土)` 形式に開く。

    日付の曜日整合チェックが読めるようにするための前処理。
    """
    out = []
    for c in s:
        out.append(_CIRCLED_WEEKDAY.get(c, c))
    return "".join(out)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_normalize_weekday.py`
Expected: PASS

- [ ] **Step 5: golden テストで既存出力が不変であることを確認**

Run: `python3 calendar/tests/run-golden`
Expected: PASS (この関数はまだどこからも呼ばれていないので差分ゼロのはず)

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/_lib.py calendar/tests/test_normalize_weekday.py
git commit -m "feat(lib): 囲み曜日文字 (㈯/㊏) の正規化を追加

hanno-tourism.jp news の実データに「6/27㈯・28㈰」形式が存在し、
曜日整合チェックが読めないため。"
```

---

### Task 3: `sources.yaml` エントリと REST API 取得層

**Files:**
- Create: `calendar/bin/cal-tourism-news-fetch`
- Modify: `calendar/sources.yaml`
- Test: `calendar/tests/test_news_api.py` (新規)

**Interfaces:**
- Consumes: なし
- Produces:
  - `fetch_json(url: str) -> object` — `cal-tourism-fetch` と同じ形の薄いラッパ。テストで差し替える対象。
  - `fetch_news_index(months: int, today: date) -> list[dict]`
    — 各要素は `{"id": int, "url": str, "title": str, "body_html": str,
      "modified_gmt": str, "date_gmt": str, "tags": list[int]}`。
      `date_gmt` が `today - months` より古いものは除外する。
  - `select_news_to_fetch(items: list[dict], cache: dict) -> tuple[list[dict], int]`
    — `(処理対象, スキップ数)`。`cache[url]["modified_gmt"]` が一致すればスキップ。
  - `API_URL` / `PER_PAGE` / `EVENT_TAG_IDS` モジュール定数。

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_news_api.py`:

```python
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
    """fetch_json を差し替え、page 番号ごとに固定リストを返す。"""
    def _f(url):
        n = 1
        if "page=" in url:
            n = int(url.split("page=")[1].split("&")[0])
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
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_news_api.py`
Expected: FAIL — `FileNotFoundError: calendar/bin/cal-tourism-news-fetch`

- [ ] **Step 3: `sources.yaml` にエントリを追加**

`calendar/sources.yaml` の末尾に追記:

```yaml
tourism-news:
  uid_prefix: tourism-news
  source_type: hanno-tourism-jp-news
  # 告知エントリ (掲載日) と本番エントリ (開催日) で prefix を変える。
  # 本番側はイベント系タグの有無で決定論的に選ぶ (LLM の判断を挟まない)。
  summary_prefix_notice: "📢 "
  summary_prefix_event: "🎪 "
  summary_prefix_other: "ℹ️ "
  api_url: "https://hanno-tourism.jp/wp-json/wp/v2/news"
  url_host_allowlist: hanno-tourism.jp
  url_path_prefix: "/news/"
  backfill_months: 6
```

- [ ] **Step 4: スクリプトの骨格と取得層を実装**

`calendar/bin/cal-tourism-news-fetch` を新規作成 (実行可能にする):

```python
#!/usr/bin/env python3
"""cal-tourism-news-fetch — hanno-tourism.jp の news 投稿タイプからイベント YAML を生成する。

告知 (掲載日) と本番 (開催日) の 2 系統を出す。開催日は LLM 抽出 + 機械検証の
二重チェックを通過した場合のみ採用する。

対象: https://hanno-tourism.jp/news/<slug>/
設計: docs/superpowers/specs/2026-08-10-tourism-news-design.md

  cal-tourism-news-fetch --out-dir calendar/events
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (  # noqa: E402
    USER_AGENT, load_source_config, load_http_cache, save_http_cache,
)

JST = timezone(timedelta(hours=9))

_SRC = load_source_config("tourism-news")
DEFAULT_UID_PREFIX = _SRC["uid_prefix"]
SOURCE_TYPE = _SRC["source_type"]
SUMMARY_PREFIX_NOTICE = _SRC["summary_prefix_notice"]
SUMMARY_PREFIX_EVENT = _SRC["summary_prefix_event"]
SUMMARY_PREFIX_OTHER = _SRC["summary_prefix_other"]
API_URL = _SRC["api_url"]
URL_HOST_ALLOWLIST = _SRC["url_host_allowlist"]
URL_PATH_PREFIX = _SRC["url_path_prefix"]
DEFAULT_BACKFILL_MONTHS = int(_SRC["backfill_months"])

PER_PAGE = 100
API_FIELDS = "id,link,slug,date_gmt,modified_gmt,title,content,tag-news"

# tag-news のうちイベント系。掲載可否の判定には使わず、表示用 prefix の選択のみ。
# 6=イベント, 7=飯能まつり, 8=エコツアー
EVENT_TAG_IDS = {6, 7, 8}


def fetch_json(url: str) -> object:
    """REST API を叩いて JSON を返す。テストで差し替える対象。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _months_ago(today: date, months: int) -> date:
    """today から months ヶ月前の日付。月末の切り上がりは 1 日に丸める。"""
    y, m = today.year, today.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def fetch_news_index(months: int, today: date) -> list[dict]:
    """REST API から news 一覧を取得し、months ヶ月以内の記事だけ返す。

    per_page=100 で全ページを辿る (実測 137 件 = 2 リクエスト)。
    content.rendered が API に露出しているので HTML の追加取得は不要。
    """
    cutoff = _months_ago(today, months).isoformat()
    out: list[dict] = []
    page = 1
    while True:
        url = (f"{API_URL}?per_page={PER_PAGE}&page={page}"
               f"&_fields={API_FIELDS}")
        batch = fetch_json(url)
        if not isinstance(batch, list) or not batch:
            break
        for it in batch:
            date_gmt = it.get("date_gmt", "")
            if date_gmt[:10] < cutoff:
                continue
            out.append({
                "id": it.get("id"),
                "url": it.get("link", ""),
                "title": (it.get("title") or {}).get("rendered", ""),
                "body_html": (it.get("content") or {}).get("rendered", ""),
                "date_gmt": date_gmt,
                "modified_gmt": it.get("modified_gmt", ""),
                "tags": list(it.get("tag-news") or []),
            })
        if len(batch) < PER_PAGE:
            break
        page += 1
    return out


def select_news_to_fetch(items: list[dict], cache: dict) -> tuple[list[dict], int]:
    """modified_gmt が前回と一致する記事をスキップする。

    hanno-tourism.jp は ETag / Last-Modified を返さないので条件付き GET が
    使えない。判定材料が無い記事は「処理対象」に倒す。
    """
    todo: list[dict] = []
    unchanged = 0
    for it in items:
        prev = (cache.get(it["url"]) or {}).get("modified_gmt")
        if prev and prev == it.get("modified_gmt"):
            unchanged += 1
            continue
        todo.append(it)
    return todo, unchanged
```

- [ ] **Step 5: 実行権限を付けてテストが通ることを確認**

```bash
chmod +x calendar/bin/cal-tourism-news-fetch
python3 calendar/tests/test_news_api.py
```
Expected: PASS — `OK: all news-api tests passed`

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/cal-tourism-news-fetch calendar/sources.yaml calendar/tests/test_news_api.py
git commit -m "feat(news): REST API 取得層と sources.yaml エントリを追加

content.rendered が API に露出しているので HTML の追加取得は不要。
実測 137 件が per_page=100 の 2 リクエストで完結する。"
```

---

### Task 4: LLM 抽出 (プロンプトと JSON パース)

**Files:**
- Modify: `calendar/bin/cal-tourism-news-fetch`
- Test: `calendar/tests/test_news_extract.py` (新規)

**Interfaces:**
- Consumes: Task 1 の `_lib.call_llm`
- Produces:
  - `LLM_MODEL` / `LLM_MAX_TOKENS` / `EXTRACT_SYSTEM_PROMPT` モジュール定数
  - `extract_with_llm(title: str, body_text: str) -> dict | None`
    — 成功時 `{"summary": str, "event_date": str|None, "event_end_date": str|None,
      "date_evidence": str|None, "status": str}`。失敗時 `None`。
      `status` は `normal`/`canceled`/`postponed`/`ended` のいずれかに正規化済み
      (未知の値は `normal` に倒す)。
  - `html_to_text(html: str) -> str` — `strip_html` + `normalize_body` + 囲み曜日正規化。

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_news_extract.py`:

```python
#!/usr/bin/env python3
"""cal-tourism-news-fetch の LLM 抽出のユニットテスト。
call_llm を差し替えるので LLM を実呼び出ししない。
実行: python3 calendar/tests/test_news_extract.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def _stub(reply):
    """call_llm を固定応答に差し替え、渡された (system, user) を記録する。"""
    seen = {}

    def _f(system, user, **kw):
        seen["system"] = system
        seen["user"] = user
        seen["kw"] = kw
        return reply
    mod.call_llm = _f
    return seen


def test_extract_parses_json():
    _stub(json.dumps({
        "summary": "はんのう昭和盆踊りが開催されます。",
        "event_date": "2026-08-08",
        "event_end_date": None,
        "date_evidence": "日時:2026年8月8日(土)",
        "status": "normal",
    }, ensure_ascii=False))
    got = mod.extract_with_llm("盆踊り", "日時:2026年8月8日(土)")
    assert got["event_date"] == "2026-08-08", got
    assert got["date_evidence"] == "日時:2026年8月8日(土)", got
    assert got["status"] == "normal", got


def test_extract_strips_code_fence():
    # LLM が ```json ... ``` で包んで返すことがある
    _stub('```json\n{"summary":"x","event_date":null,"event_end_date":null,'
          '"date_evidence":null,"status":"normal"}\n```')
    got = mod.extract_with_llm("t", "b")
    assert got is not None and got["event_date"] is None, got


def test_extract_normalizes_unknown_status():
    _stub(json.dumps({"summary": "x", "event_date": None, "event_end_date": None,
                      "date_evidence": None, "status": "なんか変な値"}))
    got = mod.extract_with_llm("t", "b")
    assert got["status"] == "normal", got


def test_extract_returns_none_on_broken_json():
    _stub("これは JSON ではありません")
    assert mod.extract_with_llm("t", "b") is None


def test_extract_returns_none_when_llm_unavailable():
    mod.call_llm = lambda system, user, **kw: None
    assert mod.extract_with_llm("t", "b") is None


def test_extract_skips_short_body():
    """安全装置: 本文が薄い状態で LLM を呼ばない (ハルシネーション防止)。"""
    called = {"n": 0}

    def _f(system, user, **kw):
        called["n"] += 1
        return "{}"
    mod.call_llm = _f
    assert mod.extract_with_llm("t", "短い") is None
    assert called["n"] == 0, called


def test_extract_sends_title_and_body():
    seen = _stub(json.dumps({"summary": "x", "event_date": None,
                             "event_end_date": None, "date_evidence": None,
                             "status": "normal"}))
    mod.extract_with_llm("タイトルです", "本文です" * 20)
    assert "タイトルです" in seen["user"], seen["user"]
    assert "本文です" in seen["user"], seen["user"]
    assert seen["kw"]["model"] == mod.LLM_MODEL
    assert seen["kw"]["temperature"] == 0


def test_html_to_text_opens_circled_weekday():
    got = mod.html_to_text("<p>飯能河原6/27㈯・28㈰の営業について</p>")
    assert "(土)" in got and "(日)" in got, got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-extract tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_news_extract.py`
Expected: FAIL — `AttributeError: module has no attribute 'extract_with_llm'`

- [ ] **Step 3: 実装**

`cal-tourism-news-fetch` の import に追加:

```python
from _lib import (  # noqa: E402
    USER_AGENT, load_source_config, load_http_cache, save_http_cache,
    call_llm, llm_available, strip_html, normalize_body, strip_markdown,
    normalize_circled_weekday, normalize_fullwidth_digits, normalize_tilde,
    yaml_escape_str, yaml_block_scalar, output_path_for, find_existing_by_uid,
    AI_DISCLAIMER_JP,
)
```

定数と関数を追加:

```python
MIN_BODY_CHARS = 50          # これ未満なら LLM を呼ばない (ハルシネーション防止)
FULL_TEXT_THRESHOLD = 400    # LLM 不在時、これ以下は全文掲載

LLM_MODEL = "claude-haiku-4-5"
LLM_MAX_TOKENS = 1024

# v1: 初版。調査で確認した 6 つの失敗モードに一対一で対応させている
# (docs/superpowers/specs/2026-08-10-tourism-news-design.md の「確認された失敗モード」)。
EXTRACT_SYSTEM_PROMPT = """あなたは奥むさし飯能観光協会サイトのお知らせ記事から、市民向けカレンダーに載せる情報を取り出すアシスタントです。

これは自動パイプラインの一部で、あなたの出力はプログラムがそのまま解釈します。人間との対話ではありません。読者に質問する・追加情報を求める・処理できない理由を説明する等の対話的応答は絶対にしないでください。

出力は次の形の JSON オブジェクト 1 個だけです。前置き・説明・コードフェンスを付けないでください。

{
  "summary": "…",
  "event_date": "YYYY-MM-DD" または null,
  "event_end_date": "YYYY-MM-DD" または null,
  "date_evidence": "本文からの引用" または null,
  "status": "normal" | "canceled" | "postponed" | "ended"
}

## event_date の決め方

記事の主題となるイベントの開催日 (初日) を返します。次の区別を必ず守ってください。

- **更新スタンプは開催日ではありません**。「【6/26更新】」「6/16更新」「※4/4AM更新」のような表記は、記事やチラシ画像が更新された日付です。これを event_date にしてはいけません。
- **終了日は event_date ではありません**。「9月6日(日)まで」のように終了日しか書かれていない開催中の企画では、event_date は null、event_end_date に終了日を入れてください。開始日が本文に明記されている場合だけ event_date を埋めます。
- **副イベント・協賛イベントの日付ではなく、記事の主題の日付**を返してください。例えば「ひな飾り展」の記事に協賛イベント「丸太雛めぐり」の日程が併記されている場合、返すのはひな飾り展の日程です。
- **記事の主目的が募集・協賛のお願いであっても、本文に開催日が明記されていれば返してください**。
- 期間のあるイベントは event_date に初日、event_end_date に最終日を入れます。単日なら event_end_date は null です。
- 年が本文に書かれていない場合、記事の公開日から最も自然な年を推定してください。ただし推定に自信が持てない場合は event_date を null にしてください。**推測で埋めるより null のほうが良い結果になります。**
- 開催日が読み取れない記事 (会報誌の発行案内、アンケート依頼など) では event_date を null にしてください。

## date_evidence

event_date の根拠にした本文中の記述を、**本文からそのまま一字一句コピー**してください。要約・言い換え・整形をしてはいけません。プログラムがこの文字列を本文から検索して照合します。event_date が null なら date_evidence も null です。

## status

- `canceled`: 中止が決定したと本文が述べている
- `postponed`: 延期されたと本文が述べている
- `ended`: 既に終了した・受付を締め切ったと本文が述べている
- `normal`: 上記以外

**「雨天決行・荒天中止」「天候により中止する場合があります」のような条件付きの注意書きは `canceled` ではありません。** これらは開催予定の記事です。実際に中止・延期が決定したと書かれている場合だけ `canceled` / `postponed` にしてください。

中止・延期の場合も、**event_date には元々の開催予定日をそのまま入れてください** (null にしない)。カレンダー側で「【中止】」を付けて表示します。

## summary

- 全体で 200〜400 字程度の日本語。
- 日時・場所・対象者・料金・申込締切・申込方法など、市民の行動に関わる事実は省略しない。本文に書かれていないことは書かない (推測禁止)。
- 中止・延期・終了のステータスがある場合は、要約の冒頭に置いてください。市民が誤って参加しようとしないためです。
- 日付や金額は本文表記のまま (令和8年8月8日 等)。
- 出だしに「お知らせ:」「概要:」のような冗語は不要。本題から始める。
- 末尾に URL や「詳細は〜」を付けない。呼出側で付与する。
- **Markdown 記法 (**太字**、# 見出し、- リスト、リンク等) は一切使わないでください**。出力先は Google カレンダーの予定欄で、Markdown は literal なテキストとして表示されます。構造化したい場合は改行と全角記号で: 箇条書きは行頭「・」、見出しは「【見出し】」。
"""

_VALID_STATUS = {"normal", "canceled", "postponed", "ended"}


def html_to_text(html: str) -> str:
    """記事本文 HTML を、日付照合に使える正規化済みテキストにする。"""
    text = normalize_body(strip_html(html))
    text = normalize_circled_weekday(text)
    text = normalize_fullwidth_digits(text)
    return normalize_tilde(text)


def _strip_code_fence(s: str) -> str:
    """LLM が ```json ... ``` で包んで返した場合に中身を取り出す。"""
    t = s.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines[1:]).strip()


def extract_with_llm(title: str, body_text: str) -> dict | None:
    """本文から要約・開催日・ステータスを抽出する。失敗時 None。

    抽出は創造性が不要で、ブレると日付が揺れて content_hash が変動する。
    temperature を 0 に固定する。
    """
    if not body_text or len(body_text) < MIN_BODY_CHARS:
        # 安全装置: 薄い本文で LLM を呼ばない (ハルシネーション防止)
        return None
    raw = call_llm(EXTRACT_SYSTEM_PROMPT, f"# {title}\n\n{body_text}",
                   model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS, temperature=0)
    if raw is None:
        return None
    try:
        data = json.loads(_strip_code_fence(raw))
    except Exception as e:
        print(f"  WARN: LLM returned non-JSON: {e}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print("  WARN: LLM returned non-object JSON", file=sys.stderr)
        return None
    status = data.get("status")
    if status not in _VALID_STATUS:
        status = "normal"
    summary = data.get("summary") or ""
    return {
        "summary": strip_markdown(str(summary).strip(), bullet="・"),
        "event_date": data.get("event_date") or None,
        "event_end_date": data.get("event_end_date") or None,
        "date_evidence": data.get("date_evidence") or None,
        "status": status,
    }
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_news_extract.py`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add calendar/bin/cal-tourism-news-fetch calendar/tests/test_news_extract.py
git commit -m "feat(news): LLM 抽出とプロンプトを追加

プロンプトは調査で確認した 6 つの失敗モード (更新スタンプ・終了日・
副イベント・中止追記・延期・条件付き中止の誤判定) に一対一で対応させた。"
```

---

### Task 5: 機械検証 5 項目

LLM が返した開催日を、コード側で検算する。**このタスクが本設計の要。**

**Files:**
- Modify: `calendar/bin/cal-tourism-news-fetch`
- Test: `calendar/tests/test_news_verify.py` (新規)

**Interfaces:**
- Consumes: Task 2 の `_lib.normalize_circled_weekday`、Task 4 の `html_to_text`
- Produces: `verify_event_date(extracted: dict, body_text: str, pub_date: date) -> str | None`
  — 検証を通れば `None`、落ちれば**失格理由の文字列**を返す (ログ出力に使う)。
  `extracted["event_date"]` が `None` の場合は呼び出さない前提 (呼び出し側が先に弾く)。
- Produces: `UPDATE_STAMP_RE` モジュール定数 (`re.Pattern`)。

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_news_verify.py`:

```python
#!/usr/bin/env python3
"""cal-tourism-news-fetch の機械検証 5 項目のユニットテスト。
実データで確認した失敗モードを回帰ケースとして持つ。
実行: python3 calendar/tests/test_news_verify.py
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


def _ex(event_date, date_evidence, status="normal", end=None):
    return {"summary": "s", "event_date": event_date, "event_end_date": end,
            "date_evidence": date_evidence, "status": status}


def test_accepts_valid_case():
    """実データ: はんのう昭和盆踊り。2026-08-08 は土曜。"""
    body = "8月8日(土) はんのう昭和盆踊りへ♪ 日時:2026年8月8日(土) 午後6時〜"
    got = mod.verify_event_date(_ex("2026-08-08", "日時:2026年8月8日(土)"),
                                body, date(2026, 8, 7))
    assert got is None, got


def test_rejects_hallucinated_evidence():
    """検証 1: date_evidence が本文に無い。"""
    body = "夏祭りを開催します。"
    got = mod.verify_event_date(_ex("2026-08-08", "日時:2026年8月8日(土)"),
                                body, date(2026, 8, 7))
    assert got is not None and "evidence" in got, got


def test_rejects_evidence_not_matching_date():
    """検証 2: 根拠と結論の月日が食い違う。"""
    body = "日時:2026年8月8日(土) 午後6時〜"
    got = mod.verify_event_date(_ex("2026-09-15", "日時:2026年8月8日(土)"),
                                body, date(2026, 8, 7))
    assert got is not None and "mismatch" in got, got


def test_rejects_weekday_mismatch():
    """検証 3: 2026-08-09 は日曜なので (土) と食い違う。"""
    body = "日時:2026年8月8日(土) 午後6時〜"
    # 月日は本文と合わせつつ年をずらして曜日を崩す
    body2 = "日時:8月8日(土) 午後6時〜"
    got = mod.verify_event_date(_ex("2025-08-08", "日時:8月8日(土)"),
                                body2, date(2025, 8, 7))
    # 2025-08-08 は金曜
    assert got is not None and "weekday" in got, got


def test_rejects_date_far_from_publish():
    """検証 4: 実データの養成講座が 2025 年へ滑落した事故の回帰。

    2025-05-31 は土曜なので検証 3 (曜日) は通ってしまう。範囲チェックが
    無いと「検証済み」として過去年が確定する。これが調査時に起きた事故。
    """
    body = "スケジュール ◆ 5月31日(土) 9:00〜14:10"
    got = mod.verify_event_date(_ex("2025-05-31", "5月31日(土)"),
                                body, date(2026, 5, 1))
    assert got is not None and "out-of-range" in got, got


def test_rejects_update_stamp():
    """検証 5: 実データのキッチンカー記事。「6/16更新」は開催日ではない。"""
    body = "▽6月の出店カレンダー 6/16更新 ※クリックで大きく見られます。"
    got = mod.verify_event_date(_ex("2026-06-16", "6/16更新"),
                                body, date(2026, 6, 1))
    assert got is not None and "update-stamp" in got, got


def test_accepts_evidence_without_weekday():
    """曜日表記が無ければ検証 3 はスキップする。"""
    body = "期間:2026年3月28日から4月5日まで"
    got = mod.verify_event_date(_ex("2026-03-28", "2026年3月28日"),
                                body, date(2026, 2, 25))
    assert got is None, got


def test_accepts_circled_weekday_evidence():
    """実データ: 「6/27㈯」。正規化後に曜日一致を見る。2026-06-27 は土曜。"""
    body = mod.html_to_text("<p>飯能河原6/27㈯・28㈰の営業について</p>")
    got = mod.verify_event_date(_ex("2026-06-27", "6/27(土)"),
                                body, date(2026, 6, 26))
    assert got is None, got


def test_accepts_far_future_date_within_range():
    """実データ: 7/23 公開の「飯能まつり協賛のお願い」に 11/7 の開催日がある。
    記事の主目的が募集でも開催日は採る。2026-11-07 は土曜。"""
    body = "令和8年の飯能まつりは、11月7日(土)、8日(日)に開催を予定しています。"
    got = mod.verify_event_date(_ex("2026-11-07", "11月7日(土)"),
                                body, date(2026, 7, 23))
    assert got is None, got


def test_rejects_malformed_date():
    got = mod.verify_event_date(_ex("2026-13-45", "でたらめ"),
                                "でたらめ", date(2026, 8, 7))
    assert got is not None, got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-verify tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_news_verify.py`
Expected: FAIL — `AttributeError: module has no attribute 'verify_event_date'`

- [ ] **Step 3: 実装**

`cal-tourism-news-fetch` に `re` の import を追加し、以下を実装:

```python
import re

# 「【6/26更新】」「6/16更新」「※4/4AM更新」等。実データのキッチンカー記事では
# これしか日付が無く、正規表現による抽出が 4 件中 3 件で誤取得した。
UPDATE_STAMP_RE = re.compile(r"\d{1,2}\s*/\s*\d{1,2}\s*(?:AM|PM)?\s*更新")

_WEEKDAY_CHARS = "月火水木金土日"
_WEEKDAY_IN_EVIDENCE_RE = re.compile(r"[(（]\s*([月火水木金土日])\s*[)）]")

# 開催日が記事公開日からこの範囲を外れたら失格。過去年への滑落 (実測: 養成講座が
# 2025 年に確定した) と、遠すぎる未来の誤抽出を止める。
MIN_DAYS_BEFORE_PUBLISH = -31
MAX_DAYS_AFTER_PUBLISH = 400


def _normalize_for_match(s: str) -> str:
    """照合用の正規化。本文と evidence の両方に同じものを掛ける。"""
    s = normalize_circled_weekday(s)
    s = normalize_fullwidth_digits(s)
    s = normalize_tilde(s)
    return re.sub(r"\s+", "", s)


def verify_event_date(extracted: dict, body_text: str,
                      pub_date: date) -> str | None:
    """LLM が返した開催日を検算する。通れば None、落ちれば失格理由を返す。

    LLM は「その日付が開催日か更新スタンプか終了日か」の意味判断が得意で、
    正規表現は「その日付が本文に実在し曜日が整合するか」の機械判定が得意。
    役割を分けて二重にする。
    """
    raw_date = extracted.get("event_date")
    evidence = extracted.get("date_evidence")

    try:
        ev_date = date.fromisoformat(str(raw_date))
    except Exception:
        return f"invalid-date: {raw_date!r}"

    if not evidence:
        return "no-evidence"

    ev_norm = _normalize_for_match(evidence)
    body_norm = _normalize_for_match(body_text)

    # 検証 1: 根拠が本文に実在するか (幻覚検出)
    if ev_norm not in body_norm:
        return f"evidence-not-found: {evidence!r}"

    # 検証 5: 更新スタンプを根拠にしていないか。
    # 月日チェック (検証 2) より先に置く。「6/16更新」は月日そのものは一致して
    # しまうので、検証 2 では止められない。
    if UPDATE_STAMP_RE.search(ev_norm):
        return f"update-stamp: {evidence!r}"

    # 検証 2: 根拠と結論の月日が一致するか
    if not _evidence_contains_month_day(ev_norm, ev_date):
        return f"mismatch: {evidence!r} vs {ev_date.isoformat()}"

    # 検証 3: 根拠に曜日があれば一致するか
    m = _WEEKDAY_IN_EVIDENCE_RE.search(normalize_circled_weekday(evidence))
    if m and _WEEKDAY_CHARS[ev_date.weekday()] != m.group(1):
        return (f"weekday-mismatch: {evidence!r} vs "
                f"{ev_date.isoformat()} ({_WEEKDAY_CHARS[ev_date.weekday()]})")

    # 検証 4: 記事公開日から妥当な範囲か
    delta = (ev_date - pub_date).days
    if not (MIN_DAYS_BEFORE_PUBLISH <= delta <= MAX_DAYS_AFTER_PUBLISH):
        return f"out-of-range: {ev_date.isoformat()} is {delta}d from {pub_date}"

    return None


def _evidence_contains_month_day(ev_norm: str, ev_date: date) -> bool:
    """正規化済み evidence に ev_date の月日が現れるか。

    「8月8日」「8/8」の両表記を許す。ゼロ埋めの有無も許す。
    """
    m, d = ev_date.month, ev_date.day
    forms = [
        f"{m}月{d}日", f"{m:02d}月{d:02d}日",
        f"{m}/{d}", f"{m:02d}/{d:02d}",
        f"{ev_date.year}年{m}月{d}日",
    ]
    return any(f in ev_norm for f in forms)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_news_verify.py`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add calendar/bin/cal-tourism-news-fetch calendar/tests/test_news_verify.py
git commit -m "feat(news): 開催日の機械検証 5 項目を追加

根拠文字列の実在・根拠と結論の一致・曜日整合・公開日からの範囲・
更新スタンプ除外。実データで踏んだ失敗モードを回帰テストにしている。"
```

---

### Task 6: 本番の作成条件 (検証と直交する判定)

機械検証は「取れた日付が信用できるか」の検査。作成可否はそれとは別に決まる。

**Files:**
- Modify: `calendar/bin/cal-tourism-news-fetch`
- Test: `calendar/tests/test_news_gating.py` (新規)

**Interfaces:**
- Consumes: Task 5 の `verify_event_date`
- Produces:
  - `normalize_news_url(url: str) -> str` — パーセントデコードし、末尾スラッシュを付けて小文字ホストに揃える。
  - `find_manual_conflict(events_dir: str, news_url: str) -> str | None`
    — 同じ news 記事を指す**クローラ管理外の** YAML があれば path を返す。
  - `should_create_event(extracted: dict, body_text: str, pub_date: date, has_existing_event: bool, manual_conflict: str | None) -> tuple[bool, str]`
    — `(作るか, 理由)`。理由はログ用の短い文字列。

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_news_gating.py`:

```python
#!/usr/bin/env python3
"""cal-tourism-news-fetch の本番作成条件のユニットテスト。
実行: python3 calendar/tests/test_news_gating.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

BODY = "日時:2026年8月8日(土) 午後6時〜 会場:中央公園"
PUB = date(2026, 8, 7)


def _ex(event_date="2026-08-08", evidence="日時:2026年8月8日(土)",
        status="normal", end=None):
    return {"summary": "s", "event_date": event_date, "event_end_date": end,
            "date_evidence": evidence, "status": status}


def test_creates_for_valid_normal_event():
    ok, why = mod.should_create_event(_ex(), BODY, PUB, False, None)
    assert ok is True, why


def test_skips_when_event_date_is_null():
    """実データ: ムーミン谷みずあそび (終了日しか無い)。"""
    ok, why = mod.should_create_event(
        _ex(event_date=None, evidence=None, end="2026-09-06"),
        BODY, PUB, False, None)
    assert ok is False and "no-date" in why, why


def test_skips_canceled_article_without_existing_event():
    """中止として生まれた記事は本番を作らない (告知のみ)。"""
    ok, why = mod.should_create_event(_ex(status="canceled"), BODY, PUB,
                                      False, None)
    assert ok is False and "canceled" in why, why


def test_creates_when_canceled_but_existing_event_present():
    """既に本番を出していれば【中止】へ書き換えるため True を返す。"""
    ok, why = mod.should_create_event(_ex(status="canceled"), BODY, PUB,
                                      True, None)
    assert ok is True, why


def test_skips_on_manual_conflict():
    """実データ: 令和8年飯能夏祭り。手動 YAML を優先する。"""
    ok, why = mod.should_create_event(_ex(), BODY, PUB, False,
                                      "calendar/events/2026/07-18_x.yaml")
    assert ok is False and "manual" in why, why


def test_skips_when_verification_fails():
    ok, why = mod.should_create_event(_ex(evidence="本文に無い根拠"), BODY, PUB,
                                      False, None)
    assert ok is False and "evidence-not-found" in why, why


def test_normalize_news_url_decodes_percent_encoding():
    enc = ("https://hanno-tourism.jp/news/"
           "%E4%BB%A4%E5%92%8C%EF%BC%98%E5%B9%B4/")
    dec = "https://hanno-tourism.jp/news/令和８年/"
    assert mod.normalize_news_url(enc) == mod.normalize_news_url(dec)


def test_normalize_news_url_adds_trailing_slash():
    a = mod.normalize_news_url("https://hanno-tourism.jp/news/abc")
    b = mod.normalize_news_url("https://hanno-tourism.jp/news/abc/")
    assert a == b, (a, b)


def test_find_manual_conflict_detects_encoded_url():
    enc = ("https://hanno-tourism.jp/news/"
           "%E4%BB%A4%E5%92%8C%EF%BC%98%E5%B9%B4/")
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "2026"))
        with open(os.path.join(d, "2026", "07-18_x.yaml"), "w",
                  encoding="utf-8") as f:
            f.write('uid: "natsumatsuri-20260718@hanno.city.tecoli.com"\n'
                    f'url: "{enc}"\n')
        got = mod.find_manual_conflict(d, "https://hanno-tourism.jp/news/令和８年/")
        assert got is not None, got


def test_find_manual_conflict_ignores_crawler_owned_yaml():
    """自分が前回作った YAML を「手動」と誤認しない。"""
    url = "https://hanno-tourism.jp/news/abc/"
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "2026"))
        with open(os.path.join(d, "2026", "08-08_tourism-news-101-event.yaml"),
                  "w", encoding="utf-8") as f:
            f.write('uid: "tourism-news-101-event@hanno.city.tecoli.com"\n'
                    f'url: "{url}"\n'
                    "source:\n"
                    f"  type: {mod.SOURCE_TYPE}\n")
        assert mod.find_manual_conflict(d, url) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-gating tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_news_gating.py`
Expected: FAIL — `AttributeError: module has no attribute 'should_create_event'`

- [ ] **Step 3: 実装**

`cal-tourism-news-fetch` に `glob` と `urllib.parse` の import を追加し、以下を実装:

```python
import glob
import urllib.parse


def normalize_news_url(url: str) -> str:
    """news 記事 URL を比較可能な形に正規化する。

    手動 YAML は日本語 slug がパーセントエンコードされた形で入っている。
    エンコード表記の揺れで衝突を見逃すと重複イベントが出るのでデコードして揃える。
    """
    u = urllib.parse.unquote(url.strip())
    if not u.endswith("/"):
        u += "/"
    return u


def find_manual_conflict(events_dir: str, news_url: str) -> str | None:
    """同じ news 記事を指すクローラ管理外の YAML を探す。

    このクローラ自身が作った YAML (source.type が SOURCE_TYPE) は対象外。
    見つかれば path、無ければ None。
    """
    target = normalize_news_url(news_url)
    for path in glob.glob(os.path.join(events_dir, "**", "*.yaml"),
                          recursive=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
                head = f.read(8192)
        except Exception:
            continue
        if f"type: {SOURCE_TYPE}" in head:
            continue          # 自分が作った YAML
        if "hanno-tourism.jp/news/" not in head:
            continue
        for line in head.split("\n"):
            line = line.strip()
            if not (line.startswith("url:") or line.startswith("- url:")):
                continue
            val = line.split(":", 1)[1].strip().strip('"')
            if val and normalize_news_url(val) == target:
                return path
    return None


def should_create_event(extracted: dict, body_text: str, pub_date: date,
                        has_existing_event: bool,
                        manual_conflict: str | None) -> tuple[bool, str]:
    """本番エントリを作る (または既存を更新する) かを決める。

    機械検証は「取れた日付が信用できるか」の検査で、ここはそれと直交する条件。
    """
    if not extracted.get("event_date"):
        return False, "no-date"
    if manual_conflict:
        return False, f"manual-conflict: {manual_conflict}"
    reason = verify_event_date(extracted, body_text, pub_date)
    if reason:
        return False, reason
    if extracted["status"] in ("canceled", "postponed") and not has_existing_event:
        # 中止として生まれた記事。新規に中止済みの予定を作っても役に立たない。
        return False, f"born-{extracted['status']}"
    return True, "ok"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_news_gating.py`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add calendar/bin/cal-tourism-news-fetch calendar/tests/test_news_gating.py
git commit -m "feat(news): 本番エントリの作成条件と手動 YAML 衝突検出を追加

URL 比較はパーセントデコードして行う。手動の夏祭り YAML と
API の link でエンコード表記が揺れると重複が出るため。"
```

---

### Task 7: YAML 生成 (告知・本番の 2 系統)

**Files:**
- Modify: `calendar/bin/cal-tourism-news-fetch`
- Test: `calendar/tests/test_news_yaml.py` (新規)

**Interfaces:**
- Consumes: Task 3 の `SUMMARY_PREFIX_*` / `EVENT_TAG_IDS`、Task 4 の `extract_with_llm`
- Produces:
  - `content_hash_of(item: dict) -> str` — 記事本文とタイトルから 16 桁の sha256 短縮ハッシュ。
  - `notice_uid(prefix: str, post_id: int, content_hash: str) -> str`
    → `"<prefix>-<id>-<hash6>@hanno.city.tecoli.com"` (`hash6` = `content_hash` の先頭 6 桁)。
    **告知は世代を作る** (Task 9) ので、内容が変わると UID も変わる。
    `cal-oshirase-fetch` の incremental mode と同じ規約。
  - `event_uid(prefix: str, post_id: int) -> str` → `"<prefix>-<id>-event@hanno.city.tecoli.com"`
    **本番は世代を作らない。** 開催日は 1 つで、中止時は同じ UID のまま
    `【中止】` に書き換える (承認済みの設計判断)。
  - `jst_date_of(gmt_iso: str) -> str` — `"2026-08-07T06:18:16"` → `"2026-08-07"` (JST 換算)
  - `summary_prefix_for(tags: list[int]) -> str`
  - `build_notice_yaml(item, extracted, description, fetched_at=None) -> str`
  - `build_event_yaml(item, extracted, description, fetched_at=None) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_news_yaml.py`:

```python
#!/usr/bin/env python3
"""cal-tourism-news-fetch の YAML 生成のユニットテスト。
実行: python3 calendar/tests/test_news_yaml.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

ITEM = {
    "id": 101,
    "url": "https://hanno-tourism.jp/news/bon-odori/",
    "title": "8月8日(土) はんのう昭和盆踊りへ♪",
    "body_html": "<p>日時:2026年8月8日(土)</p>",
    "date_gmt": "2026-08-07T06:18:16",
    "modified_gmt": "2026-08-07T06:18:16",
    "tags": [6],
}
EX = {"summary": "盆踊りが開催されます。", "event_date": "2026-08-08",
      "event_end_date": None, "date_evidence": "日時:2026年8月8日(土)",
      "status": "normal"}
FIXED_TS = "2026-08-10T00:00:00Z"


def test_jst_date_of_crosses_day_boundary():
    # 06:18 UTC = 15:18 JST 同日
    assert mod.jst_date_of("2026-08-07T06:18:16") == "2026-08-07"
    # 16:00 UTC = 翌日 01:00 JST
    assert mod.jst_date_of("2026-08-07T16:00:00") == "2026-08-08"


def test_uids():
    assert mod.notice_uid("tourism-news", 101, "abcdef0123456789") == \
        "tourism-news-101-abcdef@hanno.city.tecoli.com"
    assert mod.event_uid("tourism-news", 101) == \
        "tourism-news-101-event@hanno.city.tecoli.com"


def test_content_hash_is_stable_and_changes_with_body():
    a = mod.content_hash_of(ITEM)
    assert a == mod.content_hash_of(dict(ITEM)), "同じ入力なら同じハッシュ"
    b = mod.content_hash_of(dict(ITEM, body_html="<p>違う本文</p>"))
    assert a != b, "本文が変われば変わる"
    # modified_gmt は内容ではないのでハッシュに含めない
    c = mod.content_hash_of(dict(ITEM, modified_gmt="2099-01-01T00:00:00"))
    assert a == c, "modified_gmt はハッシュに含めない"


def test_summary_prefix_for():
    assert mod.summary_prefix_for([6]) == mod.SUMMARY_PREFIX_EVENT
    assert mod.summary_prefix_for([7, 4]) == mod.SUMMARY_PREFIX_EVENT
    assert mod.summary_prefix_for([4]) == mod.SUMMARY_PREFIX_OTHER
    assert mod.summary_prefix_for([]) == mod.SUMMARY_PREFIX_OTHER


def test_notice_yaml_uses_publish_date():
    doc = mod.build_notice_yaml(ITEM, EX, "本文", fetched_at=FIXED_TS)
    assert 'dtstart: "2026-08-07"' in doc, doc
    assert 'dtend: "2026-08-07"' in doc, doc
    h6 = mod.content_hash_of(ITEM)[:6]
    assert f'uid: "tourism-news-101-{h6}@hanno.city.tecoli.com"' in doc, doc
    assert mod.SUMMARY_PREFIX_NOTICE in doc, doc
    assert f"type: {mod.SOURCE_TYPE}" in doc, doc
    assert "content_hash:" in doc, doc


def test_event_yaml_uses_extracted_date():
    doc = mod.build_event_yaml(ITEM, EX, "本文", fetched_at=FIXED_TS)
    assert 'dtstart: "2026-08-08"' in doc, doc
    assert 'dtend: "2026-08-08"' in doc, doc
    assert 'uid: "tourism-news-101-event@hanno.city.tecoli.com"' in doc, doc
    assert mod.SUMMARY_PREFIX_EVENT in doc, doc


def test_event_yaml_uses_end_date_for_range():
    ex = dict(EX, event_date="2026-03-28", event_end_date="2026-04-05")
    doc = mod.build_event_yaml(ITEM, ex, "本文", fetched_at=FIXED_TS)
    assert 'dtstart: "2026-03-28"' in doc, doc
    assert 'dtend: "2026-04-05"' in doc, doc


def test_event_yaml_marks_canceled():
    ex = dict(EX, status="canceled")
    doc = mod.build_event_yaml(ITEM, ex, "本文", fetched_at=FIXED_TS)
    assert "【中止】" in doc, doc


def test_yaml_has_no_raw_newline_in_scalar():
    """summary に改行が混ざると YAML が壊れるので空白に畳む。"""
    item = dict(ITEM, title="改行\nを含む\nタイトル")
    doc = mod.build_notice_yaml(item, EX, "本文", fetched_at=FIXED_TS)
    summary_line = [ln for ln in doc.split("\n") if ln.startswith("summary:")]
    assert len(summary_line) == 1, doc
    assert "改行 を含む タイトル" in summary_line[0], summary_line


def test_description_carries_disclaimer_and_url():
    doc = mod.build_notice_yaml(ITEM, EX, "要約テキスト", fetched_at=FIXED_TS)
    assert "要約テキスト" in doc, doc
    assert ITEM["url"] in doc, doc


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-yaml tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_news_yaml.py`
Expected: FAIL — `AttributeError: module has no attribute 'jst_date_of'`

- [ ] **Step 3: 実装**

```python
import hashlib

UID_NAMESPACE = "hanno.city.tecoli.com"
CANCELED_MARK = "【中止】"
POSTPONED_MARK = "【延期】"


def jst_date_of(gmt_iso: str) -> str:
    """API の date_gmt / modified_gmt (UTC naive ISO) を JST の日付にする。"""
    dt = datetime.fromisoformat(gmt_iso.replace("Z", "")).replace(tzinfo=timezone.utc)
    return dt.astimezone(JST).date().isoformat()


def content_hash_of(item: dict) -> str:
    """記事の内容 (タイトル + 本文) から 16 桁の短縮 sha256 を作る。

    modified_gmt は「内容」ではないので含めない。含めると、実質同じ内容で
    modified_gmt だけ動いたときに別世代が生まれて flood する。
    """
    canonical = f"{item['title']}\n{html_to_text(item['body_html'])}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def notice_uid(prefix: str, post_id: int, content_hash: str) -> str:
    """告知エントリの UID。内容が変わると変わる (= 世代を作る)。

    cal-oshirase-fetch の incremental mode と同じ規約。
    """
    return f"{prefix}-{post_id}-{content_hash[:6]}@{UID_NAMESPACE}"


def event_uid(prefix: str, post_id: int) -> str:
    """本番エントリの UID。世代を作らず、中止時は同じ UID のまま書き換える。"""
    return f"{prefix}-{post_id}-event@{UID_NAMESPACE}"


def summary_prefix_for(tags: list[int]) -> str:
    """本番エントリの prefix をタグから決める (LLM の判断を挟まない)。"""
    return SUMMARY_PREFIX_EVENT if set(tags) & EVENT_TAG_IDS else SUMMARY_PREFIX_OTHER


def _one_line(s: str) -> str:
    """YAML の scalar に入れるため改行を空白に畳む。"""
    return " ".join(s.split())


def _status_mark(status: str) -> str:
    if status == "canceled":
        return CANCELED_MARK
    if status == "postponed":
        return POSTPONED_MARK
    return ""


def _build_yaml(uid: str, summary: str, item: dict, dtstart: str, dtend: str,
                description: str, fetched_at: str | None,
                supersedes: str | None = None) -> str:
    lines: list[str] = []
    lines.append(f"uid: {yaml_escape_str(uid)}")
    lines.append(f"summary: {yaml_escape_str(_one_line(summary))}")
    lines.append(f"url: {yaml_escape_str(item['url'])}")
    lines.append(f"dtstart: {yaml_escape_str(dtstart)}")
    lines.append(f"dtend: {yaml_escape_str(dtend)}")
    desc = f"奥むさし飯能観光協会: {item['url']}"
    if description:
        desc = f"{desc}\n\n{description}"
    lines.append("description: " + yaml_block_scalar(desc, indent=2))
    lines.append("")
    lines.append("render:")
    lines.append("  gcal:")
    lines.append("    mode: single-allday")
    lines.append("")
    lines.append("source:")
    lines.append(f"  type: {SOURCE_TYPE}")
    lines.append(f"  id: {yaml_escape_str(str(item['id']))}")
    lines.append(f"  url: {yaml_escape_str(item['url'])}")
    ts = fetched_at or (datetime.utcnow().isoformat() + "Z")
    lines.append(f"  fetched_at: {yaml_escape_str(ts)}")
    lines.append(f"  modified_gmt: {yaml_escape_str(item.get('modified_gmt', ''))}")
    lines.append(f"  content_hash: {yaml_escape_str('sha256-' + content_hash_of(item))}")
    if supersedes:
        lines.append(f"  supersedes: {yaml_escape_str(supersedes)}")
    return "\n".join(lines) + "\n"


def build_notice_yaml(item: dict, extracted: dict, description: str,
                      fetched_at: str | None = None,
                      supersedes: str | None = None) -> str:
    """告知エントリ: 記事が公開された事実。dtstart は公開日 (JST)。

    supersedes が渡された場合は世代リンクを記録する (Task 9)。
    """
    d = jst_date_of(item["date_gmt"])
    summary = SUMMARY_PREFIX_NOTICE + _status_mark(extracted["status"]) + item["title"]
    return _build_yaml(notice_uid(DEFAULT_UID_PREFIX, item["id"],
                                  content_hash_of(item)),
                       summary, item, d, d, description, fetched_at,
                       supersedes=supersedes)


def build_event_yaml(item: dict, extracted: dict, description: str,
                     fetched_at: str | None = None) -> str:
    """本番エントリ: 開催日。verify を通った event_date のみ到達する。"""
    start = extracted["event_date"]
    end = extracted.get("event_end_date") or start
    summary = (summary_prefix_for(item["tags"])
               + _status_mark(extracted["status"]) + item["title"])
    return _build_yaml(event_uid(DEFAULT_UID_PREFIX, item["id"]), summary,
                       item, start, end, description, fetched_at)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_news_yaml.py`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add calendar/bin/cal-tourism-news-fetch calendar/tests/test_news_yaml.py
git commit -m "feat(news): 告知・本番 2 系統の YAML 生成を追加"
```

---

### Task 8: `main()`、description 組み立て、サニティチェック

ここまでの部品を繋いで動くクローラにする。

**Files:**
- Modify: `calendar/bin/cal-tourism-news-fetch`
- Test: `calendar/tests/test_news_main.py` (新規)

**Interfaces:**
- Consumes: Task 3〜7 の全て
- Produces:
  - `build_description(extracted: dict, body_text: str) -> str`
    — LLM 要約があれば `AI_DISCLAIMER_JP` を冒頭に付けて返す。無ければ本文をそのまま
      (`FULL_TEXT_THRESHOLD` 超は切り詰め)。
  - `check_news_count(n: int, min_news: int) -> None` — 下回れば `sys.exit(2)`
  - `process_news(items, out_dir, dry_run, cache) -> dict`
    — `{"notice": int, "event": int, "skipped_event": int, "llm_fail": int}`
  - `main() -> None`

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_news_main.py`:

```python
#!/usr/bin/env python3
"""cal-tourism-news-fetch の main / process_news のユニットテスト。
実行: python3 calendar/tests/test_news_main.py
"""
from __future__ import annotations
import glob
import importlib.machinery
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

BON = {
    "id": 101,
    "url": "https://hanno-tourism.jp/news/bon-odori/",
    "title": "8月8日(土) はんのう昭和盆踊りへ♪",
    "body_html": "<p>日時:2026年8月8日(土) 午後6時から午後9時まで。会場は中央公園です。"
                 "どなたでもご参加いただけます。雨天の場合は中止となります。</p>",
    "date_gmt": "2026-08-07T06:18:16",
    "modified_gmt": "2026-08-07T06:18:16",
    "tags": [6],
}


def _stub_llm(payload):
    mod.call_llm = lambda system, user, **kw: json.dumps(payload,
                                                         ensure_ascii=False)


def _files(d):
    return sorted(os.path.basename(p)
                  for p in glob.glob(os.path.join(d, "**", "*.yaml"),
                                     recursive=True))


def _notice_name(item):
    h6 = mod.content_hash_of(item)[:6]
    return f"08-07_tourism-news-101-{h6}.yaml"


def test_process_news_writes_both_entries():
    _stub_llm({"summary": "盆踊りが開催されます。", "event_date": "2026-08-08",
               "event_end_date": None, "date_evidence": "日時:2026年8月8日(土)",
               "status": "normal"})
    with tempfile.TemporaryDirectory() as d:
        r = mod.process_news([BON], d, False, {})
        assert r["notice"] == 1 and r["event"] == 1, r
        names = _files(d)
        assert _notice_name(BON) in names, names
        assert "08-08_tourism-news-101-event.yaml" in names, names


def test_process_news_writes_notice_only_when_no_date():
    _stub_llm({"summary": "会報誌を発行しました。", "event_date": None,
               "event_end_date": None, "date_evidence": None,
               "status": "normal"})
    with tempfile.TemporaryDirectory() as d:
        r = mod.process_news([BON], d, False, {})
        assert r["notice"] == 1 and r["event"] == 0, r
        assert _files(d) == [_notice_name(BON)], _files(d)


def test_process_news_records_cache_on_success():
    _stub_llm({"summary": "s", "event_date": None, "event_end_date": None,
               "date_evidence": None, "status": "normal"})
    cache = {}
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([BON], d, False, cache)
    assert cache[BON["url"]]["modified_gmt"] == "2026-08-07T06:18:16", cache


def test_process_news_does_not_record_cache_on_llm_failure():
    """失敗した記事は次回リトライされる必要がある。"""
    mod.call_llm = lambda system, user, **kw: None
    cache = {}
    with tempfile.TemporaryDirectory() as d:
        r = mod.process_news([BON], d, False, cache)
    assert r["llm_fail"] == 1, r
    assert BON["url"] not in cache, cache


def test_process_news_keeps_existing_cache_fields():
    _stub_llm({"summary": "s", "event_date": None, "event_end_date": None,
               "date_evidence": None, "status": "normal"})
    cache = {BON["url"]: {"etag": 'W/"abc"'}}
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([BON], d, False, cache)
    assert cache[BON["url"]]["etag"] == 'W/"abc"', cache


def test_dry_run_writes_nothing():
    _stub_llm({"summary": "s", "event_date": "2026-08-08",
               "event_end_date": None, "date_evidence": "日時:2026年8月8日(土)",
               "status": "normal"})
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([BON], d, True, {})
        assert _files(d) == [], _files(d)


def test_check_news_count_exits_when_too_few():
    try:
        mod.check_news_count(50, 100)
    except SystemExit as e:
        assert e.code == 2, e
    else:
        raise AssertionError("should have exited")


def test_check_news_count_passes():
    mod.check_news_count(137, 100)   # 例外が出なければよい


def test_build_description_adds_disclaimer_for_llm_summary():
    got = mod.build_description({"summary": "要約です。", "status": "normal"},
                                "本文" * 300)
    assert mod.AI_DISCLAIMER_JP in got, got
    assert "要約です。" in got, got


def test_build_description_falls_back_to_body():
    got = mod.build_description({"summary": "", "status": "normal"}, "短い本文")
    assert "短い本文" in got, got
    assert mod.AI_DISCLAIMER_JP not in got, got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-main tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_news_main.py`
Expected: FAIL — `AttributeError: module has no attribute 'process_news'`

- [ ] **Step 3: 実装**

```python
def build_description(extracted: dict, body_text: str) -> str:
    """description 本体を組み立てる。

    LLM 要約があればそれを使い AI 由来であることを明示する。無い場合 (API キー
    不在・LLM 失敗) は本文を使う。この分岐で content_hash が変わるので、CI では
    必ず ANTHROPIC_API_KEY を渡すこと (2026-05-26 の oshirase 障害と同じ罠)。
    """
    summary = (extracted or {}).get("summary") or ""
    if summary:
        return f"{AI_DISCLAIMER_JP}\n\n{summary}"
    text = body_text.strip()
    if len(text) > FULL_TEXT_THRESHOLD:
        text = text[:FULL_TEXT_THRESHOLD].rstrip() + "…"
    return text


def check_news_count(n: int, min_news: int) -> None:
    """API が返す件数の下限チェック。API 仕様変更・大量非公開を検知する。

    news は蓄積型で 2017 年の記事も残っている (実測 137 件) ので下限を高く置ける。
    """
    if n < min_news:
        print(f"FAIL: news from API ({n}) < --min-news ({min_news}). "
              "API 仕様変更か大量非公開の可能性がある。",
              file=sys.stderr)
        sys.exit(2)


def process_news(items: list[dict], out_dir: str, dry_run: bool,
                 cache: dict) -> dict:
    """記事ごとに告知 (常に) と本番 (条件付き) を書き出す。"""
    stats = {"notice": 0, "event": 0, "skipped_event": 0, "llm_fail": 0}
    for i, item in enumerate(items, 1):
        print(f"[{i}/{len(items)}] {item['url']}", file=sys.stderr)
        body_text = html_to_text(item["body_html"])
        extracted = extract_with_llm(item["title"], body_text)
        if extracted is None:
            stats["llm_fail"] += 1
            # 要約なしでも告知は出す。ただし cache には記録せず次回リトライさせる。
            extracted = {"summary": "", "event_date": None,
                         "event_end_date": None, "date_evidence": None,
                         "status": "normal"}
            recordable = False
        else:
            recordable = True

        description = build_description(extracted, body_text)
        pub_date = date.fromisoformat(jst_date_of(item["date_gmt"]))

        n_uid = notice_uid(DEFAULT_UID_PREFIX, item["id"], content_hash_of(item))
        notice_path = output_path_for(out_dir, n_uid,
                                      jst_date_of(item["date_gmt"]))
        if not dry_run:
            _write(notice_path, build_notice_yaml(item, extracted, description))
        stats["notice"] += 1

        ev_uid = event_uid(DEFAULT_UID_PREFIX, item["id"])
        existing_event = find_existing_by_uid(out_dir, ev_uid)
        conflict = find_manual_conflict(out_dir, item["url"])
        ok, why = should_create_event(extracted, body_text, pub_date,
                                      existing_event is not None, conflict)
        if ok:
            ev_path = output_path_for(out_dir, ev_uid, extracted["event_date"])
            if not dry_run:
                if existing_event and existing_event != ev_path:
                    # 開催日が変わった場合は旧ファイルを消してから書く
                    os.remove(existing_event)
                _write(ev_path, build_event_yaml(item, extracted, description))
            stats["event"] += 1
        else:
            stats["skipped_event"] += 1
            print(f"  no event entry: {why}", file=sys.stderr)

        if recordable:
            entry = cache.setdefault(item["url"], {})
            entry["modified_gmt"] = item.get("modified_gmt", "")
    return stats


def _write(path: str, doc: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="hanno-tourism.jp news イベント YAML 生成")
    ap.add_argument("--out-dir", default="calendar/events")
    ap.add_argument("--min-news", type=int, default=100,
                    help="API が返す件数がこれ未満なら exit 2")
    ap.add_argument("--backfill-months", type=int,
                    default=DEFAULT_BACKFILL_MONTHS,
                    help="この月数より古い記事は処理しない (毎回適用)")
    ap.add_argument("--no-cache", action="store_true",
                    help="modified_gmt によるスキップを行わない")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        items = fetch_news_index(args.backfill_months, datetime.now(JST).date())
    except Exception as e:
        print(f"FAIL: news API unavailable: {e}", file=sys.stderr)
        sys.exit(2)

    # 下限チェックは backfill フィルタ前の総数で見たいので、API の総数を別に数える。
    check_news_count(_total_count(), args.min_news)

    cache = {} if args.no_cache else load_http_cache()
    if args.no_cache:
        todo, unchanged = items, 0
    else:
        todo, unchanged = select_news_to_fetch(items, cache)

    print(f"Processing {len(todo)} of {len(items)} news "
          f"(unchanged={unchanged})", file=sys.stderr)

    r = process_news(todo, args.out_dir, args.dry_run, cache)

    if todo and r["llm_fail"] == len(todo):
        print("FAIL: LLM extraction failed for every article.", file=sys.stderr)
        sys.exit(2)

    if not args.dry_run and not args.no_cache:
        save_http_cache(cache)

    print(f"notice={r['notice']} event={r['event']} "
          f"skipped_event={r['skipped_event']} llm_fail={r['llm_fail']} "
          f"unchanged={unchanged}", file=sys.stderr)


def _total_count() -> int:
    """API の総件数を数える。fetch_news_index は backfill で削るので別途数える。

    X-WP-Total ヘッダを読めれば 1 リクエストで済むが、fetch_json が本文しか
    返さないので `_fields=id` で全ページを辿る。転送量は小さい。
    """
    total = 0
    page = 1
    while True:
        batch = fetch_json(f"{API_URL}?per_page={PER_PAGE}&page={page}&_fields=id")
        if not isinstance(batch, list) or not batch:
            break
        total += len(batch)
        if len(batch) < PER_PAGE:
            break
        page += 1
    return total


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_news_main.py`
Expected: PASS

- [ ] **Step 5: 実サイトに対して dry-run で動作確認**

```bash
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  ./calendar/bin/cal-tourism-news-fetch --dry-run --no-cache --backfill-months 1
```
Expected: `notice=N event=M …` が出て異常終了しない。
`no event entry: …` の理由が妥当か目視する。

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/cal-tourism-news-fetch calendar/tests/test_news_main.py
git commit -m "feat(news): main と process_news、サニティチェックを追加

LLM 失敗記事は cache に記録せず次回リトライさせる。抽出失敗率は
判定に使わない (日付が無いのが正常な記事を含むため誤発火する)。"
```

---

### Task 9: 告知エントリの世代リンク

記事が更新されたとき、告知は**前世代を残して新しい世代を作る** (`cal-oshirase-fetch`
と同じ規約)。中止の追記はここに自然に出る。Task 7 で UID に content hash を入れたので、
内容が変われば別ファイルになる。あとは前世代を引いて `supersedes` と状態ヘッダを付ける。

**本番は世代を作らない。** 開催日は 1 つで、中止時は同じ UID のまま書き換える。

**Files:**
- Modify: `calendar/bin/cal-tourism-news-fetch`
- Test: `calendar/tests/test_news_generations.py` (新規)

**Interfaces:**
- Consumes: Task 7 の `content_hash_of` / `notice_uid` / `build_notice_yaml`
- Produces:
  - `existing_notice_generations(events_dir: str, prefix: str) -> dict[str, list[tuple[str, str, str, str]]]`
    — `post_id` (str) → `(dtstart, uid, path, content_hash)` の list。dtstart 降順・
      同 dtstart は path 降順の安定ソート済み (先頭 = 直前世代)。
  - `notice_status_header(publish_date: str, prev_dtstart: str | None) -> str`
    — 新着なら `"🆕 新着掲載 (公開日: …)"`、更新なら `"🔄 内容更新 (公開日: … / 前回掲載: …)"`。

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_news_generations.py`:

```python
#!/usr/bin/env python3
"""告知エントリの世代リンクのユニットテスト。
実行: python3 calendar/tests/test_news_generations.py
"""
from __future__ import annotations
import glob
import importlib.machinery
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

ITEM = {
    "id": 303,
    "url": "https://hanno-tourism.jp/news/sakura-week/",
    "title": "飯能さくらウィーク開催",
    "body_html": "<p>期間:令和8年3月28日(土)〜4月5日(日)の9日間。中央公園で開催します。"
                 "キッチンカー等が出店し飲食の提供もあります。雨天決行・荒天中止。</p>",
    "date_gmt": "2026-02-25T00:00:00",
    "modified_gmt": "2026-02-25T00:00:00",
    "tags": [6],
}
EX = {"summary": "さくらウィークが開催されます。", "event_date": "2026-03-28",
      "event_end_date": "2026-04-05", "date_evidence": "令和8年3月28日(土)",
      "status": "normal"}


def _stub_llm(payload):
    mod.call_llm = lambda system, user, **kw: json.dumps(payload,
                                                         ensure_ascii=False)


def _names(d):
    return sorted(os.path.basename(p)
                  for p in glob.glob(os.path.join(d, "**", "*.yaml"),
                                     recursive=True))


def test_status_header_new():
    got = mod.notice_status_header("2026-02-25", None)
    assert got.startswith("🆕"), got
    assert "2026-02-25" in got, got


def test_status_header_update_mentions_previous():
    got = mod.notice_status_header("2026-02-25", "2026-02-20")
    assert got.startswith("🔄"), got
    assert "2026-02-20" in got, got


def test_existing_generations_sorts_newest_first():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "2026"))
        for dtstart, h in (("2026-02-25", "aaaaaa"), ("2026-02-20", "bbbbbb")):
            p = os.path.join(d, "2026", f"{dtstart[5:]}_tourism-news-303-{h}.yaml")
            with open(p, "w", encoding="utf-8") as f:
                f.write(f'uid: "tourism-news-303-{h}@hanno.city.tecoli.com"\n'
                        f'dtstart: "{dtstart}"\n'
                        f'  content_hash: "sha256-{h}0000000000"\n')
        idx = mod.existing_notice_generations(d, "tourism-news")
        gens = idx["303"]
        assert gens[0][0] == "2026-02-25", gens
        assert len(gens) == 2, gens


def test_existing_generations_ignores_event_entries():
    """本番エントリ (-event) を世代として数えない。"""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "2026"))
        p = os.path.join(d, "2026", "03-28_tourism-news-303-event.yaml")
        with open(p, "w", encoding="utf-8") as f:
            f.write('uid: "tourism-news-303-event@hanno.city.tecoli.com"\n'
                    'dtstart: "2026-03-28"\n'
                    '  content_hash: "sha256-cccccc0000000000"\n')
        idx = mod.existing_notice_generations(d, "tourism-news")
        assert idx.get("303") in (None, []), idx


def test_second_run_with_same_content_creates_no_new_generation():
    _stub_llm(EX)
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([ITEM], d, False, {})
        first = _names(d)
        mod.process_news([ITEM], d, False, {})
        assert _names(d) == first, (first, _names(d))


def test_updated_content_creates_new_generation_and_keeps_old():
    _stub_llm(EX)
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([ITEM], d, False, {})
        before = _names(d)
        updated = dict(ITEM,
                       body_html="<p>【3/1更新】内容が変わりました。"
                                 "期間:令和8年3月28日(土)〜4月5日(日)の9日間。</p>",
                       modified_gmt="2026-03-01T00:00:00")
        mod.process_news([updated], d, False, {})
        after = _names(d)
        assert len(after) > len(before), (before, after)
        # 前世代が残っている
        for name in before:
            assert name in after, (name, after)


def test_new_generation_records_supersedes():
    _stub_llm(EX)
    with tempfile.TemporaryDirectory() as d:
        mod.process_news([ITEM], d, False, {})
        old_uid = mod.notice_uid("tourism-news", 303, mod.content_hash_of(ITEM))
        updated = dict(ITEM,
                       body_html="<p>【3/1更新】内容が変わりました。"
                                 "期間:令和8年3月28日(土)〜4月5日(日)の9日間。</p>")
        mod.process_news([updated], d, False, {})
        new_uid = mod.notice_uid("tourism-news", 303, mod.content_hash_of(updated))
        new_path = [p for p in glob.glob(os.path.join(d, "**", "*.yaml"),
                                         recursive=True)
                    if new_uid.split("@")[0] in os.path.basename(p)]
        assert new_path, _names(d)
        with open(new_path[0], encoding="utf-8") as f:
            doc = f.read()
        assert "supersedes:" in doc, doc
        assert old_uid in doc, doc
        assert "🔄" in doc, doc


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-generation tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_news_generations.py`
Expected: FAIL — `AttributeError: module has no attribute 'notice_status_header'`

- [ ] **Step 3: 実装**

`cal-tourism-news-fetch` に追加:

```python
# 世代の状態ヘッダ。cal-oshirase-fetch と同じ絵文字規約 (_lib.STATUS_MARKERS)。
def notice_status_header(publish_date: str, prev_dtstart: str | None) -> str:
    """告知 description の冒頭に置く 1 行。"""
    if prev_dtstart:
        return f"🔄 内容更新 (公開日: {publish_date} / 前回掲載: {prev_dtstart})"
    return f"🆕 新着掲載 (公開日: {publish_date})"


_NOTICE_UID_RE_TMPL = r"^{prefix}-(\d+)-(?!event@)([A-Za-z0-9]+)@"


def existing_notice_generations(events_dir: str,
                                prefix: str) -> dict[str, list[tuple[str, str, str, str]]]:
    """既存の告知 YAML を post_id 別に集めた世代索引を返す。

    値は (dtstart, uid, path, content_hash) の list で dtstart 降順・同 dtstart は
    path 降順に安定ソート済み (先頭 = 直前世代)。本番エントリ (`-event@`) は除く。
    """
    pat = re.compile(_NOTICE_UID_RE_TMPL.format(prefix=re.escape(prefix)))
    idx: dict[str, list[tuple[str, str, str, str]]] = {}
    for path in glob.glob(os.path.join(events_dir, "**", "*.yaml"),
                          recursive=True):
        uid = read_yaml_scalar(path, "uid")
        if not uid:
            continue
        m = pat.match(uid)
        if not m:
            continue
        ch = read_yaml_scalar(path, "content_hash") or ""
        if ch.startswith("sha256-"):
            ch = ch[len("sha256-"):]
        dtstart = read_yaml_scalar(path, "dtstart") or ""
        idx.setdefault(m.group(1), []).append((dtstart, uid, path, ch))
    for gens in idx.values():
        gens.sort(key=lambda g: (g[0], g[2]), reverse=True)
    return idx
```

`read_yaml_scalar` を `_lib` の import に追加する。

`process_news` の告知パートを差し替える:

```python
        n_hash = content_hash_of(item)
        n_uid = notice_uid(DEFAULT_UID_PREFIX, item["id"], n_hash)
        pub_str = jst_date_of(item["date_gmt"])
        gens = generations.get(str(item["id"]), [])

        if any(g[3] == n_hash for g in gens):
            # 同じ内容の世代が既にある。新しい世代を作らない (flood 防止)。
            stats["notice_unchanged"] += 1
        else:
            prev = gens[0] if gens else None
            header = notice_status_header(pub_str, prev[0] if prev else None)
            notice_desc = f"{header}\n\n{description}"
            notice_path = output_path_for(out_dir, n_uid, pub_str)
            if not dry_run:
                _write(notice_path, build_notice_yaml(
                    item, extracted, notice_desc,
                    supersedes=prev[1] if prev else None))
            stats["notice"] += 1
```

`process_news` の冒頭で索引を 1 回だけ作る (記事ごとに走査すると O(n²) になる):

```python
    generations = existing_notice_generations(out_dir, DEFAULT_UID_PREFIX)
```

`stats` の初期値に `"notice_unchanged": 0` を足す。
新しい世代を書いたら `generations` にも追記して、同一実行内の重複を防ぐ:

```python
            gens.insert(0, (pub_str, n_uid, notice_path, n_hash))
            generations[str(item["id"])] = gens
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_news_generations.py`
Expected: PASS

- [ ] **Step 5: 既存テストの回帰確認**

Task 8 の `test_news_main.py` は告知ファイル名を `content_hash_of` から導いているので
そのまま通るはずだが、`description` に状態ヘッダが付いたことで
`test_build_description_*` 以外に影響が出ていないか確認する。

Run: `python3 calendar/tests/test_news_main.py && python3 calendar/tests/test_news_yaml.py`
Expected: PASS

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/cal-tourism-news-fetch calendar/tests/test_news_generations.py
git commit -m "feat(news): 告知エントリの世代リンクを追加

cal-oshirase-fetch と同じ規約。内容が変われば新世代を作り前世代を残す。
本番エントリは世代を作らず同じ UID のまま書き換える。"
```

---

### Task 10: 更新時の【中止】書き換えと golden テスト

**Files:**
- Modify: `calendar/bin/cal-tourism-news-fetch`
- Modify: `calendar/tests/run-golden`
- Create: `calendar/tests/fixtures/cal-tourism-news-fetch/` (API レスポンスと LLM 応答)
- Create: `calendar/tests/seed/cal-tourism-news-cancel/` (既存本番 YAML)
- Create: `calendar/tests/capture-news-fixtures` (実サイトから fixtures を取る dev tool)

**Interfaces:**
- Consumes: Task 8 の `process_news`
- Produces: golden 名 `cal-tourism-news-fetch` と `cal-tourism-news-cancel`

- [ ] **Step 1: 中止書き換えの失敗テストを書く**

`calendar/tests/test_news_cancel.py`:

```python
#!/usr/bin/env python3
"""中止・延期の追記が既存の本番エントリに反映されるかのテスト。
実行: python3 calendar/tests/test_news_cancel.py
"""
from __future__ import annotations
import glob
import importlib.machinery
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

# 実データ: 名栗ほたる祭り。6/11 告知 → 6/26 に冒頭へ中止が追記された。
HOTARU = {
    "id": 202,
    "url": "https://hanno-tourism.jp/news/naguri-hotaru/",
    "title": "名栗ほたる祭り",
    "body_html": "<p>【6/26更新】台風接近に伴い中止が決定しました。 ノーラ名栗にて"
                 "今年も「名栗ほたる祭り」を開催! 日時:2026年6月27日(土) "
                 "午後5時〜午後8時30分(雨天決行) 会場:ノーラ名栗</p>",
    "date_gmt": "2026-06-11T00:00:00",
    "modified_gmt": "2026-06-26T09:00:00",
    "tags": [6],
}


def _stub_llm(payload):
    mod.call_llm = lambda system, user, **kw: json.dumps(payload,
                                                         ensure_ascii=False)


def test_existing_event_gets_canceled_mark():
    _stub_llm({"summary": "台風接近に伴い中止が決定しました。",
               "event_date": "2026-06-27", "event_end_date": None,
               "date_evidence": "日時:2026年6月27日(土)", "status": "canceled"})
    with tempfile.TemporaryDirectory() as d:
        # 前回の実行で本番が既にある状態を作る
        os.makedirs(os.path.join(d, "2026"))
        prev = os.path.join(d, "2026", "06-27_tourism-news-202-event.yaml")
        with open(prev, "w", encoding="utf-8") as f:
            f.write('uid: "tourism-news-202-event@hanno.city.tecoli.com"\n'
                    'summary: "🎪 名栗ほたる祭り"\n'
                    f'url: "{HOTARU["url"]}"\n'
                    'dtstart: "2026-06-27"\n'
                    'dtend: "2026-06-27"\n'
                    "source:\n"
                    f"  type: {mod.SOURCE_TYPE}\n")
        r = mod.process_news([HOTARU], d, False, {})
        assert r["event"] == 1, r
        with open(prev, encoding="utf-8") as f:
            doc = f.read()
        assert "【中止】" in doc, doc
        assert 'dtstart: "2026-06-27"' in doc, doc


def test_born_canceled_creates_notice_only():
    """中止として生まれた記事 (既存本番なし) は本番を作らない。"""
    _stub_llm({"summary": "中止のお知らせ", "event_date": "2026-06-27",
               "event_end_date": None,
               "date_evidence": "日時:2026年6月27日(土)", "status": "canceled"})
    with tempfile.TemporaryDirectory() as d:
        r = mod.process_news([HOTARU], d, False, {})
        assert r["event"] == 0, r
        names = sorted(os.path.basename(p) for p in
                       glob.glob(os.path.join(d, "**", "*.yaml"), recursive=True))
        h6 = mod.content_hash_of(HOTARU)[:6]
        assert names == [f"06-11_tourism-news-202-{h6}.yaml"], names


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-cancel tests passed")
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python3 calendar/tests/test_news_cancel.py`
Expected: FAIL — 既存ファイルに【中止】が入らない

- [ ] **Step 3: 既存本番の上書きが【中止】を反映することを確かめ、必要なら直す**

設計上はここまでの部品で通るはず (`should_create_event` が `canceled` かつ
`has_existing_event=True` で `True` を返し、`build_event_yaml` が `_status_mark` で
`【中止】` を付ける)。**このステップの目的は、その繋がりが実際に成立しているかを
テストで確かめること。** 落ちた場合の切り分け順:

1. `mod.should_create_event(...)` を直接呼んで `(True, "ok")` が返るか
   — 返らなければ Task 6 の分岐順序 (verify より先に `born-canceled` に落ちていないか) を見る
2. `mod.build_event_yaml(HOTARU, ex, "本文")` の戻り値に `【中止】` が含まれるか
   — 含まれなければ Task 7 の `_status_mark` の呼び出し漏れ
3. `process_news` が既存ファイルを上書きしているか
   — `existing_event != ev_path` の分岐で `os.remove` した後に書き忘れていないか

- [ ] **Step 4: テストが通ることを確認**

Run: `python3 calendar/tests/test_news_cancel.py`
Expected: PASS

- [ ] **Step 5: fixtures 取得スクリプトを書いて実行**

`calendar/tests/capture-news-fixtures` (新規、実行可能):

```python
#!/usr/bin/env python3
"""calendar/tests/capture-news-fixtures — news の golden 用 fixtures を実サイトから取得。

ネットワークと LLM を使う dev tool。fixtures を更新したい時に手動実行する。
  ANTHROPIC_API_KEY=... python3 calendar/tests/capture-news-fixtures

出力:
  fixtures/cal-tourism-news-fetch/api-page1.json   API レスポンス (対象記事のみ)
  fixtures/cal-tourism-news-fetch/llm.json         記事 id → LLM 応答 (JSON 文字列)
"""
from __future__ import annotations
import importlib.machinery, importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
FIX = os.path.join(HERE, "fixtures", "cal-tourism-news-fetch")

loader = importlib.machinery.SourceFileLoader("m",
                                              os.path.join(BIN, "cal-tourism-news-fetch"))
spec = importlib.util.spec_from_loader("m", loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

# golden に含める記事数。直近から順に採る。
#
# golden の役目は「パイプライン全体がバイト単位で安定しているか」であって、
# 失敗モードの網羅ではない。失敗モードは test_news_verify.py 等が実データを
# インラインに持って個別に検証している。だから採取対象は「直近 N 件」で足りるし、
# 特定 slug への依存を持たないぶん記事が消えても壊れない。
CAPTURE_COUNT = 6


def main():
    if not m.llm_available():
        sys.exit("ANTHROPIC_API_KEY が必要です")
    os.makedirs(FIX, exist_ok=True)
    raw = []
    page = 1
    while True:
        batch = m.fetch_json(f"{m.API_URL}?per_page={m.PER_PAGE}&page={page}"
                             f"&_fields={m.API_FIELDS}")
        if not batch:
            break
        raw.extend(batch)
        if len(batch) < m.PER_PAGE:
            break
        page += 1

    if not raw:
        sys.exit("API が記事を返しませんでした")
    picked = sorted(raw, key=lambda it: it.get("date_gmt", ""),
                    reverse=True)[:CAPTURE_COUNT]

    with open(os.path.join(FIX, "api-page1.json"), "w", encoding="utf-8") as f:
        json.dump(picked, f, ensure_ascii=False, indent=2)

    replies = {}
    for it in picked:
        body = m.html_to_text((it.get("content") or {}).get("rendered", ""))
        title = (it.get("title") or {}).get("rendered", "")
        text = m.call_llm(m.EXTRACT_SYSTEM_PROMPT, f"# {title}\n\n{body}",
                          model=m.LLM_MODEL, max_tokens=m.LLM_MAX_TOKENS,
                          temperature=0)
        replies[str(it["id"])] = text
        print(f"captured {it['id']}: {text[:80] if text else None}")
    with open(os.path.join(FIX, "llm.json"), "w", encoding="utf-8") as f:
        json.dump(replies, f, ensure_ascii=False, indent=2)
    print(f"OK: {len(picked)} articles -> {FIX}")


if __name__ == "__main__":
    main()
```

```bash
chmod +x calendar/tests/capture-news-fixtures
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" python3 calendar/tests/capture-news-fixtures
```

Expected: `captured <id>: {"summary":…` が 6 行出て `OK: 6 articles -> …` で終わる。
`llm.json` の各値が JSON 文字列になっているか (null になっていないか) を確認する。

- [ ] **Step 6: `run-golden` に登録**

`calendar/tests/run-golden` に setup 関数を追加:

```python
def _setup_tourism_news(m, crawler, manifest):
    """API レスポンスと LLM 応答を fixtures から再生する。

    LLM は非決定的なので実呼び出しはしない (記録済み応答の再生)。
    """
    import json as _json
    with open(os.path.join(FIX, crawler, "api-page1.json"), encoding="utf-8") as f:
        posts = _json.load(f)
    with open(os.path.join(FIX, crawler, "llm.json"), encoding="utf-8") as f:
        replies = _json.load(f)

    def _fetch_json(url):
        if "page=1" in url or "page=" not in url:
            return posts
        return []
    m.fetch_json = _fetch_json

    # user プロンプトの先頭行 (= "# タイトル") から記事を引き当てて応答を返す
    by_title = {(p.get("title") or {}).get("rendered", ""): str(p["id"])
                for p in posts}

    def _call_llm(system, user, **kw):
        head = user.split("\n", 1)[0].removeprefix("# ").strip()
        return replies.get(by_title.get(head, ""), None)
    m.call_llm = _call_llm

    m.load_http_cache = lambda: {}
    m.save_http_cache = lambda c: None
    # backfill フィルタが「今日」に依存すると golden が日々壊れるので固定する
    m.DEFAULT_BACKFILL_MONTHS = 12000
    # fixtures は数件しか無いので --min-news の下限チェックを無効化する
    # (run-golden は sys.argv を組み立てるため CLI 引数を足せない)
    m.check_news_count = lambda n, min_news: None
```

`CRAWLERS` に 2 行追加:

```python
CRAWLERS = [
    ("cal-oshirase-fetch", "cal-oshirase-fetch", _setup_oshirase, None),
    ("cal-oshirase-update", "cal-oshirase-fetch", _setup_oshirase, "cal-oshirase-update"),
    ("cal-shicho-blog-fetch", "cal-shicho-blog-fetch", _setup_shicho_blog, None),
    ("cal-tourism-news-fetch", "cal-tourism-news-fetch", _setup_tourism_news, None),
    ("cal-tourism-news-cancel", "cal-tourism-news-fetch", _setup_tourism_news,
     "cal-tourism-news-cancel"),
]
```

`cal-tourism-news-cancel` 用の seed を作る (既存本番がある状態の再現)。
`api-page1.json` の中から `event_date` が取れる記事を 1 つ選び、その `id` と
LLM 応答の `event_date` を使って本番 YAML を 1 つ置く:

```bash
python3 - <<'PY'
import json, os
FIX = "calendar/tests/fixtures/cal-tourism-news-fetch"
posts = json.load(open(f"{FIX}/api-page1.json", encoding="utf-8"))
replies = json.load(open(f"{FIX}/llm.json", encoding="utf-8"))
target = None
for p in posts:
    raw = replies.get(str(p["id"]))
    if not raw:
        continue
    try:
        ex = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    except Exception:
        continue
    if ex.get("event_date"):
        target = (p, ex)
        break
if not target:
    raise SystemExit("event_date が取れる記事が fixtures にありません。"
                     "CAPTURE_COUNT を増やして再取得してください。")
p, ex = target
d = ex["event_date"]
out = f"calendar/tests/seed/cal-tourism-news-cancel/{d[:4]}"
os.makedirs(out, exist_ok=True)
path = f"{out}/{d[5:]}_tourism-news-{p['id']}-event.yaml"
with open(path, "w", encoding="utf-8") as f:
    f.write(
        f'uid: "tourism-news-{p["id"]}-event@hanno.city.tecoli.com"\n'
        f'summary: "🎪 {p["title"]["rendered"]}"\n'
        f'url: "{p["link"]}"\n'
        f'dtstart: "{d}"\n'
        f'dtend: "{ex.get("event_end_date") or d}"\n'
        'description: |-\n'
        '  前世代 (seed)\n'
        '\n'
        'source:\n'
        '  type: hanno-tourism-jp-news\n'
        f'  id: "{p["id"]}"\n'
        f'  url: "{p["link"]}"\n'
    )
print("wrote", path)
PY
```

この seed があると、同じ記事を再処理したときに `has_existing_event=True` の経路
(中止なら【中止】へ書き換え) が golden に載る。

- [ ] **Step 7: golden を生成して中身を目視**

```bash
python3 calendar/tests/run-golden --update
git diff --stat calendar/tests/golden/
```
生成された YAML を開いて、`dtstart` / `summary` / `description` が
妥当かを**必ず目視で確認する**。おかしければ golden ではなく実装を直す。

- [ ] **Step 8: golden が安定することを確認**

Run: `python3 calendar/tests/run-golden`
Expected: PASS (2 回連続で走らせても同じ)

- [ ] **Step 9: コミット**

```bash
git add calendar/bin/cal-tourism-news-fetch calendar/tests/
git commit -m "test(news): 中止書き換えのテストと golden fixtures を追加

LLM は記録済み応答を再生する。非決定的なので実呼び出しはしない。"
```

---

### Task 11: CI 組み込み、評価スクリプト、README 更新

**Files:**
- Modify: `.github/workflows/cal-daily.yml`
- Create: `calendar/tests/corpus/README.md`
- Create: `calendar/tests/eval-news-prompt` (LLM を実呼び出しする手動評価ツール)
- Modify: `calendar/README.md:291-313` (「既知のギャップ」節)

**Interfaces:**
- Consumes: Task 8 の CLI (`--out-dir` / `--min-news`)
- Produces: なし (最終タスク)

- [ ] **Step 1: CI に crawl ステップを追加**

`.github/workflows/cal-daily.yml` の「Crawl hanno-tourism」ステップの直後に挿入:

```yaml
      - name: Crawl hanno-tourism-news
        # ANTHROPIC_API_KEY が無いと description の組み立てが LLM 要約から本文
        # そのままに変わり content_hash が変動する (2026-05-26 の oshirase 障害と
        # 同じ罠)。必須。
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: ./calendar/bin/cal-tourism-news-fetch --out-dir calendar/events --min-news 100 || echo "hanno-tourism-news" >> "$RUNNER_TEMP/crawl-failures.txt"
```

- [ ] **Step 2: corpus を置く**

調査に使った 137 件の API レスポンスを取り直して置く:

```bash
mkdir -p calendar/tests/corpus
python3 - <<'PY'
import json, urllib.request
out = []
for p in (1, 2):
    url = ("https://hanno-tourism.jp/wp-json/wp/v2/news?per_page=100"
           f"&page={p}&_fields=id,link,slug,date_gmt,modified_gmt,title,content,tag-news")
    req = urllib.request.Request(url, headers={"User-Agent": "myhanno-calendar-fetcher/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out.extend(json.loads(r.read().decode("utf-8")))
with open("calendar/tests/corpus/news-all.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(len(out))
PY
```

`calendar/tests/corpus/README.md`:

```markdown
# corpus

プロンプト改訂時の手動評価に使う実データのスナップショット。
CI では読まない (`run-golden` が使うのは `../fixtures/`)。

- `news-all.json` — hanno-tourism.jp `/wp-json/wp/v2/news` の全件 (取得時 137 件)

`../seed/` とは別物。`seed/` は「out-dir に事前展開する既存 YAML」で、
こちらは「クローラへの入力となる生の API レスポンス」。

更新: `calendar/tests/eval-news-prompt --refresh`
```

- [ ] **Step 3: 評価スクリプトを書く**

`calendar/tests/eval-news-prompt` (新規、実行可能):

```python
#!/usr/bin/env python3
"""calendar/tests/eval-news-prompt — news 抽出プロンプトの手動評価ツール。

LLM を実呼び出しするので CI には載せない。EXTRACT_SYSTEM_PROMPT を改訂したとき、
corpus 全件に対して抽出と機械検証を回し、通過率と失格理由の内訳を出す。

  ANTHROPIC_API_KEY=... python3 calendar/tests/eval-news-prompt
  ANTHROPIC_API_KEY=... python3 calendar/tests/eval-news-prompt --limit 20
"""
from __future__ import annotations
import argparse, collections, importlib.machinery, importlib.util, json, os, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
CORPUS = os.path.join(HERE, "corpus", "news-all.json")

loader = importlib.machinery.SourceFileLoader("m",
                                              os.path.join(BIN, "cal-tourism-news-fetch"))
spec = importlib.util.spec_from_loader("m", loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="先頭 N 件だけ評価")
    args = ap.parse_args()

    if not m.llm_available():
        sys.exit("ANTHROPIC_API_KEY が必要です")
    with open(CORPUS, encoding="utf-8") as f:
        posts = json.load(f)
    if args.limit:
        posts = posts[:args.limit]

    reasons = collections.Counter()
    passed = 0
    for i, p in enumerate(posts, 1):
        title = (p.get("title") or {}).get("rendered", "")
        body = m.html_to_text((p.get("content") or {}).get("rendered", ""))
        pub = date.fromisoformat(m.jst_date_of(p["date_gmt"]))
        ex = m.extract_with_llm(title, body)
        if ex is None:
            reasons["llm-failed"] += 1
            continue
        if not ex.get("event_date"):
            reasons["no-date"] += 1
            continue
        why = m.verify_event_date(ex, body, pub)
        if why:
            reasons[why.split(":")[0]] += 1
            print(f"  [{i}] REJECT {why}  <- {title[:40]}")
            continue
        passed += 1
        print(f"  [{i}] OK {ex['event_date']} ({ex['status']})  <- {title[:40]}")

    n = len(posts)
    print(f"\n通過 {passed}/{n} ({100*passed/n:.0f}%)")
    for k, v in reasons.most_common():
        print(f"  {k}: {v}")
    print("\n注意: 通過率は適合率ではない。通過した日付が本当に開催日かは目視で確認すること。")


if __name__ == "__main__":
    main()
```

```bash
chmod +x calendar/tests/eval-news-prompt
```

- [ ] **Step 4: 評価スクリプトを走らせて結果を確認**

```bash
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" python3 calendar/tests/eval-news-prompt --limit 40
```
Expected: 通過率と失格理由の内訳が出る。**通過した日付が本当に開催日かを目視で確認する。**
調査時の正規表現ベースの適合率 (約 1/3) を明確に上回っていること。
下回る場合は `EXTRACT_SYSTEM_PROMPT` を改訂して再実行する。

- [ ] **Step 5: `calendar/README.md` を更新**

`### 既知のギャップ: news 投稿タイプは未対応 (2026-08-10)` の節 (291〜311 行目) を
以下で置き換える。末尾の LLM 版 extractor への言及
(`city-tecoli/tools/hanno-tourism-extractor/`) は残す。

```markdown
## cal-tourism-news-fetch (news 投稿タイプ)

`cal-tourism-fetch` が見るのは投稿タイプ `tour` だけ。祭り・花火・盆踊りなどの
単発イベント告知は `news` (`/news/<slug>/`) に載るので、こちらは別クローラが扱う。

REST API (`/wp-json/wp/v2/news`) の `content.rendered` に本文が露出しているので
**HTML の追加取得が要らない**。全件が per_page=100 の 2 リクエストで完結する
(実測 137 件)。更新検知は `tour` と同じ `modified_gmt` 方式。

### 告知と本番の 2 系統

1 記事から最大 2 つのイベントを作る。

| | dtstart | UID | 対象 |
|---|---|---|---|
| 告知 | 記事の公開日 | `tourism-news-<id>-<hash6>` | news 全件 |
| 本番 | 抽出した開催日 | `tourism-news-<id>-event` | 開催日が取れたものだけ |

掲載日は事実そのものなので嘘をつきようがない。抽出の当たり外れは本番側だけが
引き受ける。開催日が取れなければ告知だけが残る。

告知は `cal-oshirase-fetch` と同じく**世代を作る** (内容が変われば新 UID、
前世代は残り `source.supersedes` で繋がる)。本番は世代を作らず、中止・延期が
追記されたら同じ UID のまま `summary` を `【中止】…` に書き換える。

### 開催日は二重チェックしたものだけ採る

`news` には `tour` の `<dl><dt>開催日・時間</dt>` に相当する定型フィールドが無い
(実測: 日時ラベルを持つのはイベント系 69 件中 13 件)。正規表現だけでは再現率 65%
に対し適合率が約 1/3 まで落ちる。更新スタンプ・終了日・副イベント・中止追記を
拾ってしまうため。

そこで Haiku 4.5 に「どの日付が開催日か」の意味判断をさせ、返ってきた日付を
コード側で検算する。検算は 5 項目で、全部通過して初めて本番を作る。

1. LLM が返した根拠文字列が本文に実在するか (幻覚検出)
2. 根拠と結論の月日が一致するか
3. 根拠に曜日表記があれば実際の曜日と一致するか
4. 記事公開日の −31 〜 +400 日の範囲か
5. 根拠が更新スタンプ (`6/16更新` 等) でないか

失格したらログに理由を出して本番を作らない。告知は作る。

### そのほかの決めごと

- `tag-news` タクソノミー (`イベント`/`飯能まつり`/`エコツアー`) は**掲載可否には
  使わない**。表示用の絵文字を決めるだけ。タグ付け漏れが実測 2 件あるため
- 同じ記事を指す**手動 YAML があれば本番を作らない**。URL はパーセントデコードして
  比較する (手動 YAML と API の `link` でエンコード表記が揺れる)
- `--backfill-months` (既定 6) は初回だけでなく**毎回適用するフィルタ**。
  これより古い記事は更新されても処理しない
- 記事が API から消えても**既存 YAML は残す** (追随はスコープ外)
- `--min-news` (既定 100) 未満なら exit 2。`news` は蓄積型で 2017 年の記事も
  残っているため下限を高く置ける
- 抽出失敗率は**判定に使わない**。日付が無いのが正常な記事 (休業案内・会報誌発行)
  を含むので、`tour` の「全件 0 セッションなら異常」は移植できない

### プロンプトを変えたとき

golden テストが見ているのは「記録済み LLM 応答に対してコード側が正しく振る舞うか」
であって、プロンプト改訂の効果は検証していない。改訂したら
`calendar/tests/eval-news-prompt` を手で回すこと (LLM を実呼び出しするので CI には
載せていない)。入力は `calendar/tests/corpus/news-all.json`。

設計の経緯と実データの調査結果:
[`docs/superpowers/specs/2026-08-10-tourism-news-design.md`](../docs/superpowers/specs/2026-08-10-tourism-news-design.md)
```

- [ ] **Step 6: 全テストと golden を回す**

```bash
for t in calendar/tests/test_*.py; do echo "== $t"; python3 "$t" || break; done
python3 calendar/tests/run-golden
```
Expected: 全て PASS

- [ ] **Step 7: コミット**

```bash
git add .github/workflows/cal-daily.yml calendar/tests/ calendar/README.md
git commit -m "feat(news): CI 組み込み、プロンプト評価ツール、README 更新

CI には ANTHROPIC_API_KEY を必ず渡す (無いと description の組み立てが
変わり content_hash が変動する)。評価ツールは LLM を実呼び出しするので
CI には載せない。"
```

---

## 完了条件

- [ ] `python3 calendar/tests/run-golden` が PASS (既存 3 件 + 新規 2 件)
- [ ] `calendar/tests/test_*.py` が全て PASS
- [ ] `./calendar/bin/cal-tourism-news-fetch --dry-run` が実サイトに対して正常終了
- [ ] `cal-oshirase-fetch` の golden が Task 1 の前後で不変
- [ ] 「はんのう昭和盆踊り」相当の記事から本番エントリが 8/8 に生成される
- [ ] `calendar/README.md` の「既知のギャップ」節が実装済みの記述に差し替わっている
