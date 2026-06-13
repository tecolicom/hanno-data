"""calendar/bin/ 配下 crawler スクリプトの共通ヘルパ.

各 crawler が独自実装していた helper / idempotency check を集約。

使い方:
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _lib import USER_AGENT, fetch, existing_content_hash_matches, read_yaml_scalar, yaml_escape_str

引数命名の規約:
    s         — 任意のテキスト (HTML / 本文 / Markdown 等の総称)
    html      — 入力が HTML であることを明示する必要がある場合のみ
    url, dest — fetch 系の入力 URL / 保存先 path
    path      — 単一ファイルの読込 path
    out_dir / events_dir — ディレクトリ path
"""
from __future__ import annotations

import glob
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date as _date


# ==================== 定数 ====================


# 全 crawler 共通の User-Agent (= 取得先サーバ側で連絡先が辿れる identifier)
USER_AGENT = "myhanno-calendar-fetcher/0.1 (+https://city.tecoli.com)"

# 全 crawler 共通の UID namespace (iCalUID の `@` 以降に使う)
UID_NAMESPACE = "hanno.city.tecoli.com"

# AI 要約 / 翻訳結果の冒頭に付ける disclaimer (日本語). cal-oshirase-fetch が
# 付与し、cal-translate-en が翻訳時に剥がす契約。
AI_DISCLAIMER_JP = "AI による要約 (正確な情報は元記事をご確認ください)"


# ==================== HTTP fetch ====================


def fetch(url: str, timeout: int = 30) -> str:
    """User-Agent 付きで HTTP GET し、UTF-8 デコードした body 文字列を返す.

    エラーは呼出側に伝播。
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_binary(url: str, dest: str, timeout: int = 30) -> None:
    """User-Agent 付きで binary download (PDF 等). dest path に保存."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        with open(dest, "wb") as f:
            f.write(r.read())


# 共有 HTTP cache (ETag / Last-Modified 永続化先). git で commit する。
HTTP_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # calendar/
    ".http-cache.json",
)


def fetch_with_cache(
    url: str,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: int = 30,
) -> tuple[str | None, str | None, str | None]:
    """Conditional GET 対応 fetch.

    呼出側が持っている etag / last_modified を `If-None-Match` /
    `If-Modified-Since` で送り、サーバが 304 を返したら body=None で返す。
    そうでなければ body + 新しい etag / last_modified を返す。

    戻り値: (body | None, etag, last_modified)
        body が None = 304 not modified (= 既存 YAML 維持)。
        body が str  = 新規/変更。呼出側は parse + save。
    """
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            # 200 OK だがレスポンスに ETag/Last-Modified が無い時は旧値を維持
            # しない (= 次回も無条件 GET になる、これが望ましい)。
            new_etag = r.headers.get("ETag")
            new_lm = r.headers.get("Last-Modified")
            return body, new_etag, new_lm
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None, etag, last_modified
        raise


def load_http_cache(path: str = HTTP_CACHE_PATH) -> dict:
    """HTTP cache (URL → {etag, last_modified}) を読み込む.

    無ければ空 dict。format error 時も空 dict (= 全 URL を再 fetch)。
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_http_cache(cache: dict, path: str = HTTP_CACHE_PATH) -> None:
    """HTTP cache を JSON で書き戻す. dir が無ければ作る."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, sort_keys=True, indent=2)


# ==================== HTML / テキスト正規化 ====================


def strip_html(s: str) -> str:
    """HTML タグ + 主要 entity を素のテキストに.

    block-level タグ (br, /p, /li, /h1-6) は適切な改行に置換してから
    残タグを除去。crawler が cell 内 / 本文 block どちらでも使える共通実装。
    """
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n\n", s, flags=re.I)
    s = re.sub(r"</li\s*>", "\n", s, flags=re.I)
    s = re.sub(r"</h[1-6]\s*>", "\n\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return s


def collapse_space(s: str) -> str:
    """連続空白を 1 個に潰し前後 strip."""
    return re.sub(r"\s+", " ", s).strip()


def normalize_fullwidth_digits(s: str) -> str:
    """全角数字 (U+FF10-FF19) を ASCII 数字 (0-9) に."""
    out = []
    for c in s:
        co = ord(c)
        if 0xff10 <= co <= 0xff19:
            out.append(chr(co - 0xff10 + 0x30))
        else:
            out.append(c)
    return "".join(out)


def normalize_tilde(s: str) -> str:
    """全角ティルダ U+FF5E → 波ダッシュ U+301C."""
    return s.replace("～", "〜")


def normalize_body(s: str) -> str:
    """本文 block を正規化: 段落間 1 空行、行頭空白除去、末尾 strip.

    `strip_html()` の結果に対して掛ける段組整形。
    """
    lines = [ln.rstrip() for ln in s.split("\n")]
    lines = [re.sub(r"^[ 　]+", "", ln) for ln in lines]
    out: list[str] = []
    blank_run = 0
    for ln in lines:
        if ln == "":
            blank_run += 1
            if blank_run <= 1:
                out.append(ln)
        else:
            blank_run = 0
            out.append(ln)
    return "\n".join(out).strip()


def strip_markdown(s: str, bullet: str = "• ") -> str:
    """LLM が混入させた Markdown 記法を plain text に変換.

    Google カレンダーの description 欄は Markdown 非対応なので、太字・
    見出し・箇条書き・コード・リンク等を素テキスト化する。

    bullet: 行頭 `-` / `*` を置換する記号 (日本語は `・`、英語は `• ` 等)。
    """
    if not s:
        return s
    s = re.sub(r"\*\*([^*\n]+?)\*\*", r"\1", s)
    s = re.sub(r"__([^_\n]+?)__", r"\1", s)
    s = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)", r"\1", s)
    s = re.sub(r"(?<!_)_(?!_)([^_\n]+?)(?<!_)_(?!_)", r"\1", s)
    s = re.sub(r"(?m)^#{1,6}\s+", "", s)
    s = re.sub(r"(?m)^[ \t]*[-*]\s+", bullet, s)
    s = re.sub(r"`([^`\n]+?)`", r"\1", s)
    s = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", s)
    return s


# ==================== HTML メタデータ抽出 ====================


_OG_UPDATED_TIME_RE = re.compile(
    r'<meta[^>]+property=["\']og:updated_time["\'][^>]+content=["\'](\d{4})-'
)


def infer_year_from_og(html: str) -> int:
    """HTML の og:updated_time meta タグから西暦年を推定。

    無ければ今日の西暦年を返す。市公式サイトの「年表記なし」記事を
    日付付きで扱うための fallback。
    """
    m = _OG_UPDATED_TIME_RE.search(html)
    return int(m.group(1)) if m else _date.today().year


# ==================== 暦変換 ====================


def reiwa_to_gregorian(reiwa_y: int) -> int:
    """令和 N 年 → 西暦. 令和元年 = 2019."""
    return 2018 + reiwa_y


def gregorian_to_reiwa(year: int) -> int:
    """西暦 → 令和 N 年. 2019 = 令和元年."""
    return year - 2018


# ==================== YAML 整形 ====================


def yaml_escape_str(s: str) -> str:
    """YAML scalar 用の文字列 escape (`"..."`、`"` と `\\` を escape)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_block_scalar(s: str, indent: int = 2) -> str:
    """改行を含む文字列を YAML の `|` ブロックスカラとして整形.

    末尾改行があれば `|` (clip)、無ければ `|-` (strip) を出し分ける。
    """
    pad = " " * indent
    lines = s.split("\n")
    if s.endswith("\n"):
        head = "|"
        body = lines[:-1] if lines and lines[-1] == "" else lines
    else:
        head = "|-"
        body = lines
    return head + "\n" + "\n".join(pad + ln for ln in body)


# ==================== イベント YAML ファイル操作 ====================


def read_yaml_scalar(path: str, key: str) -> str | None:
    """YAML ファイルから指定 key の scalar 値 (引用符付き文字列) を取り出す.

    形式: `^\\s*KEY:\\s*"VALUE"\\s*$`
    マッチする最初の行の VALUE を返す。無ければ None。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            for ln in f:
                m = re.match(r"^\s*" + re.escape(key) + r":\s*\"([^\"]*)\"\s*$", ln)
                if m:
                    return m.group(1)
    except Exception:
        return None
    return None


def existing_content_hash_matches(path: str, html_hash: str) -> bool:
    """既存 YAML の content_hash フィールドが指定の html_hash と一致するか判定.

    各 crawler が「既存 YAML と内容が同じなら write を skip」する idempotency
    check に使う。skip しないと translations: 等の後付けブロックが消えて、
    translate-en が翌日再翻訳する無限ループになる (2026-05-26 のバグ)。

    呼び出し例:
        if existing_content_hash_matches(out_path, html_hash):
            continue  # 内容変化なし、既存 YAML を保持

    path 存在しない / 読込失敗 / content_hash 行が無い: False (= 新規書込必要)。
    """
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            prev = f.read()
    except Exception:
        return False
    m = re.search(r"^\s*content_hash:\s*[\"']?sha256-([0-9a-f]+)", prev, re.MULTILINE)
    return bool(m) and m.group(1) == html_hash


def output_path_for(out_dir: str, uid: str, date_str: str) -> str:
    """events/<YYYY>/<MM-DD>_<uid-local>.yaml の物理 path を返す.

    各 crawler の出力先 layout 共通規約。
    date_str: "YYYY-MM-DD" 想定。
    """
    year_part = date_str[:4]
    md = date_str[5:10]
    fname = f"{md}_{uid.split('@')[0]}.yaml"
    return os.path.join(out_dir, year_part, fname)


def find_existing_by_uid(events_dir: str, uid: str) -> str | None:
    """events_dir 配下を再帰探索し、uid を含む YAML が既にあれば path を返す.

    crawler の incremental fetch (= UID が既出なら skip) で使う。
    YAML 冒頭 4KB のみ読むので軽量。
    """
    pattern = os.path.join(events_dir, "**", "*.yaml")
    for path in glob.glob(pattern, recursive=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
                head = f.read(4096)
        except Exception:
            continue
        if uid in head:
            return path
    return None


def load_source_config(source_key: str, config_path: str | None = None) -> dict:
    """calendar/sources.yaml から source 別設定 dict を返す。

    config_path 省略時は _lib.py から ../sources.yaml で解決 (= calendar/sources.yaml)。
    CI は hanno-data repo を checkout するので、この相対 path で必ず到達できる。
    source_key 不在 / file 不在 / YAML 不正は明示的に例外を投げて即失敗する
    (silent default は flood の温床なので避ける)。
    """
    import yaml
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "sources.yaml")
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if source_key not in data:
        raise KeyError(f"source '{source_key}' not found in {config_path}")
    return data[source_key]
