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
import re
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
    """HTTP GET してテキストを返す。**golden はこの関数を差し替える** (最下層).

    **`from _hanno_lib import fetch_text` の形で import しないこと。** golden
    テストは `_hanno_lib.fetch_text` を差し替えることで URL → テキストの層を
    fixture に載せる。from-import すると呼出側モジュールの名前空間に束縛が
    コピーされ、後からの差し替えが効かず、テストが実ネットワークに出てしまう。
    `import _hanno_lib` して `_hanno_lib.fetch_text(...)` と修飾して呼ぶこと。

    (`fetch_cal` は自分のモジュール globals 経由で `fetch_text` を引くので、
    `fetch_cal` を from-import するのは問題ない。)
    """
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
        if not isinstance(lib, dict):
            raise ValueError(f"cal.php: libraries の要素が dict でない ({lib!r})")
        if lib.get("code") == lib_code:
            terms = lib.get("term")
            if not isinstance(terms, list):
                raise ValueError(f"cal.php: 館 {lib_code} に term が無い")
            return terms
    raise ValueError(f"cal.php: 館 {lib_code} が応答に含まれない")


_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def days_of(terms: list[dict], key: str) -> list[str]:
    """term 配列から closing_day / event_day を "YYYY-MM-DD" の昇順で集める.

    配信元は "2026/08/03" 形式で返す。重複は潰す。**terms_of と方針を揃え、
    正規化後の値が "YYYY-MM-DD" の形でなければ ValueError。** 黙って通すと
    ゼロ埋め無しでソート順が壊れたまま、あるいは list でない値・None/int が
    混ざったまま不正な UID を作ってしまう (取得層が死んだことと区別できなく
    なる、という terms_of と同じ理由)。
    """
    out: set[str] = set()
    for t in terms:
        days = t.get(key) or []
        if not isinstance(days, list):
            raise ValueError(
                f"cal.php: term[{key!r}] が list でない ({days!r})")
        for d in days:
            normalized = str(d).replace("/", "-")
            if not _YMD_RE.match(normalized):
                raise ValueError(
                    f"cal.php: term[{key!r}] に不正な日付が含まれる ({d!r})")
            out.add(normalized)
    return sorted(out)
