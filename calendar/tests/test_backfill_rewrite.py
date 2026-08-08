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

# 注: description ブロック内の「空行」は半角スペース 2 個の行 (実際の events/ と同じ)。
# test_rewrite_status_header_refuses_without_status_line がこの文字列を .replace() で
# 消す前提なので、エディタの trailing whitespace 除去で壊さないこと。
BLANK = "  "
DOC = "\n".join([
    'uid: "oshirase-7334-497925@hanno.city.tecoli.com"',
    'summary: "ℹ️ 市有地の売却"',
    'dtstart: "2026-08-08"',
    'description: |-',
    '  \U0001f504 内容更新 (公開日: 2026-08-07)',
    BLANK,
    '  AI による要約 (正確な情報は元記事をご確認ください)',
    BLANK,
    '  本文です。',
    '',
    'render:',
    '  gcal:',
    '    mode: single-allday',
    '',
    'source:',
    '  type: city-hanno-oshirase',
    '  id: "7334"',
    '  content_hash: "sha256-497925995081bafc"',
    '  summary_method: "llm-haiku-4-5"',
    '  publish_date: "2026-08-07"',
    '',
])


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
    stripped = DOC.replace('  \U0001f504 内容更新 (公開日: 2026-08-07)\n' + BLANK + '\n', '')
    assert "内容更新" not in stripped        # replace が効いていることの確認
    path = _write(stripped)
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
