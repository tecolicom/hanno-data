"""calendar/bin/ 配下 crawler スクリプトの共通ヘルパ.

各 crawler が独自実装していた helper / idempotency check を集約。

使い方:
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _lib import existing_content_hash_matches, read_yaml_scalar
"""
from __future__ import annotations

import re


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


def existing_content_hash_matches(out_path: str, html_hash: str) -> bool:
    """既存 YAML の content_hash フィールドが指定の html_hash と一致するか判定.

    各 crawler が「既存 YAML と内容が同じなら write を skip」する idempotency
    check に使う。skip しないと translations: 等の後付けブロックが消えて、
    translate-en が翌日再翻訳する無限ループになる (2026-05-26 のバグ)。

    呼び出し例:
        if existing_content_hash_matches(out_path, html_hash):
            continue  # 内容変化なし、既存 YAML を保持

    out_path 存在しない / 読込失敗 / content_hash 行が無い: False (= 新規書込必要)。
    """
    import os
    if not os.path.exists(out_path):
        return False
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            prev = f.read()
    except Exception:
        return False
    m = re.search(r"^\s*content_hash:\s*[\"']?sha256-([0-9a-f]+)", prev, re.MULTILINE)
    return bool(m) and m.group(1) == html_hash


def yaml_escape_str(s: str) -> str:
    """YAML scalar 用の文字列 escape (`"..."`、` " ` と `\\` を escape)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
