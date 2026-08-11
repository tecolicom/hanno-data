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


# 注: 実際の events/ では description ブロック内の「空行」は半角スペース 2 個の行
# (yaml_block_scalar が全行を indent でパディングするため)。ここでは素の空行で書いて
# おり、read_yaml_block は両方を扱える必要がある (test_read_yaml_block_nested_indent
# 側はパディングありのケース)。
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


def test_format_photo_lines_single_and_multi():
    assert mod.format_photo_lines([]) == []
    assert mod.format_photo_lines(["https://e/1.jpg"]) == ["写真: https://e/1.jpg"]
    assert mod.format_photo_lines(["https://e/1.jpg", "https://e/2.jpg"]) == [
        "写真1: https://e/1.jpg", "写真2: https://e/2.jpg",
    ]
    assert mod.format_photo_lines(["https://e/1.jpg", "https://e/2.jpg"],
                                  label="Photo", number_sep=" ") == [
        "Photo 1: https://e/1.jpg", "Photo 2: https://e/2.jpg",
    ]


def test_split_photo_lines_after_source_url_stripped():
    # 実際の順序: 本文 → 写真行 → source URL 行。split_description が URL 行を
    # 落とした後の text に対して適用する。
    text = (
        "📝 市長ブログ更新 (公開日: 2026-07-28)\n\n本文です。\n\n"
        "写真: https://www.city.hanno.lg.jp/material/images/group/79/a.jpg\n\n"
        "市長ブログ「市政一直線」: https://example.com/14127.html"
    )
    body, url = mod.split_description(text)
    body, photos = mod.split_photo_lines(body)
    assert url == "https://example.com/14127.html"
    assert photos == ["https://www.city.hanno.lg.jp/material/images/group/79/a.jpg"]
    assert body.endswith("本文です。")


def test_split_photo_lines_multiple_and_numbered():
    body, photos = mod.split_photo_lines(
        "本文です。\n\n写真1: https://e/1.jpg\n写真2: https://e/2.jpg")
    assert body == "本文です。"
    assert photos == ["https://e/1.jpg", "https://e/2.jpg"]


def test_split_photo_lines_noop_without_photos():
    body, photos = mod.split_photo_lines("本文です。\n\n続きます。")
    assert body == "本文です。\n\n続きます。"
    assert photos == []


def test_split_photo_lines_keeps_body_url_lines():
    # 本文中の「写真」以外のラベル付き URL は剥がさない
    body, photos = mod.split_photo_lines("本文です。\n\n申込: https://e/form.html")
    assert photos == []
    assert body.endswith("申込: https://e/form.html")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all description-parts tests passed")
