# 商工会議所 お知らせカレンダー Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 飯能商工会議所の告知 (`xo_event`) のうち検定を除く 4 カテゴリ・暦年 2026 分を取り込み、`cci` / `cci.en` の 2 カレンダーとして配信する。

**Architecture:** 既存の追記型クローラ (`cal-oshirase-fetch` / `cal-shicho-blog-fetch`) と同じ系統。WordPress REST API から一覧と本文を 1 リクエストで取得し、長文は Claude Haiku で要約する。同じ記事が更新されたら新 UID の別世代を作り `source.supersedes` で辿れるようにする。差分行の機械検算は既存の `drop_unchanged_claims()` を `_lib` へ移して共有する。

**Tech Stack:** Python 3 (標準ライブラリ + PyYAML + httpx)、Claude Haiku 4.5、`gws` (googleworkspace/cli)、GitHub Actions。

設計書: [`docs/superpowers/specs/2026-08-20-cci-event-calendar-design.md`](../specs/2026-08-20-cci-event-calendar-design.md)

## Global Constraints

- **`content_hash` は `title` + `date` + `body` のみ**から計算する。`summary_method` / `format_version` は**含めない**。含めると CI で `ANTHROPIC_API_KEY` が落ちた日に全件が「変化あり」判定になりカレンダーが氾濫する (2026-05-26 の実障害)
- **要約の閾値は既存と同じ** — `MIN_BODY_CHARS = 50` 未満は `url-only`、`FULL_TEXT_THRESHOLD = 400` 以下は `full`、超は `llm-haiku-4-5`。LLM 不可の環境では長文も `full` に落とす
- **UID 形式**: `cci-event-<post-id>-<hash6>@hanno.city.tecoli.com`。`<hash6>` は `content_hash` の先頭 6 文字
- **取り込み対象**: `xo_event_cat` = 7 (お知らせ) / 20 (セミナー) / 10 (経営支援) / 8 (地域振興)。**9 (検定) は除外**
- **期間**: `after=2026-01-01T00:00:00`
- **`source:` を持たない YAML (手動キュレーション) には絶対に触れない**
- **既存 5 カレンダーの挙動を変えない**
- カレンダー ID (作成済み):
  - `cci` = `b0a56c8e1f5246cda41e2fdb3c449b20c50bb365aac92333a4a9290a21e7edcf@group.calendar.google.com`
  - `cci.en` = `b932613ee11b3b16657b986a7ec1bd82ad7c385c30de75a2db5834ba1a297e32@group.calendar.google.com`
- テストは既存慣習に従う: `python3 calendar/tests/test_xxx.py` で自己実行、末尾に `if __name__ == "__main__":` の runner

---

## File Structure

| ファイル | 責務 |
|---|---|
| `calendar/bin/_lib.py` (変更) | `drop_unchanged_claims()` / `_CLAIM_RE` / `_claim_value_key()` を `cal-oshirase-fetch` から移設 |
| `calendar/bin/cal-oshirase-fetch` (変更) | 上記を `_lib` から import する形へ。ロジックは変えない |
| `calendar/bin/cal-cci-event-fetch` (新規) | REST 取得・本文整形・要約・世代管理・YAML 生成 |
| `calendar/bin/cal-myhanno` (変更) | `CALENDARS` に `cci` / `cci.en`、`SOURCE_TYPE_TO_CALENDAR` に `hanno-cci-event` |
| `calendar/sources.yaml` (変更) | `cci-event` セクション |
| `calendar/tests/test_diff_verify.py` (変更) | `_lib` 参照へ書き換え |
| `calendar/tests/test_cci_event.py` (新規) | カテゴリ prefix / 本文整形 / content_hash の不変性 |
| `calendar/tests/fixtures/cal-cci-event-fetch/` (新規) | REST レスポンス JSON + manifest |
| `calendar/tests/seed/cal-cci-event-update/` (新規) | 更新検知シナリオ用の既存 YAML |
| `calendar/tests/golden/cal-cci-event-*/` (新規) | 期待出力 |
| `calendar/tests/run-golden` (変更) | `CRAWLERS` に 2 シナリオ |
| `.github/workflows/cal-daily.yml` (変更) | crawl ステップ |
| `README.md` / `calendar/README.md` (変更) | 新カレンダーと新クローラの説明 |

---

### Task 1: 機械検算を `_lib` へ移設して共有する

差分行を作るクローラが 2 本になるので、`drop_unchanged_claims()` を共有する。
片方にだけ置いてコピーすると、後日片方だけ直る事故が起きる。

**Files:**
- Modify: `calendar/bin/_lib.py` (末尾の集合同期セクションの直前に追加)
- Modify: `calendar/bin/cal-oshirase-fetch` (定義を削除し import に変更)
- Modify: `calendar/tests/test_diff_verify.py` (読み込み先を `_lib` に)

**Interfaces:**
- Consumes: `_lib.normalize_char_width`
- Produces: `_lib.drop_unchanged_claims(text: str | None) -> str | None`

- [ ] **Step 1: テストの読み込み先を `_lib` に変える (失敗させる)**

`calendar/tests/test_diff_verify.py` の冒頭を差し替える:

```python
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "_lib.py")
loader = importlib.machinery.SourceFileLoader("_lib", SCRIPT)
spec = importlib.util.spec_from_loader("_lib", loader)
lib = importlib.util.module_from_spec(spec)
loader.exec_module(lib)

drop = lib.drop_unchanged_claims
```

docstring も「`cal-oshirase-fetch` の」→「`_lib` の (差分行を作る全クローラが共有)」に変える。

- [ ] **Step 2: 失敗を確認**

Run: `python3 calendar/tests/test_diff_verify.py`
Expected: FAIL — `AttributeError: module '_lib' has no attribute 'drop_unchanged_claims'`

- [ ] **Step 3: `_lib.py` へ移設**

`calendar/bin/_lib.py` の `# ==================== 集合同期 (schedule set sync) ====================`
の直前に、以下をそのまま追加する (`cal-oshirase-fetch` からの移設):

```python
# ==================== LLM 出力の機械検算 ====================
# 「〜から〜に」の対。左辺は「値」の maximal な token を取るため、直前が数字・
# カンマでないことを要求する (負の後読み)。これが無いと「1,970万円から970万円に」
# の左辺から "970万円" だけを切り出してしまい、真の変更を同値と誤判定する。
_CLAIM_RE = re.compile(
    r"(?<![0-9０-９,，])([0-9０-９][0-9０-９,，.．]*[^\s、。]{0,6}?)から"
    r"([0-9０-９][0-9０-９,，.．]*[^\s、。]{0,6}?)に")


def _claim_value_key(s: str) -> str:
    """同値判定用の正規化キー。全角/半角とカンマの差を吸収する。"""
    return normalize_char_width(s).replace(",", "").replace("，", "").strip()


def drop_unchanged_claims(text: str | None) -> str | None:
    """「A から A に変更されました」という同値の主張を落とす (機械検算).

    LLM は変更を説明させられると、名指しできる変更が無い場面でも手元の値で型を
    埋めてしまうことがある。プロンプトで明示的に禁じ temperature=0 にしても
    発生した (2026-08-19 本番: 4 対すべて同値の「主な変更」が出た) ため、
    生成後にコード側で検査する。プロンプトを強める方向では再発する。

    単位は **文** (`。` 区切り)。同値の対を 1 つでも含む文は、その文の生成が
    信用できない証拠なので丸ごと捨てる (節だけ削ると日本語が壊れる)。真の変更を
    述べた別の文は残す。全部落ちたら None = 「主な変更」行を出さない。

    検出は数値を伴う対に限る。非数値の同値 (「会場が A から A に」) も理屈上
    ありえるが、緩いパターンは真の変更通知を誤って削除する危険がある。観測された
    失敗は数値であり、そこだけを確実に止める。

    差分行を作るクローラが複数あるので _lib に置く。片方にだけ置くと、後日
    片方だけ直る事故が起きる。
    """
    if not text or not text.strip():
        return None

    kept: list[str] = []
    for sentence in re.split(r"(?<=。)", text):
        if not sentence.strip():
            continue
        pairs = _CLAIM_RE.findall(sentence)
        if any(_claim_value_key(a) == _claim_value_key(b) for a, b in pairs):
            continue     # 同値を含む = この文は信用できない
        kept.append(sentence)

    out = "".join(kept).strip()
    return out or None
```

- [ ] **Step 4: `cal-oshirase-fetch` から定義を削除して import に変える**

`_CLAIM_RE` / `_claim_value_key` / `drop_unchanged_claims` の 3 つの定義を削除する
(`diff_with_llm` の直前にある)。`from _lib import (...)` に `drop_unchanged_claims`
を足し、`normalize_char_width` は使わなくなるなら外す。

`diff_with_llm` 末尾の呼び出しはそのまま残す:

```python
    line = " ".join(text.split()) or None
    # 生成後の機械検算。プロンプトで禁じても「A から A に変更」が出るため
    # (_lib.drop_unchanged_claims の docstring 参照)、コード側で最後に止める。
    return drop_unchanged_claims(line)
```

プロンプト末尾の注記も `drop_unchanged_claims()` → `_lib.drop_unchanged_claims()`
に直す。

- [ ] **Step 5: テストが通ることを確認**

Run: `python3 calendar/tests/test_diff_verify.py`
Expected: `OK: all diff-verify tests passed`

- [ ] **Step 6: 全体が壊れていないことを確認**

Run: `python3 calendar/tests/run-golden`
Expected: `All golden checks passed.`

`cal-oshirase-fetch` が読み込めることも確認する:

Run: `python3 -c "import importlib.machinery,importlib.util as u; l=importlib.machinery.SourceFileLoader('m','calendar/bin/cal-oshirase-fetch'); s=u.spec_from_loader('m',l); m=u.module_from_spec(s); l.exec_module(m); print('ok', m.drop_unchanged_claims('料金が1,000円から1,000円に変更されました。'))"`
Expected: `ok None`

- [ ] **Step 7: コミット**

```bash
git add calendar/bin/_lib.py calendar/bin/cal-oshirase-fetch calendar/tests/test_diff_verify.py
git commit -m "refactor(calendar): 機械検算 drop_unchanged_claims を _lib へ移設"
```

---

### Task 2: REST 取得とカテゴリ prefix

ネットワークを触らない純粋関数だけを先に作る。

**Files:**
- Create: `calendar/bin/cal-cci-event-fetch`
- Create: `calendar/tests/test_cci_event.py`

**Interfaces:**
- Consumes: `_lib.strip_html`, `_lib.normalize_body`
- Produces (module scope):
  - `CATEGORIES: dict[int, str]` — `{7: "お知らせ", 20: "セミナー", 10: "経営支援", 8: "地域振興"}`
  - `CATEGORY_PREFIX: dict[str, str]`
  - `summary_for(title: str, cat_ids: list[int]) -> str`
  - `body_from_post(post: dict) -> str`
  - `content_hash_for(title: str, date: str, body: str) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`calendar/tests/test_cci_event.py`:

```python
#!/usr/bin/env python3
"""cal-cci-event-fetch の純粋関数のユニットテスト。
実行: python3 calendar/tests/test_cci_event.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_cci_event_fetch",
                                              os.path.join(BIN, "cal-cci-event-fetch"))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


def test_category_prefix_by_id():
    assert m.summary_for("補助金の募集", [20]) == "🎓 補助金の募集"
    assert m.summary_for("夏季休業日のお知らせ", [7]) == "ℹ️ 夏季休業日のお知らせ"
    assert m.summary_for("専門家相談の日程", [10]) == "💼 専門家相談の日程"
    assert m.summary_for("はんのう元気市", [8]) == "🏮 はんのう元気市"


def test_unknown_category_gets_no_prefix():
    # 検定 (9) 等、対象外のカテゴリしか持たない記事は prefix 無し。
    # そもそも取得対象外だが、防御的に素通りさせる。
    assert m.summary_for("簿記検定の結果", [9]) == "簿記検定の結果"
    assert m.summary_for("カテゴリ無し", []) == "カテゴリ無し"


def test_first_known_category_wins():
    # 複数カテゴリが付いた記事は CATEGORIES の定義順で最初に一致したものを使う
    got = m.summary_for("複合記事", [9, 8])
    assert got == "🏮 複合記事", got


def test_body_strips_html_entities_and_tags():
    post = {"content": {"rendered": "<p>８月14日は<strong>休業</strong>します。</p>\n<p>&amp; 追記</p>"}}
    got = m.body_from_post(post)
    assert "<p>" not in got, got
    assert "&amp;" not in got, got
    assert "休業" in got, got
    assert "& 追記" in got, got


def test_content_hash_ignores_summary_method():
    # content_hash は title + date + body のみ。要約方式を変えても動かない
    # (2026-05-26 の flood 障害の回帰テスト)。
    a = m.content_hash_for("題", "2026-08-11", "本文")
    b = m.content_hash_for("題", "2026-08-11", "本文")
    assert a == b
    assert a != m.content_hash_for("題", "2026-08-11", "別の本文")
    assert a != m.content_hash_for("別の題", "2026-08-11", "本文")
    assert a != m.content_hash_for("題", "2026-08-12", "本文")
    assert len(a) == 16, a


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all cci-event tests passed")
```

- [ ] **Step 2: 失敗を確認**

Run: `python3 calendar/tests/test_cci_event.py`
Expected: FAIL — ファイルが存在しない

- [ ] **Step 3: クローラの骨格を作る**

`calendar/bin/cal-cci-event-fetch`:

```python
#!/usr/bin/env python3
"""cal-cci-event-fetch — 飯能商工会議所の告知 (xo_event) を YAML 化。

Source: https://www.hanno-cci.or.jp/wp-json/wp/v2/xo_event

WordPress REST API。一覧レスポンスに content.rendered が含まれるので、
記事ごとの個別 fetch は不要 (1 リクエストで本文まで来る)。

**開催日は取れない。** XO Event Calendar は開催日を postmeta に持つが REST は
meta を公開しておらず、admin-ajax の月グリッドもイベントを返さない。したがって
dtstart は掲載日 (post date) になる。

追記型クローラ (集合同期型ではない)。設計:
docs/superpowers/specs/2026-08-20-cci-event-calendar-design.md
"""
from __future__ import annotations

import argparse
import hashlib
import html as _html
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (  # noqa: E402
    USER_AGENT, UID_NAMESPACE, strip_html, normalize_body,
    yaml_escape_str, yaml_block_scalar, load_source_config,
)


SOURCE_KEY = "cci-event"

# 取り込むカテゴリ (xo_event_cat の term id)。**9 (検定) は除外**:
# 大半が合格者番号発表で、掲載日に載せても「その日に何かが起きる」わけではない。
# dict の順序が「複数カテゴリが付いた記事でどれを採るか」の優先順位になる。
CATEGORIES: dict[int, str] = {
    8:  "地域振興",
    20: "セミナー",
    10: "経営支援",
    7:  "お知らせ",
}

# 1 カレンダーに 4 系統が混ざるので識別子を付ける
# (既存クローラの 📢/🎪/ℹ️/📝 と同じ役割)。
CATEGORY_PREFIX: dict[str, str] = {
    "お知らせ":   "ℹ️ ",
    "セミナー":   "🎓 ",
    "経営支援":   "💼 ",
    "地域振興":   "🏮 ",
}


def category_of(cat_ids: list[int]) -> str | None:
    """記事のカテゴリ名を返す。対象外しか無ければ None。

    複数付いている場合は CATEGORIES の定義順で最初に一致したものを採る。
    """
    for cid in CATEGORIES:
        if cid in cat_ids:
            return CATEGORIES[cid]
    return None


def summary_for(title: str, cat_ids: list[int]) -> str:
    """カテゴリ別の絵文字 prefix を付けた summary."""
    cat = category_of(cat_ids)
    prefix = CATEGORY_PREFIX.get(cat, "") if cat else ""
    return f"{prefix}{title}"


def body_from_post(post: dict) -> str:
    """content.rendered を平文へ整形する."""
    raw = (post.get("content") or {}).get("rendered") or ""
    return normalize_body(strip_html(_html.unescape(raw)))


def content_hash_for(title: str, date: str, body: str) -> str:
    """コンテンツ identity の hash (= title + date + body のみ).

    **summary_method / format_version は意図的に含めない。** rendering の選択で
    あって content の identity ではない。含めると CI で ANTHROPIC_API_KEY が
    落ちた日に全件が「変化あり」判定になりカレンダーが氾濫する
    (2026-05-26 の実障害。cal-oshirase-fetch のコメントが正典)。
    """
    canonical = json.dumps({"title": title, "date": date, "body": body},
                           ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: 実行権限を付けてテスト**

Run: `chmod +x calendar/bin/cal-cci-event-fetch && python3 calendar/tests/test_cci_event.py`
Expected: `OK: all cci-event tests passed`

- [ ] **Step 5: 実データで目視確認**

Run:
```bash
python3 - <<'EOF'
import importlib.machinery, importlib.util as u, json, urllib.request
l = importlib.machinery.SourceFileLoader('m', 'calendar/bin/cal-cci-event-fetch')
s = u.spec_from_loader('m', l); m = u.module_from_spec(s); l.exec_module(m)
url = ('https://www.hanno-cci.or.jp/wp-json/wp/v2/xo_event'
       '?per_page=5&after=2026-01-01T00:00:00&_fields=id,date,title,content,xo_event_cat')
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
for p in json.load(urllib.request.urlopen(req)):
    s_ = m.summary_for(p['title']['rendered'], p['xo_event_cat'])
    b = m.body_from_post(p)
    print(p['date'][:10], '|', s_[:44], '|', len(b), '字')
EOF
```
Expected: 各行に絵文字 prefix が付き、本文の字数が出る

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/cal-cci-event-fetch calendar/tests/test_cci_event.py
git commit -m "feat(calendar): 商工会議所 xo_event のカテゴリ判定と本文整形"
```

---

### Task 3: 取得・要約・世代管理・main

**Files:**
- Modify: `calendar/bin/cal-cci-event-fetch`
- Modify: `calendar/sources.yaml`

**Interfaces:**
- Consumes: Task 2 の `summary_for` / `body_from_post` / `content_hash_for`、`_lib.call_llm`, `_lib.llm_available`, `_lib.drop_unchanged_claims`
- Produces: `fetch_posts(cfg) -> list[dict]`, `build_yaml_doc(...) -> str`, `main()`

- [ ] **Step 1: `sources.yaml` に設定を足す**

末尾に追加:

```yaml
# 飯能商工会議所の告知 (xo_event 投稿タイプ)。追記型。
# 開催日は REST に出てこない (meta 非公開) ので dtstart は掲載日。
cci-event:
  uid_prefix: cci-event
  source_type: hanno-cci-event
  api_url: "https://www.hanno-cci.or.jp/wp-json/wp/v2/xo_event"
  site_url: "https://www.hanno-cci.or.jp/"
  location: "飯能商工会議所"
  url_host_allowlist: www.hanno-cci.or.jp
  url_path_prefix: "/xo_event/"
  after: "2026-01-01T00:00:00"
  # 取り込むカテゴリ (term id)。9 (検定) は除外。
  category_ids: [8, 20, 10, 7]
```

- [ ] **Step 2: 取得と YAML 生成を実装**

`calendar/bin/cal-cci-event-fetch` の末尾に追加。`from _lib import` に
`call_llm, llm_available, drop_unchanged_claims, fetch_with_cache,
load_http_cache, save_http_cache, output_path_for, read_yaml_scalar,
read_yaml_block, strip_status_header, AI_DISCLAIMER_JP` を足す。

```python
MIN_BODY_CHARS = 50          # これ未満なら url-only
FULL_TEXT_THRESHOLD = 400    # これ以下は全文、超は LLM 要約 (cal-oshirase-fetch と同値)
LLM_MODEL = "claude-haiku-4-5"

SUMMARY_SYSTEM_PROMPT = """あなたは飯能商工会議所の告知を、Google カレンダーの予定欄に収まる日本語要約にします。

- 全体で 200〜400 字程度。
- 事業者・市民が行動を決めるのに要る情報を優先: 日付・期間・締切、場所、費用、対象、申込方法。
- 本文に無いことは書かない。推測しない。
- Markdown 記法は使わない (literal 表示されるため)。
- 要約だけを返す。前置きは不要。
"""


def _llm_available() -> bool:
    """run-golden がこの名前を差し替えて LLM 経路を断つので薄いラッパで残す。"""
    return llm_available()


def summarize(title: str, body: str) -> str | None:
    user = f"# {title}\n\n{body}"
    return call_llm(SUMMARY_SYSTEM_PROMPT, user, model=LLM_MODEL, max_tokens=1024)


def fetch_posts(cfg: dict) -> list[dict]:
    """対象カテゴリの記事を新しい順に取得する (ページング込み)。"""
    posts: list[dict] = []
    page = 1
    while True:
        q = urllib.parse.urlencode({
            "per_page": 100,
            "page": page,
            "after": cfg["after"],
            "xo_event_cat": ",".join(str(c) for c in cfg["category_ids"]),
            "_fields": "id,date,modified_gmt,link,title,content,xo_event_cat",
        })
        # 注: modified_gmt による politeness は入れない。REST の一覧が本文まで
        # 含めて 1 リクエストで返るので、記事ごとの再取得が発生しない。再書き込みの
        # 抑制は content_hash の一致判定で足りる (設計書 §8 の「2 段の判定」のうち、
        # 実際に必要なのは content_hash 側だけ)。
        req = urllib.request.Request(f"{cfg['api_url']}?{q}",
                                     headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req) as r:
                batch = json.load(r)
        except Exception as e:
            print(f"  ERROR fetching page {page}: {e}", file=sys.stderr)
            break
        if not batch:
            break
        posts.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return posts


def build_yaml_doc(uid: str, post: dict, cfg: dict, description: str,
                   method: str, content_hash: str,
                   supersedes: str | None) -> str:
    date_str = post["date"][:10]
    lines = [
        f"uid: {yaml_escape_str(uid)}",
        f"summary: {yaml_escape_str(summary_for(post['title']['rendered'], post['xo_event_cat']))}",
        f"location: {yaml_escape_str(cfg['location'])}",
        f"url: {yaml_escape_str(post['link'])}",
        f"dtstart: {yaml_escape_str(date_str)}",
        f"dtend: {yaml_escape_str(date_str)}",
        "description: " + yaml_block_scalar(description, indent=2),
        "",
        "render:",
        "  gcal:",
        "    mode: single-allday",
        "",
        "source:",
        f"  type: {cfg['source_type']}",
        f"  id: {yaml_escape_str(str(post['id']))}",
        f"  url: {yaml_escape_str(post['link'])}",
        f"  category: {yaml_escape_str(category_of(post['xo_event_cat']) or '')}",
        f"  summary_method: {yaml_escape_str(method)}",
        f"  content_hash: {yaml_escape_str('sha256-' + content_hash)}",
    ]
    if supersedes:
        lines.append(f"  supersedes: {yaml_escape_str(supersedes)}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 3: main を実装**

同ファイルの末尾に追加:

```python
def _existing_by_page_id(out_dir: str, uid_prefix: str) -> dict[str, list[tuple[str, str]]]:
    """{page_id: [(content_hash, uid), ...]} を返す (世代判定用)。"""
    import glob
    found: dict[str, list[tuple[str, str]]] = {}
    for path in glob.glob(os.path.join(out_dir, "**", "*.yaml"), recursive=True):
        uid = read_yaml_scalar(path, "uid")
        if not uid or not uid.startswith(f"{uid_prefix}-"):
            continue
        pid = read_yaml_scalar(path, "id")
        ch = (read_yaml_scalar(path, "content_hash") or "").replace("sha256-", "")
        if pid:
            found.setdefault(pid, []).append((ch, uid))
    return found


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    default_out_dir = os.path.join(here, "..", "events")
    cfg = load_source_config(SOURCE_KEY)

    ap = argparse.ArgumentParser(description="飯能商工会議所 xo_event → YAML")
    ap.add_argument("--out-dir", default=default_out_dir)
    ap.add_argument("--uid-prefix", default=cfg["uid_prefix"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-items", type=int, default=0,
                    help="取得件数がこれ未満なら exit 2 (CI 暴走防止)")
    args = ap.parse_args()

    posts = fetch_posts(cfg)
    print(f"Fetched {len(posts)} posts", file=sys.stderr)
    if len(posts) < args.min_items:
        sys.exit(f"only {len(posts)} posts (< --min-items {args.min_items})")

    existing = _existing_by_page_id(args.out_dir, args.uid_prefix)
    written = skipped = 0

    for post in posts:
        title = post["title"]["rendered"]
        date_str = post["date"][:10]
        body = body_from_post(post)
        ch = content_hash_for(title, date_str, body)
        pid = str(post["id"])

        gens = existing.get(pid, [])
        if any(h == ch for h, _ in gens):
            skipped += 1
            continue                       # 同内容の世代が既にある

        if not body or len(body) < MIN_BODY_CHARS:
            method, text = "url-only", ""
        elif len(body) <= FULL_TEXT_THRESHOLD:
            method, text = "full", body
        elif _llm_available():
            s = summarize(title, body)
            if s:
                method, text = "llm-haiku-4-5", f"{AI_DISCLAIMER_JP}\n\n{s}"
            else:
                method, text = "full", body
        else:
            # LLM 不可の環境では長文も full。method を full にしておけば
            # content_hash は変わらない (hash に method を含めないため)。
            method, text = "full", body

        supersedes = gens[-1][1] if gens else None
        parts = [text] if text else []
        if supersedes:
            parts.insert(0, "🔄 内容更新")
        parts.append(post["link"])
        description = "\n\n".join(parts)

        uid = f"{args.uid_prefix}-{pid}-{ch[:6]}@{UID_NAMESPACE}"
        doc = build_yaml_doc(uid, post, cfg, description, method, ch, supersedes)
        out_path = output_path_for(args.out_dir, uid, date_str)

        if args.dry_run:
            written += 1
            continue
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(doc)
        written += 1

    print(f"Done. written={written} skipped={skipped}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: dry-run で件数を確認**

Run: `./calendar/bin/cal-cci-event-fetch --out-dir /tmp/cci-dry --dry-run`
Expected: `Fetched 49 posts` 前後、`written=49`

- [ ] **Step 5: 実際に生成して 1 件を目視**

Run:
```bash
./calendar/bin/cal-cci-event-fetch --out-dir /tmp/cci-out
ls /tmp/cci-out/2026 | head -3
cat "/tmp/cci-out/2026/$(ls /tmp/cci-out/2026 | head -1)"
```
Expected: `summary` に絵文字 prefix、`source.category` が入っている

- [ ] **Step 6: 冪等性を確認**

Run: `./calendar/bin/cal-cci-event-fetch --out-dir /tmp/cci-out`
Expected: `written=0 skipped=49`

- [ ] **Step 7: コミット**

```bash
git add calendar/bin/cal-cci-event-fetch calendar/sources.yaml
git commit -m "feat(calendar): 商工会議所 xo_event の取得・要約・世代管理"
```

---

### Task 4: 差分行「主な変更」

設計書 §6 の要求。同じ記事が更新されたとき、前世代の description と今回の本文を
Claude Haiku に比較させて差分行を作り、`description` 冒頭に置く。生成後に
`_lib.drop_unchanged_claims()` で機械検算する。

**Files:**
- Modify: `calendar/bin/cal-cci-event-fetch`

**Interfaces:**
- Consumes: Task 1 の `_lib.drop_unchanged_claims`、`_lib.call_llm`、
  `_lib.read_yaml_block`、`_lib.strip_status_header`
- Produces: `diff_line(title: str, prev_path: str, new_body: str) -> str | None`

- [ ] **Step 1: 差分プロンプトと関数を実装**

`cal-cci-event-fetch` の `summarize()` の後に追加:

```python
DIFF_SYSTEM_PROMPT = """あなたは飯能商工会議所の告知が更新されたとき、何が変わったかを 1 行で述べます。

- 日本語で 1〜2 文、全体で 120 字以内。ラベルは付けず変更内容だけを書く。
- **前回の要約は要約であって全文ではありません。** 言い回しや詳しさの違いを変更として報告しないでください。
- **「〜が〜に変更されました」と書いてよいのは、前回の要約に *異なる値* がはっきり書かれている場合だけです。** 同じ値なら変更ではありません。
- 拾うべきは行動が変わる変更です: 日付・期間・締切、金額、会場、申込方法、中止/延期。
- 確信を持って言える変更が無い場合は、何も出力せず空文字を返してください。
- Markdown 記法は使わない。
"""
# 注意: 上の制約はこの指示だけでは守られない。temperature=0 でも同値の対を書く
# 事例が本番で出た (2026-08-19、cal-oshirase-fetch)。**プロンプトを強める方向で
# 直そうとしないこと** — 最終的な保証は _lib.drop_unchanged_claims() にある。


def diff_line(title: str, prev_path: str, new_body: str) -> str | None:
    """前世代の description と今回の本文から差分行を作る。作れなければ None。

    比較材料は前世代の description (= 前回の要約または全文)。元記事の本文は
    保存していないため非対称な比較になる。誤検出は生成後の機械検算で止める。
    """
    if not _llm_available():
        return None
    raw = read_yaml_block(prev_path, "description")
    if not raw:
        return None
    prev = strip_status_header(raw).strip()
    if not prev or not new_body or len(new_body) < MIN_BODY_CHARS:
        return None
    user = (f"# {title}\n\n## 前回の掲載内容\n\n{prev}\n\n"
            f"## 今回の本文\n\n{new_body}")
    text = call_llm(DIFF_SYSTEM_PROMPT, user, model=LLM_MODEL,
                    max_tokens=512, temperature=0)
    if text is None:
        return None
    line = " ".join(text.split()) or None
    return drop_unchanged_claims(line)
```

- [ ] **Step 2: `_existing_by_page_id` が path も返すようにする**

差分行を作るには前世代の**ファイルパス**が要る。Task 3 で書いた関数の戻り値を
`{page_id: [(content_hash, uid, path), ...]}` に変える:

```python
def _existing_by_page_id(out_dir: str, uid_prefix: str) -> dict[str, list[tuple[str, str, str]]]:
    """{page_id: [(content_hash, uid, path), ...]} を返す (世代判定用)。"""
    import glob
    found: dict[str, list[tuple[str, str, str]]] = {}
    for path in sorted(glob.glob(os.path.join(out_dir, "**", "*.yaml"), recursive=True)):
        uid = read_yaml_scalar(path, "uid")
        if not uid or not uid.startswith(f"{uid_prefix}-"):
            continue
        pid = read_yaml_scalar(path, "id")
        ch = (read_yaml_scalar(path, "content_hash") or "").replace("sha256-", "")
        if pid:
            found.setdefault(pid, []).append((ch, uid, path))
    return found
```

`main()` 内の 2 箇所を合わせる:

```python
        if any(h == ch for h, _, _ in gens):
            skipped += 1
            continue
```

```python
        supersedes = gens[-1][1] if gens else None
        prev_path = gens[-1][2] if gens else None
```

- [ ] **Step 3: description の組み立てに差分行を入れる**

`main()` の description 組み立てを差し替える:

```python
        parts = [text] if text else []
        if supersedes:
            header = "🔄 内容更新"
            dl = diff_line(title, prev_path, body) if prev_path else None
            if dl:
                header += f"\n主な変更: {dl}"
            parts.insert(0, header)
        parts.append(post["link"])
        description = "\n\n".join(parts)
```

- [ ] **Step 4: 差分行の経路を実データで確認**

`ANTHROPIC_API_KEY` が要る。前世代を仕込んで 2 回走らせる:

```bash
export ANTHROPIC_API_KEY=...   # 未設定なら差分行は出ない (None) ので確認にならない
rm -rf /tmp/cci-diff && ./calendar/bin/cal-cci-event-fetch --out-dir /tmp/cci-diff
# 1 件の content_hash を壊して「更新された」状態を作る
F=$(ls /tmp/cci-diff/2026/*.yaml | head -1)
sed -i '' 's/^  content_hash: .*/  content_hash: "sha256-0000000000000000"/' "$F"
./calendar/bin/cal-cci-event-fetch --out-dir /tmp/cci-diff
grep -l supersedes /tmp/cci-diff/2026/*.yaml
```
Expected: `written=1`、`supersedes` を持つ YAML が 1 つできる。その
`description` 冒頭に `🔄 内容更新` があり、差分行が出るか出ないかは LLM 次第
(**内容が実際には変わっていないので、出ないのが正しい**)。

- [ ] **Step 5: 機械検算が繋がっていることを確認**

Run:
```bash
python3 -c "
import importlib.machinery, importlib.util as u
l = importlib.machinery.SourceFileLoader('m','calendar/bin/cal-cci-event-fetch')
s = u.spec_from_loader('m', l); m = u.module_from_spec(s); l.exec_module(m)
print(m.drop_unchanged_claims('料金が1,000円から1,000円に変更されました。'))
print(m.drop_unchanged_claims('料金が1,000円から2,000円に変更されました。'))
"
```
Expected: `None` / `料金が1,000円から2,000円に変更されました。`

- [ ] **Step 6: コミット**

```bash
git add calendar/bin/cal-cci-event-fetch
git commit -m "feat(calendar): 商工会議所クローラに差分行と機械検算を追加"
```

---

### Task 5: golden テスト

**Files:**
- Create: `calendar/tests/fixtures/cal-cci-event-fetch/{api-page1.json,manifest.json}`
- Create: `calendar/tests/seed/cal-cci-event-update/`
- Modify: `calendar/tests/run-golden`

**Interfaces:**
- Consumes: Task 3 の `fetch_posts` / `main`、Task 4 の `diff_line`
- Produces: golden 2 シナリオ

golden では `_llm_available()` を `False` に固定するので、**要約も差分行も
LLM を通りません**。長文は `method=full` になり、差分行は `None` になります。
`content_hash` に `method` を含めない設計なので hash は動かず、決定論的に
比較できます。差分行の生成そのものは非決定的なので golden では見ません
(`drop_unchanged_claims` の挙動は `tests/test_diff_verify.py` が見ています)。

- [ ] **Step 1: fixture を採取**

```bash
mkdir -p calendar/tests/fixtures/cal-cci-event-fetch
curl -s "https://www.hanno-cci.or.jp/wp-json/wp/v2/xo_event?per_page=100&page=1&after=2026-01-01T00:00:00&xo_event_cat=8,20,10,7&_fields=id,date,modified_gmt,link,title,content,xo_event_cat" \
  -o calendar/tests/fixtures/cal-cci-event-fetch/api-page1.json
echo '{}' > calendar/tests/fixtures/cal-cci-event-fetch/manifest.json
python3 -c "import json;print(len(json.load(open('calendar/tests/fixtures/cal-cci-event-fetch/api-page1.json'))))"
```
Expected: 49 前後

- [ ] **Step 2: `run-golden` に setup を足す**

`_setup_tourism_news` の後に追加:

```python
def _setup_cci_event(m, crawler, manifest):
    """REST を fixture に差し替え、LLM 経路を断つ。

    _llm_available() を False にすると長文も method=full になり決定論化する
    (content_hash に method を含めない設計なので hash は動かない)。
    """
    with open(os.path.join(FIX, crawler, "api-page1.json"), encoding="utf-8") as f:
        posts = json.load(f)
    m.fetch_posts = lambda cfg: posts
    m._llm_available = lambda: False
```

`CRAWLERS` に追加:

```python
    ("cal-cci-event-fetch", "cal-cci-event-fetch", _setup_cci_event, None),
    ("cal-cci-event-update", "cal-cci-event-fetch", _setup_cci_event, "cal-cci-event-update"),
```

`DETERMINISTIC_DATE_CRAWLERS` に `"cal-cci-event-fetch"` を追加する
(dtstart は掲載日で実行日に依存しない)。

- [ ] **Step 3: update シナリオの seed を作る**

fixture 内の任意の 1 記事について、`content_hash` だけ食い違わせた YAML を置く。
どの記事を使うかは fixture を見て決める:

```bash
python3 -c "
import json
d = json.load(open('calendar/tests/fixtures/cal-cci-event-fetch/api-page1.json'))
p = d[0]
print('id:', p['id'], 'date:', p['date'][:10], 'title:', p['title']['rendered'][:40])
"
```

表示された `id` と `date` を使って
`calendar/tests/seed/cal-cci-event-update/2026/<MM-DD>_cci-event-<id>-000000.yaml`
を作る:

```yaml
uid: "cci-event-<id>-000000@hanno.city.tecoli.com"
summary: "ℹ️ 旧世代の見出し"
location: "飯能商工会議所"
url: "https://www.hanno-cci.or.jp/xo_event/xo_event-<id>/"
dtstart: "<date>"
dtend: "<date>"
description: |-
  旧世代の本文

  https://www.hanno-cci.or.jp/xo_event/xo_event-<id>/

render:
  gcal:
    mode: single-allday

source:
  type: hanno-cci-event
  id: "<id>"
  url: "https://www.hanno-cci.or.jp/xo_event/xo_event-<id>/"
  category: "お知らせ"
  summary_method: "full"
  content_hash: "sha256-0000000000000000"
```

- [ ] **Step 4: golden を生成して確認**

Run: `python3 calendar/tests/run-golden --update && ls calendar/tests/golden/cal-cci-event-*`

確認事項:
- `cal-cci-event-fetch/` に fixture の全件ぶんの YAML がある
- `cal-cci-event-update/` は 1 件多い (旧世代 + 新世代が共存する = 追記型)
- 新世代の YAML に `supersedes: "cci-event-<id>-000000@..."` が入っている

Run: `grep -l supersedes calendar/tests/golden/cal-cci-event-update/*.yaml`
Expected: 1 ファイル

- [ ] **Step 5: golden が安定していることを確認**

Run: `python3 calendar/tests/run-golden`
Expected: `All golden checks passed.`

- [ ] **Step 6: コミット**

```bash
git add calendar/tests/
git commit -m "test(calendar): 商工会議所 xo_event クローラの golden 2 シナリオ"
```

---

### Task 6: routing と CI とドキュメント

**Files:**
- Modify: `calendar/bin/cal-myhanno`
- Modify: `.github/workflows/cal-daily.yml`
- Modify: `README.md`, `calendar/README.md`

**Interfaces:**
- Consumes: Task 3 が生成する `source.type: hanno-cci-event` の YAML
- Produces: なし (最終タスク)

- [ ] **Step 1: `CALENDARS` に 2 本追加**

`calendar/bin/cal-myhanno` の `"chef"` の行の後に:

```python
    # 飯能商工会議所の告知 (お知らせ・セミナー・経営支援・地域振興)。
    # tecolicom@gmail.com 所有、一般公開、SA に writer を委託。gws CLI で作成。
    "cci":        "b0a56c8e1f5246cda41e2fdb3c449b20c50bb365aac92333a4a9290a21e7edcf@group.calendar.google.com",  # 商工会議所からのお知らせ
    "cci.en":     "b932613ee11b3b16657b986a7ec1bd82ad7c385c30de75a2db5834ba1a297e32@group.calendar.google.com",  # 商工会議所からのお知らせ（EN）
```

- [ ] **Step 2: routing を追加**

```python
    "hanno-cci-chef":         "chef",
    "hanno-cci-event":        "cci",
```

- [ ] **Step 3: 英訳が有効であることを確認**

`cal-translate-en` の `NO_TRANSLATION_SOURCE_TYPES` に `hanno-cci-event` を
**入れない** (chef と違い英訳する)。既に `{"hanno-cci-chef"}` のみなので変更不要。

Run:
```bash
python3 -c "
import importlib.machinery, importlib.util as u
l = importlib.machinery.SourceFileLoader('cm','calendar/bin/cal-myhanno')
s = u.spec_from_loader('cm', l); m = u.module_from_spec(s); l.exec_module(m)
print('cci routing:', m.calendar_key_for_doc({'source': {'type': 'hanno-cci-event'}}))
print('lang=default:', [k for k in m.CALENDARS if '.' not in k])
print('lang=en     :', [k for k in m.CALENDARS if k.endswith('.en')])
"
```
Expected: `cci routing: cci` / `lang=en` に `cci.en` が含まれる

- [ ] **Step 4: CI に crawl ステップを追加**

`.github/workflows/cal-daily.yml` の `Crawl hanno-cci-chef` の直前に:

```yaml
      - name: Crawl hanno-cci-event
        # 長文は Claude Haiku で要約する。ANTHROPIC_API_KEY が無いと method が
        # llm-haiku-4-5 から full に変わるが、content_hash に method を含めない
        # 設計なので hash は動かない (= flood しない)。それでも要約の有無で
        # 見え方が変わるので、CI では必ず鍵を渡す。
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: ./calendar/bin/cal-cci-event-fetch --out-dir calendar/events --min-items 0 || echo "hanno-cci-event" >> "$RUNNER_TEMP/crawl-failures.txt"
```

集合同期型ではないので prune は不要。

- [ ] **Step 5: ローカルで全テスト**

Run:
```bash
python3 calendar/tests/run-golden
```
Expected: `All golden checks passed.`

Run:
```bash
python3 -c "
import glob, subprocess, sys
ts=sorted(glob.glob('calendar/tests/test_*.py')); fail=0
for t in ts:
    p=subprocess.run([sys.executable,t],capture_output=True,text=True)
    if p.returncode: fail=1; print('FAIL',t)
print(f'unit: {len(ts)} tests, fail={fail}')
"
```
Expected: `fail=0`

- [ ] **Step 6: `calendar/README.md` を更新**

カレンダー構成の表に 2 行追加:

```
| `cci` | 商工会議所からのお知らせ | 商工会議所の告知 (検定を除く 4 カテゴリ) | hanno-cci-event |
| `cci.en` | 商工会議所からのお知らせ（EN） | `cci` の英訳 | (同上) |
```

`chef` の説明にある「EN なし」の理由を、**「店名が固有名詞で訳しても情報が増えない」**
に直す (「shop カレンダーだから」は誤りだった。`publicCalendars()` は言語で
絞らないので、登録すれば英語カレンダーも店舗ページに出る)。

`bin/` 一覧に追加:

```
│   ├── cal-cci-event-fetch      商工会議所の告知 (xo_event)、長文は LLM 要約
```

`_lib` ヘルパ表に追加:

```
| LLM 出力の検算 | `drop_unchanged_claims(text)` — 「A から A に変更」を含む文を落とす。差分行を作る全クローラが共有 |
```

- [ ] **Step 7: ルート `README.md` を更新**

「主なソース」に追加:

```
- **飯能商工会議所 / 告知** (`cal-cci-event-fetch`): WordPress REST API (`xo_event`)。お知らせ・セミナー・経営支援・地域振興の 4 カテゴリ (検定は除外)。長文は Claude Haiku で要約。**開催日は REST に出てこない**ので dtstart は掲載日
```

カレンダー本数を 5 → 7 に直す。CI の節に `Crawl hanno-cci-event` を追記。

- [ ] **Step 8: コミット**

```bash
git add calendar/bin/cal-myhanno .github/workflows/cal-daily.yml README.md calendar/README.md
git commit -m "feat(calendar): cci カレンダーの routing / CI 配線 / ドキュメント"
```

---

## 実装後の初回反映 (手動で行う)

1. **生成して差分を読む**

```bash
./calendar/bin/cal-cci-event-fetch --out-dir calendar/events
git status --short calendar/events | head
```

2. **英訳**

```bash
export ANTHROPIC_API_KEY=...
./calendar/bin/cal-translate-en --events-dir calendar/events
```

3. **Calendar へ反映**

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/myhanno/sa.json
rm -f ~/.config/gws/sa_token_cache.json
./calendar/bin/cal-myhanno diff -d calendar/events
./calendar/bin/cal-myhanno apply-all -d calendar/events --only-managed
./calendar/bin/cal-myhanno apply-all -d calendar/events --only-managed --lang en
./calendar/bin/cal-myhanno diff -d calendar/events
```

4. **商工会議所の店舗ページに登録** (アプリ UI)

`https://city.tecoli.com/shop/ChIJ_aM0DDcmGWAR3KV7H6eOrIs/?admin=1` →
「公開カレンダー」→ 下記 ICS URL:

```
https://calendar.google.com/calendar/ical/b0a56c8e1f5246cda41e2fdb3c449b20c50bb365aac92333a4a9290a21e7edcf%40group.calendar.google.com/public/basic.ics
```

これで商工会議所のカレンダーが 2 本になり、`calendar-boxes.ts:186` の
`hasGear = metas.length >= 2` が真になって ⚙ が出る。

5. **コミットして push**
