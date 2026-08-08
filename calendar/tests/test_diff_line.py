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
    """_llm_available と diff_with_llm を差し替えるヘルパ."""
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
