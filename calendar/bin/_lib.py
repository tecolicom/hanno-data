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
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

try:
    import httpx
except ImportError:  # CI / 最小環境では未インストールのことがある
    httpx = None


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


# 全角 → 半角に寄せない文字。変換は「判断を含まない文字種の寄せ」に留める。
#   括弧類 — 日本語文中で半角にすると読みにくくなる
#   全角ティルダ U+FF5E — この文字の正規化は normalize_tilde() の担当
#     (あちらは波ダッシュ U+301C に寄せる)。ここで `~` にすると _lib 内で
#     同じ文字の扱いが食い違うので触らない。
_FULLWIDTH_KEEP = frozenset("（）［］｛｝～")

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


def normalize_tilde(s: str) -> str:
    """全角ティルダ U+FF5E → 波ダッシュ U+301C."""
    return s.replace("～", "〜")


# 丸括弧囲み (U+3289 系) と丸囲み漢字 (U+328A-U+3290) の両形式が実データに出る。
# 例: 「飯能河原6/27㈯・28㈰」「3月21日㊏案内業務お休み」
_CIRCLED_WEEKDAY = {
    "㈪": "(月)", "㈫": "(火)", "㈬": "(水)", "㈭": "(木)",
    "㈮": "(金)", "㈯": "(土)", "㈰": "(日)",
    "㊊": "(月)", "㊋": "(火)", "㊌": "(水)", "㊍": "(木)",
    "㊎": "(金)", "㊏": "(土)", "㊐": "(日)",
}


def normalize_circled_weekday(s: str) -> str:
    """囲み曜日文字 (㈯ / ㊏ 等) を `(土)` 形式に開く.

    日付の曜日整合チェックが読めるようにするための前処理。
    """
    return "".join(_CIRCLED_WEEKDAY.get(c, c) for c in s)


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


# 写真 URL 行。description 内に平文で置くと、app (event-modal) と Google Calendar
# の双方が自動で anchor 化するので、クリックで写真を開ける。
_PHOTO_LINE_RE = re.compile(r"^\s*(?:写真|Photo)\s*\d*\s*[：:][ \t]*(https?://\S+)\s*$")


def format_photo_lines(urls: list[str], label: str = "写真",
                       number_sep: str = "") -> list[str]:
    """写真 URL 群を description 用の行 list にする.

    1 枚なら "写真: <url>"、複数枚なら "写真1: <url>" … と番号を振る。
    number_sep は label と番号の間 (英語なら " " を渡して "Photo 1:")。
    """
    if not urls:
        return []
    if len(urls) == 1:
        return [f"{label}: {urls[0]}"]
    return [f"{label}{number_sep}{i}: {u}" for i, u in enumerate(urls, 1)]


def split_photo_lines(text: str) -> tuple[str, list[str]]:
    """description 末尾の「写真: URL」行群を剥がす.

    戻り値: (本文, [url, ...])

    LLM に URL を渡さないための前処理。split_description() で source URL 行を
    落とした**後**に適用する (写真行は source URL 行の 1 つ上に置くため)。
    """
    lines = text.rstrip().split("\n")
    urls: list[str] = []
    while lines:
        last = lines[-1].strip()
        if not last:            # 行間の空行はまたぐ
            lines.pop()
            continue
        m = _PHOTO_LINE_RE.match(last)
        if not m:
            break
        urls.insert(0, m.group(1))
        lines.pop()
    return "\n".join(lines).strip(), urls


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
