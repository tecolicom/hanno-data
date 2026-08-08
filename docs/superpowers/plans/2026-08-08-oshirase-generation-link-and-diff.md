# お知らせ記事の世代リンクと差分要約 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 同一ページの記事が更新されたとき、新しいイベント YAML から前世代を辿れるようにし、`description` 冒頭に「前回掲載日」と「主な変更」を出す。

**Architecture:** `cal-oshirase-fetch` の incremental モードは既に「更新のたびに別 YAML を作り、古い世代を残す」構造なので、(1) 生成時に直前世代を索引から引いて `source.supersedes` に記録し、(2) 直前世代の `description`（＝前回の LLM 要約）と新しい本文を Claude Haiku に比較させて 1 行の差分文を作り、既存の `status_header` 機構に載せる。元記事本文は保存しない。

**Tech Stack:** Python 3 (標準ライブラリのみ + `httpx`)、Claude Haiku 4.5 (Messages API 直叩き)、golden 回帰テスト (`calendar/tests/run-golden`)

**Spec:** `docs/superpowers/specs/2026-08-08-oshirase-generation-link-and-diff-design.md`

## Global Constraints

- 対象は `oshirase` クローラのみ。`shicho-blog` には結線しない（共通処理は `_lib` に置く）。
- `content_hash` の材料は **(title, date, body) のみ**。`supersedes` も `status_header` も含めない。既存 YAML の hash を絶対に動かさない。
- `description` は plain text の Google Calendar 予定欄に出る。**Markdown 記法は使わない**（`strip_markdown()` を通す）。
- LLM 呼び出しは `_llm_available()` が True のときだけ。CI / golden テストでは呼ばない。
- 空 body で LLM を呼ばない（ハルシネーション防止の既存安全装置を踏襲）。
- LLM 失敗時は差分行を省いて degrade する。例外を上に投げない。
- `TRANSLATION_FORMAT_VERSION` は bump しない。
- コメント・docstring は既存コードと同じく日本語。

---

### Task 1: oshirase golden テストを hermetic に戻す

**背景:** コミット `9b9567e` で記事取得を `fetch_with_cache()` に切り替えたとき、`run-golden` の `_setup_oshirase` が `fetch` しかモックしていないため、記事本文の取得が**実ネットワークに出ている**。対象記事は既に削除されていて 404 になり、golden テストは main 上で失敗している。

```
$ python3 calendar/tests/run-golden
  ERROR fetching https://www.city.hanno.lg.jp/emergency/13691.html: HTTP Error 404: Not Found
FAIL cal-oshirase-fetch: key set differs
  only in golden:    ['oshirase-13685-dfde2a.yaml', ...]
  only in generated: []
```

後続タスクは golden の緑を前提にするので、ここで直す。

**Files:**
- Modify: `calendar/tests/run-golden:49-50` (`_setup_oshirase`)

**Interfaces:**
- Consumes: なし
- Produces: `_setup_oshirase(m, crawler, manifest)` が `fetch_with_cache` / `load_http_cache` / `save_http_cache` をモックする（Task 4 で seed 対応を足す土台）

- [ ] **Step 1: 失敗を再現する**

Run: `python3 calendar/tests/run-golden`
Expected: FAIL。`ERROR fetching ... HTTP Error 404` が出て `only in generated: []`

- [ ] **Step 2: `_setup_oshirase` に記事取得のモックを足す**

`calendar/tests/run-golden` の `_setup_oshirase` を置き換える:

```python
# fixture 記事の Last-Modified 固定値。JST 2026-06-12 → dtstart = +1 日 = 2026-06-13。
# golden 捕捉時の実サーバ値と一致するので、golden はそのまま維持される。
OSHIRASE_FIXED_LM = "Fri, 12 Jun 2026 09:00:00 GMT"


def _setup_oshirase(m, crawler, manifest):
    m._llm_available = lambda: False  # LLM 経路を断つ (deterministic)
    # 記事本文は fetch_with_cache 経由なので、こちらもモックしないと実ネットワークに出る
    m.fetch_with_cache = lambda url, etag, lm: (
        (_read_fixture(crawler, manifest[url]), None, OSHIRASE_FIXED_LM) if url in manifest
        else (None, None, None)  # manifest 外の URL は 304 = skip
    )
    m.load_http_cache = lambda: {}
    m.save_http_cache = lambda c: None
```

- [ ] **Step 3: golden が緑になることを確認**

Run: `python3 calendar/tests/run-golden`
Expected: PASS。`OK cal-oshirase-fetch: 3 files match` と `OK cal-shicho-blog-fetch: 2 files match`、末尾に `All golden checks passed.`

ネットワークに出ていないことも確認する（`ERROR fetching` が出ないこと、`Fetching https://...feed.php` の行は `m.fetch` モック済みなので出てよい）。

- [ ] **Step 4: golden ファイルが 1 バイトも変わっていないことを確認**

Run: `git status --porcelain calendar/tests/golden/`
Expected: 空（`--update` を実行していないので当然だが、Step 3 が「たまたま通った」のでないことの確認）

- [ ] **Step 5: Commit**

```bash
git add calendar/tests/run-golden
git commit -m "fix(tests): oshirase golden の記事取得をモックして hermetic に戻す

9b9567e で記事取得が fetch_with_cache に移ったが run-golden が fetch しか
モックしておらず、実ネットワークに出ていた。対象記事が 404 になり main 上で
golden が失敗していた。"
```

---

### Task 2: `_lib` に YAML block 読み出しと description 分解を用意する

**Files:**
- Modify: `calendar/bin/_lib.py` (`read_yaml_scalar` の直後に追加、末尾付近に `split_description` を移設)
- Modify: `calendar/bin/cal-translate-en:134-158` (`split_description` を削除して `_lib` から import)
- Create: `calendar/tests/test_description_parts.py`

**Interfaces:**
- Consumes: `_lib.AI_DISCLAIMER_JP`
- Produces:
  - `_lib.STATUS_MARKERS: tuple[str, ...]` = `("🆕", "🔄", "📝")`
  - `_lib.read_yaml_block(path: str, key: str) -> str | None`
  - `_lib.strip_status_header(text: str) -> str`
  - `_lib.split_description(text: str) -> tuple[str, str | None]`

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_description_parts.py`:

```python
#!/usr/bin/env python3
"""_lib の description 分解ヘルパのユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_description_parts.py
"""
import importlib.machinery
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "bin", "_lib.py")
loader = importlib.machinery.SourceFileLoader("cal_lib", LIB)
spec = importlib.util.spec_from_loader("cal_lib", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


SAMPLE_YAML = '''uid: "oshirase-7334-497925@hanno.city.tecoli.com"
summary: "ℹ️ 市有地の売却"
description: |-
  \U0001f504 内容更新 (公開日: 2026-08-07)
  
  AI による要約 (正確な情報は元記事をご確認ください)
  
  市有地の一般競争入札を実施します。
  
  飯能市公式サイト 新着情報: https://example.com/7334.html

render:
  gcal:
    mode: single-allday
'''


def _write(text):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def test_read_yaml_block_top_level():
    path = _write(SAMPLE_YAML)
    got = mod.read_yaml_block(path, "description")
    os.remove(path)
    assert got is not None
    assert got.startswith("🔄 内容更新 (公開日: 2026-08-07)")
    assert got.endswith("飯能市公式サイト 新着情報: https://example.com/7334.html")
    # ブロック外 (render:) を巻き込んでいない
    assert "render:" not in got


def test_read_yaml_block_nested_indent():
    path = _write(
        'translations:\n'
        '  en:\n'
        '    description: |-\n'
        '      Automated translation\n'
        '      \n'
        '      Second line\n'
        '    model: "claude-haiku-4-5"\n'
    )
    got = mod.read_yaml_block(path, "description")
    os.remove(path)
    assert got == "Automated translation\n\nSecond line"


def test_read_yaml_block_missing_key():
    path = _write(SAMPLE_YAML)
    got = mod.read_yaml_block(path, "nosuchkey")
    os.remove(path)
    assert got is None


def test_strip_status_header_removes_single_line():
    text = "🔄 内容更新 (公開日: 2026-08-07)\n\nAI による要約\n\n本文"
    assert mod.strip_status_header(text) == "AI による要約\n\n本文"


def test_strip_status_header_removes_two_lines():
    text = "🔄 内容更新 (公開日: 2026-08-07)\n主な変更: 入札日を変更。\n\nAI による要約\n\n本文"
    assert mod.strip_status_header(text) == "AI による要約\n\n本文"


def test_strip_status_header_keeps_text_without_header():
    text = "AI による要約\n\n本文"
    assert mod.strip_status_header(text) == text


def test_strip_status_header_handles_header_only():
    assert mod.strip_status_header("🆕 新着掲載 (公開日: 2026-08-07)") == ""


def test_split_description_strips_disclaimer_after_status_header():
    # 従来 ^ 固定だったため status 行があると disclaimer が剥がれなかった回帰テスト
    text = (
        "🔄 内容更新 (公開日: 2026-08-07)\n\n"
        + mod.AI_DISCLAIMER_JP
        + "\n\n本文です。\n\n飯能市公式サイト 新着情報: https://example.com/7334.html"
    )
    body, url = mod.split_description(text)
    assert mod.AI_DISCLAIMER_JP not in body
    assert body.startswith("🔄 内容更新")   # status 行は残す (EN 側で訳すため)
    assert body.endswith("本文です。")
    assert url == "https://example.com/7334.html"


def test_split_description_without_status_header():
    text = mod.AI_DISCLAIMER_JP + "\n\n本文です。\n\nラベル: https://example.com/x.html"
    body, url = mod.split_description(text)
    assert body == "本文です。"
    assert url == "https://example.com/x.html"


def test_split_description_bare_url_line():
    body, url = mod.split_description("本文です。\n\nhttps://example.com/x.html")
    assert body == "本文です。"
    assert url == "https://example.com/x.html"


def test_split_description_no_url():
    body, url = mod.split_description("本文です。")
    assert body == "本文です。"
    assert url is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all description-parts tests passed")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_description_parts.py`
Expected: FAIL — `AttributeError: module 'cal_lib' has no attribute 'read_yaml_block'`

- [ ] **Step 3: `_lib.py` に 3 つを実装する**

`calendar/bin/_lib.py` の `read_yaml_scalar()` 定義の直後に追加:

```python
# description 冒頭の status 行を識別する先頭文字 (各 crawler が付与する絵文字)
STATUS_MARKERS = ("🆕", "🔄", "📝")


def read_yaml_block(path: str, key: str) -> str | None:
    """YAML の block scalar (`KEY: |` / `KEY: |-`) の中身を返す.

    インデントを除去して元のテキストを復元する。ネストしたキー
    (`translations.en.description` 等) も、その行のインデント + 2 を本文の
    インデントとみなして扱う。1 行スカラ (`KEY: "..."`) は対象外
    (それは read_yaml_scalar の担当)。見つからなければ None。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
    except Exception:
        return None
    head = re.compile(r"^(\s*)" + re.escape(key) + r":\s*\|[-+]?\s*$")
    for i, ln in enumerate(lines):
        m = head.match(ln)
        if not m:
            continue
        base = len(m.group(1))
        body: list[str] = []
        for cur in lines[i + 1:]:
            if cur.strip() == "":
                body.append("")
                continue
            indent = len(cur) - len(cur.lstrip(" "))
            if indent <= base:
                break          # ブロック終了 (同階層以上のキーに戻った)
            body.append(cur[base + 2:])
        while body and body[-1] == "":
            body.pop()
        return "\n".join(body)
    return None


def strip_status_header(text: str) -> str:
    """description 冒頭の status ブロックを除去する.

    status ブロックは STATUS_MARKERS のいずれかで始まり、最初の空行まで
    (複数行可)。該当しなければ text をそのまま返す。

    注: split_description() 側では status 行を残す。cal-translate-en が
    status 行を英訳して EN イベントにも出しているため。旧要約を LLM に
    渡すときだけ、この関数で明示的に落とす。
    """
    if not text.startswith(STATUS_MARKERS):
        return text
    parts = text.split("\n\n", 1)
    return parts[1] if len(parts) == 2 else ""


def split_description(text: str) -> tuple[str, str | None]:
    """description を (本文, source_url) に分解.

    LLM に渡したくない要素を事前に除去:
      - AI 要約 disclaimer 行 (oshirase)
      - 末尾の "ラベル: URL" 行 (source URL)

    status 行 (🆕/🔄/📝) は**残す**。cal-translate-en がこれを英訳して
    EN 側にも出すため。落としたい場合は strip_status_header() を先に通す。
    """
    # AI disclaimer 行を除去。re.M が必須: status 行がある YAML では
    # disclaimer が先頭に来ないため、^ 固定だと剥がれず英訳側で二重化する。
    text = re.sub(r"^" + re.escape(AI_DISCLAIMER_JP) + r"\s*\n+", "", text, flags=re.M)

    # 末尾の URL 行 (例: "市長ブログ「市政一直線」: https://...", "飯能市公式サイト 新着情報: https://...")
    source_url = None
    m = re.search(r"\n+([^\n]*?:[ \t]*(https?://\S+))\s*$", text)
    if m:
        source_url = m.group(2)
        text = text[:m.start()]
    else:
        # URL 単独行 (ラベル無し) も検出
        m2 = re.search(r"\n+(https?://\S+)\s*$", text)
        if m2:
            source_url = m2.group(1)
            text = text[:m2.start()]

    return text.strip(), source_url
```

注: `AI_DISCLAIMER_JP` は `_lib.py` の定数セクションで既に定義済みなので、`split_description` はそれより後に置けばよい。

- [ ] **Step 4: テストを実行して通ることを確認**

Run: `python3 calendar/tests/test_description_parts.py`
Expected: PASS — `OK: all description-parts tests passed`

- [ ] **Step 5: `cal-translate-en` を `_lib` の実装に載せ替える**

`calendar/bin/cal-translate-en` の `def split_description(...)` 定義（`_lib` に移した同名関数）を丸ごと削除し、import 行を修正する:

```python
from _lib import (yaml_escape_str, yaml_block_scalar, strip_markdown,
                  AI_DISCLAIMER_JP, split_description)
```

（既存の import 文の形に合わせること。`AI_DISCLAIMER_JP` が `cal-translate-en` 内で他に使われていなければ import から外してよい。）

- [ ] **Step 6: 既存テストが壊れていないことを確認**

Run: `python3 calendar/tests/run-golden && python3 calendar/tests/test_last_modified_dating.py && python3 calendar/tests/test_tourism_discovery.py`
Expected: すべて PASS

Run: `python3 -c "import importlib.machinery,importlib.util,os; l=importlib.machinery.SourceFileLoader('t','calendar/bin/cal-translate-en'); s=importlib.util.spec_from_loader('t',l); m=importlib.util.module_from_spec(s); l.exec_module(m); print(m.split_description('本文\n\nラベル: https://e.com/a'))"`
Expected: `('本文', 'https://e.com/a')`

- [ ] **Step 7: Commit**

```bash
git add calendar/bin/_lib.py calendar/bin/cal-translate-en calendar/tests/test_description_parts.py
git commit -m "feat(cal): description の block 読み出し / status 行除去 / 分解を _lib に集約

- read_yaml_block: block scalar (|, |-) の中身を復元
- strip_status_header: 冒頭の 🆕/🔄/📝 ブロックを除去
- split_description: cal-translate-en から移設。disclaimer 除去に re.M を追加し、
  status 行がある YAML でも剥がれるよう修正 (英訳側の disclaimer 二重化の解消)"
```

---

### Task 3: `page_id` 別の世代索引を作る

**Files:**
- Modify: `calendar/bin/cal-oshirase-fetch:310-334` (`_existing_content_hashes` を置き換え)
- Modify: `calendar/bin/cal-oshirase-fetch:402-408` (main の pre-scan)
- Modify: `calendar/bin/cal-oshirase-fetch:519-526` (loop 内の set 更新)
- Create: `calendar/tests/test_generation_index.py`

**Interfaces:**
- Consumes: `_lib.read_yaml_scalar`
- Produces: `_existing_generations(events_dir: str, uid_prefix: str) -> dict[str, list[tuple[str, str, str, str]]]`
  - キー: `page_id`
  - 値: `(dtstart, uid, path, content_hash)` の list。**dtstart 降順・同 dtstart は path 降順**にソート済み。`[0]` が直前世代。
  - `content_hash` は `sha256-` prefix を外した 16 桁。

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_generation_index.py`:

```python
#!/usr/bin/env python3
"""cal-oshirase-fetch の世代索引のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_generation_index.py
"""
import importlib.machinery
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_oshirase_fetch",
                                              os.path.join(BIN, "cal-oshirase-fetch"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def _yaml(uid, dtstart, content_hash):
    return (f'uid: "{uid}"\n'
            f'dtstart: "{dtstart}"\n'
            f'dtend: "{dtstart}"\n'
            f'source:\n'
            f'  content_hash: "sha256-{content_hash}"\n')


def _make_events(specs):
    """specs: [(filename, uid, dtstart, content_hash)] → 一時 events dir を作る."""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "2026"), exist_ok=True)
    for fname, uid, dtstart, ch in specs:
        with open(os.path.join(d, "2026", fname), "w", encoding="utf-8") as f:
            f.write(_yaml(uid, dtstart, ch))
    return d


def test_groups_by_page_id():
    d = _make_events([
        ("05-01_oshirase-7334.yaml", "oshirase-7334@x", "2026-05-01", "aaaaaaaaaaaaaaaa"),
        ("08-08_oshirase-7334-497925.yaml", "oshirase-7334-497925@x", "2026-08-08", "497925995081bafc"),
        ("06-13_oshirase-13691-6f01a7.yaml", "oshirase-13691-6f01a7@x", "2026-06-13", "6f01a79efed9044c"),
    ])
    idx = mod._existing_generations(d, "oshirase")
    assert set(idx) == {"7334", "13691"}
    assert len(idx["7334"]) == 2
    assert len(idx["13691"]) == 1


def test_newest_generation_first():
    d = _make_events([
        ("05-01_oshirase-7334.yaml", "oshirase-7334@x", "2026-05-01", "aaaaaaaaaaaaaaaa"),
        ("08-08_oshirase-7334-497925.yaml", "oshirase-7334-497925@x", "2026-08-08", "497925995081bafc"),
    ])
    idx = mod._existing_generations(d, "oshirase")
    dtstart, uid, path, ch = idx["7334"][0]
    assert dtstart == "2026-08-08"
    assert uid == "oshirase-7334-497925@x"
    assert ch == "497925995081bafc"
    assert idx["7334"][1][0] == "2026-05-01"


def test_same_dtstart_tiebreak_is_stable():
    d = _make_events([
        ("07-08_oshirase-500-aaaaaa.yaml", "oshirase-500-aaaaaa@x", "2026-07-08", "aaaaaaaaaaaaaaaa"),
        ("07-08_oshirase-500-bbbbbb.yaml", "oshirase-500-bbbbbb@x", "2026-07-08", "bbbbbbbbbbbbbbbb"),
    ])
    idx = mod._existing_generations(d, "oshirase")
    # 同 dtstart は path 降順 → bbbbbb が先
    assert idx["500"][0][1] == "oshirase-500-bbbbbb@x"
    assert idx["500"][1][1] == "oshirase-500-aaaaaa@x"


def test_ignores_other_prefixes():
    d = _make_events([
        ("07-08_shicho-blog-99-aaaaaa.yaml", "shicho-blog-99-aaaaaa@x", "2026-07-08", "aaaaaaaaaaaaaaaa"),
    ])
    assert mod._existing_generations(d, "oshirase") == {}


def test_empty_dir():
    d = tempfile.mkdtemp()
    assert mod._existing_generations(d, "oshirase") == {}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all generation-index tests passed")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_generation_index.py`
Expected: FAIL — `AttributeError: module 'cal_oshirase_fetch' has no attribute '_existing_generations'`

- [ ] **Step 3: `_existing_content_hashes` を `_existing_generations` に置き換える**

`calendar/bin/cal-oshirase-fetch` の `_existing_content_hashes` 関数全体を以下に置換:

```python
def _existing_generations(events_dir: str, uid_prefix: str) -> dict[str, list[tuple[str, str, str, str]]]:
    """既存 YAML を page_id 別に集めた世代索引を返す。

    値は (dtstart, uid, path, content_hash) の list で、dtstart 降順・同 dtstart は
    path 降順に安定ソート済み (先頭 = 直前世代)。content_hash は "sha256-" prefix を
    外した 16 桁。

    incremental mode の skip 判定 (page_id, content_hash) と、更新イベントから
    直前世代を引く supersedes 解決の両方に使う。once-per-page と incremental の
    両形式の UID から page_id を抽出する:
    `oshirase-<pid>@...` / `oshirase-<pid>-<hash6>@...`。
    """
    import glob
    pattern = os.path.join(events_dir, "**", "*.yaml")
    idx: dict[str, list[tuple[str, str, str, str]]] = {}
    pid_re = re.compile(rf"^{re.escape(uid_prefix)}-(\d+)(?:-[A-Za-z0-9]+)?@")
    for path in glob.glob(pattern, recursive=True):
        uid = _read_yaml_scalar(path, "uid")
        if not uid:
            continue
        m = pid_re.match(uid)
        if not m:
            continue
        ch = _read_yaml_scalar(path, "content_hash")
        if not ch:
            continue
        if ch.startswith("sha256-"):
            ch = ch[len("sha256-"):]
        dtstart = _read_yaml_scalar(path, "dtstart") or ""
        idx.setdefault(m.group(1), []).append((dtstart, uid, path, ch))
    for gens in idx.values():
        gens.sort(key=lambda g: (g[0], g[2]), reverse=True)
    return idx
```

- [ ] **Step 4: main の pre-scan を索引から導出するよう書き換える**

`calendar/bin/cal-oshirase-fetch` の main 内、`existing_hashes` を作っている箇所を置換:

```python
    # incremental mode 用: 既存 YAML を page_id 別の世代索引に pre-scan する。
    # skip 判定用の (page_id, content_hash) と、直前世代 (supersedes / 前回掲載日)
    # の解決を同じ索引から導く。
    existing_gens: dict[str, list[tuple[str, str, str, str]]] = {}
    existing_hashes: set[tuple[str, str]] = set()
    existing_page_ids: set[str] = set()
    if not args.once_per_page:
        existing_gens = _existing_generations(args.out_dir, args.uid_prefix)
        existing_hashes = {(pid, g[3]) for pid, gens in existing_gens.items() for g in gens}
        existing_page_ids = set(existing_gens)
```

- [ ] **Step 5: loop 末尾の set 更新に索引の更新を足す**

`calendar/bin/cal-oshirase-fetch` の loop 末尾、`existing_hashes.add(...)` の箇所を置換:

```python
        # incremental では次の loop iter 内でも自身を skip 対象にできるよう索引を更新
        if not args.once_per_page:
            existing_hashes.add((it["page_id"], content_hash))
            existing_page_ids.add(it["page_id"])
            existing_gens.setdefault(it["page_id"], []).insert(
                0, (dtstart, uid, out_path, content_hash))
```

- [ ] **Step 6: テストと golden を実行**

Run: `python3 calendar/tests/test_generation_index.py && python3 calendar/tests/run-golden`
Expected: どちらも PASS。golden は 5 ファイル一致（出力は変わらないはず）

- [ ] **Step 7: Commit**

```bash
git add calendar/bin/cal-oshirase-fetch calendar/tests/test_generation_index.py
git commit -m "refactor(oshirase): 既存 YAML の pre-scan を page_id 別の世代索引に拡張

_existing_content_hashes (set) を _existing_generations (page_id → 世代 list) に
置き換え。skip 判定はここから導出し、直前世代の uid / dtstart も引けるようにする。
出力は不変 (golden 一致)。"
```

---

### Task 4: `source.supersedes` と「前回掲載」ヘッダを出す

**Files:**
- Modify: `calendar/bin/cal-oshirase-fetch:274-302` (`build_yaml_doc`)
- Modify: `calendar/bin/cal-oshirase-fetch:496-505` (incremental branch の status_header)
- Modify: `calendar/tests/run-golden` (seed 対応 + シナリオ追加)
- Create: `calendar/tests/seed/cal-oshirase-update/2026/05-01_oshirase-13691.yaml`
- Create: `calendar/tests/golden/cal-oshirase-update/` (`--update` で生成)

**Interfaces:**
- Consumes: `_existing_generations()` (Task 3)
- Produces: `build_yaml_doc(..., publish_date=None, supersedes: str | None = None)`
  — `supersedes` を渡すと `source:` ブロック末尾に `supersedes: "<uid>"` 行が出る

- [ ] **Step 1: `build_yaml_doc` に `supersedes` を足す**

`calendar/bin/cal-oshirase-fetch` の `build_yaml_doc` シグネチャと末尾を変更:

```python
def build_yaml_doc(uid: str, item_url: str, page_id: str, title: str, date_str: str,
                   description: str, method: str,
                   content_hash: str, fetched_at: str | None,
                   publish_date: str | None = None,
                   supersedes: str | None = None) -> str:
```

`publish_date` を append している if の直後に追加:

```python
    # 同じ page の直前世代 (= この YAML が置き換える内容) の uid。
    # 世代チェーンを辿るための唯一のリンクなので、content_hash には含めない
    # (含めると既存 YAML の hash が動いてカレンダーが氾濫する)。
    if supersedes:
        lines.append(f"  supersedes: {yaml_escape_str(supersedes)}")
```

- [ ] **Step 2: incremental branch で直前世代を引いてヘッダを組む**

`calendar/bin/cal-oshirase-fetch` の incremental branch、`status_header` を決めている箇所を置換:

```python
            uid = f"{args.uid_prefix}-{it['page_id']}-{content_hash[:6]}@{UID_NAMESPACE}"
            dtstart = dtstart_from_last_modified(
                http_cache.get(it["url"], {}).get("last_modified"), today_jst)
            publish_date = it["date"]            # dc:date を保持
            # status: 同 page_id に既存 YAML 無し → 新規 / 既存あり → 内容更新。
            # 更新の場合は直前世代の uid を supersedes に記録し、前回掲載日を header に出す。
            prev = existing_gens.get(it["page_id"], [])
            if prev:
                prev_dtstart, prev_uid, prev_path, _prev_hash = prev[0]
                supersedes = prev_uid
                status_header = f"🔄 内容更新 (公開日: {publish_date} / 前回掲載: {prev_dtstart})"
            else:
                supersedes = None
                status_header = f"🆕 新着掲載 (公開日: {publish_date})"
```

`once_per_page` branch の末尾（`status_header = ""` の行の直後）にも追加:

```python
            supersedes = None                    # legacy mode では世代リンクを作らない
```

`build_yaml_doc` の呼び出しに `supersedes=supersedes` を足す:

```python
        doc = build_yaml_doc(uid, it["url"], it["page_id"], it["title"], dtstart,
                             description, method, content_hash, None,
                             publish_date=publish_date, supersedes=supersedes)
```

- [ ] **Step 3: golden の seed 用 YAML を作る**

Create `calendar/tests/seed/cal-oshirase-update/2026/05-01_oshirase-13691.yaml`。

**注意: `description` ブロック内の「空行」は半角スペース 2 個の行**（`yaml_block_scalar()` が
全行を indent でパディングするため、実際の events/ もそうなっている）。エディタの
trailing whitespace 自動除去を切って書くこと。

```yaml
uid: "oshirase-13691@hanno.city.tecoli.com"
summary: "ℹ️ 飯能市道の通行止めについて（第1地区第8号線）"
url: "https://www.city.hanno.lg.jp/emergency/13691.html"
dtstart: "2026-05-01"
dtend: "2026-05-01"
description: |-
  🆕 新着掲載 (公開日: 2026-05-01)
  
  ## 市道第1地区第8号線の通行止めのお知らせ
  
  倒木のため、市道第1地区第8号線を全面通行止めとしています。解除の見込みは立っていません。
  
  飯能市公式サイト 新着情報: https://www.city.hanno.lg.jp/emergency/13691.html

render:
  gcal:
    mode: single-allday

source:
  type: city-hanno-oshirase
  id: "13691"
  url: "https://www.city.hanno.lg.jp/emergency/13691.html"
  fetched_at: "2026-05-01T00:00:00Z"
  content_hash: "sha256-00000000deadbeef"
  summary_method: "full"
```

注: `content_hash` は fixture の実 hash (`6f01a79efed9044c`) と**必ず異なる**値にする。一致すると skip されて更新イベントが生成されない。

- [ ] **Step 4: `run-golden` を seed 対応にしてシナリオを追加**

`calendar/tests/run-golden` を以下のように変更する。

import に `shutil` を追加:

```python
import importlib.machinery, importlib.util, glob, json, os, re, shutil, sys, tempfile
```

パス定数に `SEED` を追加:

```python
SEED = os.path.join(HERE, "seed")
```

`CRAWLERS` を 4-tuple に変更（`name` は golden ディレクトリ名、`crawler` は fixtures / スクリプト名）:

```python
# (golden 名, crawler スクリプト名, setup, seed dir 名 | None)
# seed を渡すと、その中身を out-dir に事前展開してから crawler を走らせる
# (= 既存 YAML がある状態の再現。更新検知 / supersedes の経路を通す)。
CRAWLERS = [
    ("cal-oshirase-fetch", "cal-oshirase-fetch", _setup_oshirase, None),
    ("cal-oshirase-update", "cal-oshirase-fetch", _setup_oshirase, "cal-oshirase-update"),
    ("cal-shicho-blog-fetch", "cal-shicho-blog-fetch", _setup_shicho_blog, None),
]
```

`_run_crawler` を書き換え:

```python
def _run_crawler(crawler, setup, seed):
    m = _load(crawler)
    manifest = _manifest(crawler)
    m.fetch = lambda url: _read_fixture(crawler, manifest[url])
    setup(m, crawler, manifest)
    out = {}
    saved_argv = sys.argv
    try:
        with tempfile.TemporaryDirectory() as d:
            if seed:
                shutil.copytree(os.path.join(SEED, seed), d, dirs_exist_ok=True)
            sys.argv = [crawler, "--out-dir", d]
            m.main()
            for p in glob.glob(os.path.join(d, "**", "*.yaml"), recursive=True):
                with open(p, encoding="utf-8") as f:
                    out[_golden_key(p)] = _normalize(f.read())
    finally:
        sys.argv = saved_argv
    return out
```

`main()` の loop を 4-tuple に合わせる:

```python
    for name, crawler, setup, seed in CRAWLERS:
        generated = _run_crawler(crawler, setup, seed)
        gdir = os.path.join(GOLD, name)
```

以降 loop 内の `crawler` を使っている print / 変数名は `name` に置換する（`FAIL {name}`, `OK {name}`, `{name}/{key}`）。

- [ ] **Step 5: 新シナリオの golden を生成して中身を目視確認**

Run: `python3 calendar/tests/run-golden --update`
Expected: `[update] cal-oshirase-fetch: 3 golden files` / `[update] cal-oshirase-update: 4 golden files` / `[update] cal-shicho-blog-fetch: 2 golden files`

Run: `cat calendar/tests/golden/cal-oshirase-update/oshirase-13691-6f01a7.yaml`
Expected: 以下を満たすこと。満たさなければ実装のバグなので直してから先へ進む。
- `description` 冒頭が `🔄 内容更新 (公開日: 2026-06-13 / 前回掲載: 2026-05-01)`
- `source:` ブロックに `supersedes: "oshirase-13691@hanno.city.tecoli.com"`
- `主な変更:` 行は**無い**（`_llm_available()` が False のため）

Run: `git diff --stat calendar/tests/golden/cal-oshirase-fetch/`
Expected: 空 — **既存シナリオの golden は 1 バイトも変わらないこと**

Run: `grep -c "🆕 新着掲載" calendar/tests/golden/cal-oshirase-update/oshirase-13685-dfde2a.yaml`
Expected: `1` — seed に無い page は従来どおり新着扱い

- [ ] **Step 6: golden が緑で再現することを確認**

Run: `python3 calendar/tests/run-golden`
Expected: `OK cal-oshirase-fetch: 3 files match` / `OK cal-oshirase-update: 4 files match` / `OK cal-shicho-blog-fetch: 2 files match` / `All golden checks passed.`

- [ ] **Step 7: 他のテストも回す**

Run: `python3 calendar/tests/test_generation_index.py && python3 calendar/tests/test_description_parts.py && python3 calendar/tests/test_last_modified_dating.py && python3 calendar/tests/test_tourism_discovery.py`
Expected: すべて PASS

- [ ] **Step 8: Commit**

```bash
git add calendar/bin/cal-oshirase-fetch calendar/tests/run-golden calendar/tests/seed calendar/tests/golden
git commit -m "feat(oshirase): 更新イベントに source.supersedes と前回掲載日を出す

同 page_id の直前世代を索引から引き、uid を source.supersedes に記録。
description 冒頭を '🔄 内容更新 (公開日: … / 前回掲載: …)' に拡張。
content_hash には含めないので既存 YAML の hash は動かない。

golden に seed 対応を追加し、既存 YAML がある状態 (= 更新検知経路) の
シナリオ cal-oshirase-update を新設。既存 golden はバイト一致で維持。"
```

---

### Task 5: 差分要約行を LLM で生成して結線する

**Files:**
- Modify: `calendar/bin/cal-oshirase-fetch` (定数セクション / LLM セクション / incremental branch)
- Create: `calendar/tests/test_diff_line.py`

**Interfaces:**
- Consumes: `_lib.read_yaml_block`, `_lib.strip_status_header`, `_lib.split_description`, `_llm_available()`, `strip_markdown()`
- Produces:
  - `diff_with_llm(title: str, prev_summary: str, new_body: str) -> str | None`
  - `_diff_line(title: str, prev_path: str, new_body: str) -> str | None`

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_diff_line.py`:

```python
#!/usr/bin/env python3
"""cal-oshirase-fetch の差分行生成のユニットテスト。LLM は差し替えるのでネットワーク非依存。
実行: python3 calendar/tests/test_diff_line.py
"""
import importlib.machinery
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_oshirase_fetch",
                                              os.path.join(BIN, "cal-oshirase-fetch"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

PREV_YAML = '''uid: "oshirase-7334@hanno.city.tecoli.com"
summary: "ℹ️ 市有地の売却"
dtstart: "2026-05-01"
description: |-
  \U0001f195 新着掲載 (公開日: 2026-05-01)
  
  AI による要約 (正確な情報は元記事をご確認ください)
  
  入札日は令和8年6月19日です。
  
  飯能市公式サイト 新着情報: https://example.com/7334.html

source:
  content_hash: "sha256-20afe127ea8e65a5"
  summary_method: "llm-haiku-4-5"
'''


def _write(text):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _with_llm(available, diff_fn):
    """_llm_available と diff_with_llm を差し替えるコンテキスト代わりのヘルパ."""
    mod._llm_available = lambda: available
    mod.diff_with_llm = diff_fn


def test_returns_none_when_llm_unavailable():
    path = _write(PREV_YAML)
    _with_llm(False, lambda t, p, b: "呼ばれてはいけない")
    try:
        assert mod._diff_line("市有地の売却", path, "本文" * 100) is None
    finally:
        os.remove(path)


def test_passes_stripped_prev_summary_to_llm():
    path = _write(PREV_YAML)
    seen = {}

    def fake(title, prev_summary, new_body):
        seen["title"] = title
        seen["prev"] = prev_summary
        seen["body"] = new_body
        return "入札日を 9/11 に再設定。"

    _with_llm(True, fake)
    try:
        got = mod._diff_line("市有地の売却", path, "新しい本文")
    finally:
        os.remove(path)
    assert got == "入札日を 9/11 に再設定。"
    # status 行 / disclaimer / 末尾 URL がすべて剥がれていること
    assert seen["prev"] == "入札日は令和8年6月19日です。"
    assert seen["title"] == "市有地の売却"
    assert seen["body"] == "新しい本文"


def test_skips_url_only_previous_generation():
    path = _write(PREV_YAML.replace('"llm-haiku-4-5"', '"url-only"'))
    _with_llm(True, lambda t, p, b: "呼ばれてはいけない")
    try:
        assert mod._diff_line("市有地の売却", path, "新しい本文") is None
    finally:
        os.remove(path)


def test_returns_none_when_llm_returns_empty():
    path = _write(PREV_YAML)
    _with_llm(True, lambda t, p, b: "")
    try:
        assert mod._diff_line("市有地の売却", path, "新しい本文") is None
    finally:
        os.remove(path)


def test_returns_none_when_llm_fails():
    path = _write(PREV_YAML)
    _with_llm(True, lambda t, p, b: None)
    try:
        assert mod._diff_line("市有地の売却", path, "新しい本文") is None
    finally:
        os.remove(path)


def test_returns_none_when_description_missing():
    path = _write('uid: "oshirase-7334@x"\nsource:\n  summary_method: "full"\n')
    _with_llm(True, lambda t, p, b: "呼ばれてはいけない")
    try:
        assert mod._diff_line("市有地の売却", path, "新しい本文") is None
    finally:
        os.remove(path)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all diff-line tests passed")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_diff_line.py`
Expected: FAIL — `AttributeError: module 'cal_oshirase_fetch' has no attribute '_diff_line'`

- [ ] **Step 3: import を足す**

`calendar/bin/cal-oshirase-fetch` の `from _lib import (...)` に 3 つ追加:

```python
from _lib import (
    USER_AGENT, UID_NAMESPACE, fetch, read_yaml_scalar, read_yaml_block,
    strip_status_header, split_description,
    yaml_escape_str, yaml_block_scalar, strip_html, normalize_body,
    strip_markdown, AI_DISCLAIMER_JP,
    output_path_for, find_existing_by_uid, load_source_config,
    load_http_cache, save_http_cache, fetch_with_cache, dtstart_from_last_modified,
)
```

- [ ] **Step 4: 差分要約の prompt と定数を追加**

`calendar/bin/cal-oshirase-fetch` の `LLM_SYSTEM_PROMPT` 定義の直後に追加:

```python
# 更新記事の「主な変更」1 行を作る設定。要約より短く、トークンも小さい。
DIFF_LLM_MAX_TOKENS = 256
DIFF_SYSTEM_PROMPT = """あなたは飯能市公式サイトのお知らせ記事が更新されたとき、市民向けカレンダーに「何が変わったか」を 1 行で示すアシスタントです。

これは自動パイプラインの一部で、あなたの出力はそのままカレンダーの予定欄に掲載されます。人間との対話ではありません。読者に質問する・追加情報を求める・作れない理由を説明する等の対話的応答は絶対にしないでください。

入力は 2 つです:
- 「前回の要約」: 前に掲載したときの**要約文**。元記事の全文ではなく、情報が落ちています。
- 「今回の本文」: 今の元記事の本文（全文）。

出力方針:
- 日本語で 1〜2 文、**全体で 120 字以内**。
- 「主な変更:」等のラベルは付けない。変更内容だけを書く。
- **前回の要約は要約であって全文ではありません。** 言い回しの違い、詳しさの違い、書き方の順序の違いは変更として報告しないでください。前回の要約に無い項目を「新設」「追加」と断定してはいけません（単に要約から漏れていただけの可能性があります）。
- 拾うべきは、市民の行動が変わる実質的な変更です: 日付・期間・時刻の変更、金額の変更、件数や区分の変更、申込方法や会場の変更、中止/延期/終了などのステータス変更。
- 確信を持って言える変更が無い場合は、**何も出力せず空文字を返してください**（推測で書かない）。
- Markdown 記法 (**太字**、# 見出し、- リスト等) は一切使わない。出力先は Google カレンダーの予定欄で literal 表示されます。
- 変更内容だけを返す。前置きや「以下が変更点です」等の説明は不要。
"""
```

- [ ] **Step 5: `diff_with_llm` と `_diff_line` を実装する**

`calendar/bin/cal-oshirase-fetch` の `summarize_with_llm` 定義の直後に追加:

```python
def diff_with_llm(title: str, prev_summary: str, new_body: str) -> str | None:
    """前回の要約と今回の本文を比較し「主な変更」の本文を返す。失敗/変更なしは None。"""
    if httpx is None:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    if not prev_summary.strip() or not new_body or len(new_body) < MIN_BODY_CHARS:
        # 安全装置: 材料が薄い状態で LLM を呼ばない (ハルシネーション防止)
        return None
    user = (f"# {title}\n\n"
            f"## 前回の要約\n\n{prev_summary}\n\n"
            f"## 今回の本文\n\n{new_body}")
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "max_tokens": DIFF_LLM_MAX_TOKENS,
                "system": DIFF_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        text = strip_markdown(data["content"][0]["text"].strip(), bullet="・")
        # 改行は status header を壊すので 1 行に畳む
        text = " ".join(text.split())
        return text or None
    except Exception as e:
        print(f"  WARN: LLM diff failed: {e}", file=sys.stderr)
        return None
```

`_llm_available()` 定義の直後に追加:

```python
def _diff_line(title: str, prev_path: str, new_body: str) -> str | None:
    """直前世代の YAML と今回の本文から「主な変更」1 行を作る。作れなければ None。

    比較材料は前世代の description (= 前回の LLM 要約)。元記事の本文は保存して
    いないため、旧要約 × 新本文の非対称な比較になる。誤検出の抑制は
    DIFF_SYSTEM_PROMPT 側で行う。
    """
    if not _llm_available():
        return None
    if _read_yaml_scalar(prev_path, "summary_method") == "url-only":
        return None          # 前世代は URL のみ = 比較材料が無い
    raw = read_yaml_block(prev_path, "description")
    if not raw:
        return None
    prev_summary, _url = split_description(strip_status_header(raw))
    if not prev_summary.strip():
        return None
    return diff_with_llm(title, prev_summary, new_body) or None
```

- [ ] **Step 6: テストを実行して通ることを確認**

Run: `python3 calendar/tests/test_diff_line.py`
Expected: PASS — `OK: all diff-line tests passed`

- [ ] **Step 7: incremental branch で status_header に差分行を足す**

`calendar/bin/cal-oshirase-fetch` の Task 4 Step 2 で書いた `if prev:` ブロックを置換:

```python
            prev = existing_gens.get(it["page_id"], [])
            if prev:
                prev_dtstart, prev_uid, prev_path, _prev_hash = prev[0]
                supersedes = prev_uid
                status_header = f"🔄 内容更新 (公開日: {publish_date} / 前回掲載: {prev_dtstart})"
                diff_line = _diff_line(it["title"], prev_path, body)
                if diff_line:
                    status_header = f"{status_header}\n主な変更: {diff_line}"
            else:
                supersedes = None
                status_header = f"🆕 新着掲載 (公開日: {publish_date})"
```

- [ ] **Step 8: 全テストを回す**

Run: `python3 calendar/tests/run-golden && python3 calendar/tests/test_diff_line.py && python3 calendar/tests/test_generation_index.py && python3 calendar/tests/test_description_parts.py && python3 calendar/tests/test_last_modified_dating.py && python3 calendar/tests/test_tourism_discovery.py`
Expected: すべて PASS。golden は `_llm_available()` が False なので差分行が出ず、Task 4 で作った golden と一致する

- [ ] **Step 9: Commit**

```bash
git add calendar/bin/cal-oshirase-fetch calendar/tests/test_diff_line.py
git commit -m "feat(oshirase): 更新イベントに LLM 生成の「主な変更」行を出す

前世代 YAML の description (= 前回の要約) と今回の本文を Claude Haiku に
比較させ、120 字以内の 1 行を status header に足す。元記事本文は保存しない。

旧要約は情報が落ちているため、prompt で「言い回しの違いを変更として報告しない」
「要約に無い項目を新設と断定しない」を明示して誤検出を抑える。
LLM 不可 / 前世代が url-only / 出力が空 のときは差分行を省いて degrade する。"
```

---

### Task 6: `--backfill-diff` で既存イベントに遡及適用する

**Files:**
- Modify: `calendar/bin/cal-oshirase-fetch` (ヘルパ 2 つ + `run_backfill_diff` + argparse + main の分岐)
- Create: `calendar/tests/test_backfill_rewrite.py`

**Interfaces:**
- Consumes: `_existing_generations()`, `_diff_line()`, `read_yaml_block()`, `extract_body()`, `fetch_with_cache()`
- Produces:
  - `_rewrite_status_header(path: str, new_header: str) -> bool`
  - `_insert_source_field(path: str, after_key: str, key: str, value: str) -> bool`
  - `run_backfill_diff(args) -> int`
  - CLI: `--backfill-diff`, `--since YYYY-MM-DD`

- [ ] **Step 1: 失敗するテストを書く**

Create `calendar/tests/test_backfill_rewrite.py`。

**注意: `DOC` の `description` ブロック内の「空行」は半角スペース 2 個の行**。
`test_rewrite_status_header_refuses_without_status_line` がこの文字列を
`.replace()` で消す前提なので、trailing whitespace が落ちると失敗する。

```python
#!/usr/bin/env python3
"""cal-oshirase-fetch の in-place 書き換えヘルパのユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_backfill_rewrite.py
"""
import importlib.machinery
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_oshirase_fetch",
                                              os.path.join(BIN, "cal-oshirase-fetch"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

DOC = '''uid: "oshirase-7334-497925@hanno.city.tecoli.com"
summary: "ℹ️ 市有地の売却"
dtstart: "2026-08-08"
description: |-
  \U0001f504 内容更新 (公開日: 2026-08-07)
  
  AI による要約 (正確な情報は元記事をご確認ください)
  
  本文です。

render:
  gcal:
    mode: single-allday

source:
  type: city-hanno-oshirase
  id: "7334"
  content_hash: "sha256-497925995081bafc"
  summary_method: "llm-haiku-4-5"
  publish_date: "2026-08-07"
'''


def _write(text=DOC):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_rewrite_status_header_single_to_two_lines():
    path = _write()
    ok = mod._rewrite_status_header(
        path, "🔄 内容更新 (公開日: 2026-08-07 / 前回掲載: 2026-05-01)\n主な変更: 入札日を変更。")
    text = _read(path)
    os.remove(path)
    assert ok is True
    assert "  🔄 内容更新 (公開日: 2026-08-07 / 前回掲載: 2026-05-01)\n" in text
    assert "  主な変更: 入札日を変更。\n" in text
    # 本文と disclaimer は無傷
    assert "  AI による要約 (正確な情報は元記事をご確認ください)\n" in text
    assert "  本文です。\n" in text
    # description ブロックの外は無傷
    assert "render:\n  gcal:\n    mode: single-allday\n" in text
    assert '  content_hash: "sha256-497925995081bafc"\n' in text


def test_rewrite_status_header_is_idempotent():
    path = _write()
    header = "🔄 内容更新 (公開日: 2026-08-07 / 前回掲載: 2026-05-01)"
    mod._rewrite_status_header(path, header)
    first = _read(path)
    mod._rewrite_status_header(path, header)
    second = _read(path)
    os.remove(path)
    assert first == second


def test_rewrite_status_header_refuses_without_status_line():
    path = _write(DOC.replace("  🔄 内容更新 (公開日: 2026-08-07)\n  \n", ""))
    ok = mod._rewrite_status_header(path, "🔄 新ヘッダ")
    os.remove(path)
    assert ok is False


def test_insert_source_field_after_publish_date():
    path = _write()
    ok = mod._insert_source_field(path, "publish_date", "supersedes",
                                  "oshirase-7334@hanno.city.tecoli.com")
    text = _read(path)
    os.remove(path)
    assert ok is True
    assert ('  publish_date: "2026-08-07"\n'
            '  supersedes: "oshirase-7334@hanno.city.tecoli.com"\n') in text


def test_insert_source_field_after_summary_method_when_no_publish_date():
    path = _write(DOC.replace('  publish_date: "2026-08-07"\n', ""))
    assert mod._insert_source_field(path, "publish_date", "supersedes", "x@y") is False
    ok = mod._insert_source_field(path, "summary_method", "supersedes", "x@y")
    text = _read(path)
    os.remove(path)
    assert ok is True
    assert '  summary_method: "llm-haiku-4-5"\n  supersedes: "x@y"\n' in text


def test_insert_source_field_skips_when_already_present():
    path = _write()
    mod._insert_source_field(path, "publish_date", "supersedes", "first@y")
    ok = mod._insert_source_field(path, "publish_date", "supersedes", "second@y")
    text = _read(path)
    os.remove(path)
    assert ok is False
    assert "first@y" in text
    assert "second@y" not in text


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all backfill-rewrite tests passed")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python3 calendar/tests/test_backfill_rewrite.py`
Expected: FAIL — `AttributeError: module 'cal_oshirase_fetch' has no attribute '_rewrite_status_header'`

- [ ] **Step 3: 書き換えヘルパを実装する**

`calendar/bin/cal-oshirase-fetch` の `_rewrite_yaml_scalar` 定義の直後に追加:

```python
def _rewrite_status_header(path: str, new_header: str) -> bool:
    """description ブロック冒頭の status ブロックを new_header で差し替える。

    status ブロックは 🆕/🔄/📝 で始まり最初の空行まで。--backfill-diff 用の
    最小限の in-place 編集で、要約本体・末尾 URL・translations ブロックには
    一切触れない。差し替えたら True。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
    except Exception:
        return False
    head = re.compile(r"^description:\s*\|[-+]?\s*$")
    start = next((i for i, ln in enumerate(lines) if head.match(ln)), None)
    if start is None:
        return False
    i = start + 1
    if i >= len(lines) or not lines[i].startswith("  ") or not lines[i][2:].startswith(STATUS_MARKERS):
        return False
    end = i
    while end < len(lines) and lines[end].strip() != "":
        end += 1
    lines[i:end] = ["  " + ln for ln in new_header.split("\n")]
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return True
    except Exception:
        return False


def _insert_source_field(path: str, after_key: str, key: str, value: str) -> bool:
    """source: ブロックの after_key 行の直後に `key: "value"` を挿入する。

    既に key がある / after_key が無い / 書込失敗 なら False。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
    except Exception:
        return False
    key_re = re.compile(r"^\s*" + re.escape(key) + r":\s")
    if any(key_re.match(ln) for ln in lines):
        return False
    anchor = re.compile(r"^(\s*)" + re.escape(after_key) + r":\s")
    for i, ln in enumerate(lines):
        m = anchor.match(ln)
        if not m:
            continue
        lines.insert(i + 1, f"{m.group(1)}{key}: {yaml_escape_str(value)}")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return True
        except Exception:
            return False
    return False
```

`STATUS_MARKERS` を import に足す（Task 5 Step 3 の import 文に追記）:

```python
from _lib import (
    USER_AGENT, UID_NAMESPACE, STATUS_MARKERS, fetch, read_yaml_scalar, read_yaml_block,
    strip_status_header, split_description,
    ...
)
```

- [ ] **Step 4: テストを実行して通ることを確認**

Run: `python3 calendar/tests/test_backfill_rewrite.py`
Expected: PASS — `OK: all backfill-rewrite tests passed`

- [ ] **Step 5: `run_backfill_diff` を実装する**

`calendar/bin/cal-oshirase-fetch` の `def main()` の直前に追加:

```python
def run_backfill_diff(args) -> int:
    """既存の「🔄 内容更新」イベントに、差分行と source.supersedes を後付けする。

    対象は dtstart >= args.since (既定 = 前日 = アプリの表示窓の下限) かつ
    直前世代が存在するもの。記事を再 fetch して旧要約と比較する。
    content_hash / uid / dtstart / ファイル名は変更しない。
    """
    since = args.since or (datetime.now(JST).date() - timedelta(days=1)).isoformat()
    gens = _existing_generations(args.out_dir, args.uid_prefix)
    n = 0
    for page_id in sorted(gens):
        chain = gens[page_id]
        for pos, (dtstart, uid, path, _ch) in enumerate(chain):
            if dtstart < since:
                continue
            if pos + 1 >= len(chain):
                continue                      # 前世代なし = 新着掲載
            desc = read_yaml_block(path, "description") or ""
            if not desc.startswith("🔄"):
                continue                      # 更新イベントではない
            prev_dtstart, prev_uid, prev_path, _ = chain[pos + 1]
            url = _read_yaml_scalar(path, "url")
            if not url or not safe_url(url):
                continue
            try:
                article_html, _etag, _lm = fetch_with_cache(url, None, None)
            except Exception as e:
                print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
                continue
            body = extract_body(article_html or "")
            publish_date = _read_yaml_scalar(path, "publish_date") or dtstart
            title = (_read_yaml_scalar(path, "summary") or "")
            if title.startswith(SUMMARY_PREFIX):
                title = title[len(SUMMARY_PREFIX):]
            header = f"🔄 内容更新 (公開日: {publish_date} / 前回掲載: {prev_dtstart})"
            diff_line = _diff_line(title, prev_path, body)
            if diff_line:
                header = f"{header}\n主な変更: {diff_line}"
            if args.dry_run:
                print(f"# === {path} ===")
                print(header)
                n += 1
                continue
            if not _rewrite_status_header(path, header):
                print(f"  WARN: status header not rewritten: {path}", file=sys.stderr)
                continue
            if not _insert_source_field(path, "publish_date", "supersedes", prev_uid):
                _insert_source_field(path, "summary_method", "supersedes", prev_uid)
            print(f"  BACKFILL {path}", file=sys.stderr)
            n += 1
    print(f"Done [backfill-diff]. files={n}  since={since}", file=sys.stderr)
    return 0
```

- [ ] **Step 6: CLI オプションと main の分岐を追加**

`calendar/bin/cal-oshirase-fetch` の argparse に追加（`--min-items` の直前）:

```python
    ap.add_argument("--backfill-diff", action="store_true",
                    help="既存の『🔄 内容更新』イベントに差分行と source.supersedes を"
                         "後付けする。記事を再 fetch するが content_hash / uid / dtstart は"
                         "変更しない。RSS フィードは見ない。")
    ap.add_argument("--since", default=None,
                    help="--backfill-diff の対象下限 dtstart (YYYY-MM-DD、既定: 前日)")
```

`args = ap.parse_args()` の直後に分岐を追加:

```python
    if args.backfill_diff:
        sys.exit(run_backfill_diff(args))
```

- [ ] **Step 7: dry-run で実データに対する挙動を確認（LLM なし）**

Run: `ANTHROPIC_API_KEY= python3 calendar/bin/cal-oshirase-fetch --backfill-diff --dry-run --since 2026-08-01`
Expected: 数件について `# === calendar/events/2026/… ===` と `🔄 内容更新 (公開日: … / 前回掲載: …)` が出る。`ANTHROPIC_API_KEY` が空なので `主な変更:` 行は出ない。ファイルは 1 つも変更されない。

Run: `git status --porcelain calendar/events/`
Expected: 空

- [ ] **Step 8: 全テストを回す**

Run: `python3 calendar/tests/run-golden && python3 calendar/tests/test_backfill_rewrite.py && python3 calendar/tests/test_diff_line.py && python3 calendar/tests/test_generation_index.py && python3 calendar/tests/test_description_parts.py && python3 calendar/tests/test_last_modified_dating.py && python3 calendar/tests/test_tourism_discovery.py`
Expected: すべて PASS

- [ ] **Step 9: Commit**

```bash
git add calendar/bin/cal-oshirase-fetch calendar/tests/test_backfill_rewrite.py
git commit -m "feat(oshirase): --backfill-diff で既存の更新イベントに差分行を後付け

対象は dtstart >= --since (既定 = 前日 = アプリ表示窓の下限) の
「🔄 内容更新」イベント。記事を再 fetch して旧要約と比較し、status header を
差し替えて source.supersedes を挿入する。content_hash / uid / dtstart /
ファイル名・要約本体・translations ブロックには触れない。"
```

---

### Task 7: README を更新し、遡及を実行して結果を確認する

**Files:**
- Modify: `calendar/README.md` (`## bin/cal-oshirase-fetch` セクション、`### イベント YAML の形式` 相当の箇所)
- Modify: `calendar/events/2026/*.yaml` (遡及実行の結果)

**Interfaces:**
- Consumes: Task 6 の `--backfill-diff`
- Produces: なし（最終タスク）

- [ ] **Step 1: README のクローラ説明を更新する**

`calendar/README.md` の `## bin/cal-oshirase-fetch` セクション、動作モードの説明の後に追記:

```markdown
### 世代リンクと差分要約 (incremental mode)

同じ `page_id` の記事が更新されると別 YAML が生成されるが、その YAML は
`source.supersedes` に**直前 1 世代の uid** を持つ。チェーンを辿れば全世代に到達する。

```yaml
source:
  id: "7334"
  publish_date: "2026-08-07"
  supersedes: "oshirase-7334@hanno.city.tecoli.com"
```

同一記事の全世代は `grep -rn 'id: "7334"' calendar/events/` で引ける。

`description` 冒頭の status header は更新時に 2 行になる:

```
🔄 内容更新 (公開日: 2026-08-07 / 前回掲載: 2026-05-01)
主な変更: 物件 A・B・C の個別入札を新設。入札日を 6/19 から 9/11 に再設定。
```

「主な変更」は**前世代の description (= 前回の LLM 要約) と今回の本文**を Claude Haiku に
比較させて生成する (`diff_with_llm`)。元記事の本文は保存していないため、旧要約 × 新本文の
非対称な比較になり、要約から漏れていた項目が「新規」に見える誤検出がありうる。
prompt 側で「言い回しの違いを変更として報告しない」「要約に無い項目を新設と断定しない」を
明示して抑えている。LLM 不可 / 前世代が `url-only` / 出力が空 のときは差分行を省く。

`supersedes` も status header も **`content_hash` には含めない**ので、既存 YAML の
hash は動かず、カレンダーが氾濫することはない。

既存イベントへの後付けは `--backfill-diff` (既定の `--since` は前日 = アプリ表示窓の下限):

```
cal-oshirase-fetch --backfill-diff [--since YYYY-MM-DD] [--dry-run]
```
```

- [ ] **Step 2: README の CLI 引数一覧を更新する**

`calendar/README.md` の `cal-oshirase-fetch [--out-dir events] ...` の usage 行に追加:

```
cal-oshirase-fetch [--out-dir events] [--once-per-page] [--refetch-existing]
                   [--rehash-only] [--backfill-diff] [--since YYYY-MM-DD]
                   [--dry-run] [--min-items 0]
```

- [ ] **Step 3: テスト (golden 網) セクションにシナリオを追記**

`calendar/README.md` の golden テスト説明に追記:

```markdown
golden シナリオは 3 本:

| golden dir | crawler | seed | 何を固定するか |
|---|---|---|---|
| `cal-oshirase-fetch` | oshirase | 無し | 新着掲載 (🆕) の出力 |
| `cal-oshirase-update` | oshirase | `seed/cal-oshirase-update/` | 既存 YAML がある状態での更新検知 (🔄 + `supersedes`) |
| `cal-shicho-blog-fetch` | shicho-blog | 無し | 市長ブログの出力 |

`seed/<name>/` を置くと、その中身が `--out-dir` に事前展開されてから crawler が走る
(= 既存 YAML がある状態の再現)。seed 自身も出力として golden に含まれる。
```

- [ ] **Step 4: README の変更をコミット**

```bash
git add calendar/README.md
git commit -m "docs(cal): oshirase の世代リンク・差分要約・backfill-diff を README に追記"
```

- [ ] **Step 5: 遡及を dry-run で確認する（LLM あり）**

`ANTHROPIC_API_KEY` を設定した状態で:

Run: `python3 calendar/bin/cal-oshirase-fetch --backfill-diff --dry-run`
Expected: 2 件程度（`08-07_oshirase-14121-ec86a7.yaml`, `08-08_oshirase-7334-497925.yaml` 相当。実行日によって変わる）について、`🔄 内容更新 (公開日: … / 前回掲載: …)` と `主な変更: …` が表示される。

**出力される「主な変更」を目視で確認すること。** 元記事と突き合わせて、言い回しの違いを変更として報告していないか、要約漏れを「新設」と断定していないかを見る。おかしければ `DIFF_SYSTEM_PROMPT` を調整して再実行する。

Run: `git status --porcelain calendar/events/`
Expected: 空（dry-run なので）

- [ ] **Step 6: 遡及を実行する**

Run: `python3 calendar/bin/cal-oshirase-fetch --backfill-diff`
Expected: `BACKFILL calendar/events/2026/…` が対象件数分出て、末尾に `Done [backfill-diff]. files=N`

Run: `git diff calendar/events/`
Expected: 各ファイルで以下だけが変わっていること。それ以外の行が動いていたらバグ。
- `description` 冒頭 1 行が `🔄 内容更新 (公開日: … / 前回掲載: …)` + `主な変更: …` の 2 行に
- `source:` ブロックに `supersedes: "…"` が 1 行追加

Run: `git diff calendar/events/ | grep -c "content_hash"`
Expected: `0` — `content_hash` は 1 つも変わっていないこと

- [ ] **Step 7: 英訳を更新する**

Run: `python3 calendar/bin/cal-translate-en --dry-run`
Expected: 遡及した 2 件だけが再翻訳対象として挙がる（`description` が変わって `translation_hash` が変わったため）

Run: `python3 calendar/bin/cal-translate-en`
Expected: 対象件数分が翻訳される

Run: `git diff calendar/events/ | grep "AI summary\|AI による要約"`
Expected: 英訳側の `description` から `AI summary (please check the original article…)` の**重複行が消えている**こと（`split_description` の `re.M` 修正の効果）

- [ ] **Step 8: Commit**

```bash
git add calendar/events/
git commit -m "calendar: 直近の更新イベントに差分行と supersedes を後付け

cal-oshirase-fetch --backfill-diff の実行結果 + 英訳更新。
content_hash / uid / dtstart は不変。"
```

- [ ] **Step 9: Calendar への反映を dry-run で確認する**

Run: `python3 calendar/bin/cal-myhanno apply-all --only-managed --dry-run`
Expected: 遡及した 2 件が `"action": "update"` として挙がる（`description` が変わったため drift 検出される）。それ以外のイベントが `update` になっていないこと。

**実際の反映は `cal-daily.yml` の次回実行に任せる。** ここで `apply-all` を本番実行しない。

---

## 完了条件

- [ ] `python3 calendar/tests/run-golden` が緑（3 シナリオすべて）
- [ ] `calendar/tests/test_*.py` がすべて緑
- [ ] `calendar/tests/golden/cal-oshirase-fetch/` が Task 1 開始時点から 1 バイトも変わっていない
- [ ] 遡及後の `calendar/events/` の diff に `content_hash` の変更が 1 つも無い
- [ ] `calendar/README.md` に世代リンク・差分要約・`--backfill-diff`・golden シナリオ表が載っている
