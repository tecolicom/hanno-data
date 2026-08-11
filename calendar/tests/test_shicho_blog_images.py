#!/usr/bin/env python3
"""cal-shicho-blog-fetch の写真 URL 抽出のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_shicho_blog_images.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-shicho-blog-fetch")
loader = importlib.machinery.SourceFileLoader("cal_shicho_blog_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_shicho_blog_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

FIXTURE = os.path.join(HERE, "fixtures", "cal-shicho-blog-fetch", "13650.html")


def _fixture_html() -> str:
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


def test_extract_images_from_real_fixture():
    urls = mod.extract_images(_fixture_html())
    assert urls, "fixture には <figure class=\"img-item\"> があるはず"
    for u in urls:
        assert u.startswith("https://www.city.hanno.lg.jp/material/"), u


def test_extract_images_skips_header_and_footer_decorations():
    # free-layout-area の外にあるヘッダ/フッタ画像は拾わない
    urls = mod.extract_images(_fixture_html())
    assert not any("/theme/base/img_common/" in u for u in urls)


def test_extract_images_completes_protocol_relative_src():
    html = (
        '<div class="free-layout-area">'
        '<figure class="img-item"><img alt="x" src="//www.city.hanno.lg.jp/material/a.jpg"></figure>'
        '</div><div class="toiawase">'
    )
    assert mod.extract_images(html) == ["https://www.city.hanno.lg.jp/material/a.jpg"]


def test_extract_images_rejects_foreign_host():
    html = (
        '<div class="free-layout-area">'
        '<figure><img src="https://evil.example.com/a.jpg"></figure>'
        '</div><div class="toiawase">'
    )
    assert mod.extract_images(html) == []


def test_extract_images_dedupes_and_caps():
    figs = "".join(
        f'<figure><img src="//www.city.hanno.lg.jp/material/{i}.jpg"></figure>'
        for i in range(mod.MAX_PHOTOS + 3)
    )
    dup = '<figure><img src="//www.city.hanno.lg.jp/material/0.jpg"></figure>'
    html = f'<div class="free-layout-area">{dup}{figs}</div><div class="toiawase">'
    urls = mod.extract_images(html)
    assert len(urls) == mod.MAX_PHOTOS
    assert len(set(urls)) == len(urls)


def test_extract_images_none_when_no_figure():
    html = '<div class="free-layout-area"><p>本文だけ</p></div><div class="toiawase">'
    assert mod.extract_images(html) == []


def test_body_still_excludes_figures():
    # 写真は description の写真行に出す。本文テキストからは従来通り落とす。
    html = (
        '<div class="free-layout-area"><p>本文です。</p>'
        '<figure><img alt="キャプション代わりの alt" src="//www.city.hanno.lg.jp/material/a.jpg"></figure>'
        '</div><div class="toiawase">'
    )
    assert "alt" not in mod.extract_body(html)
    assert "本文です。" in mod.extract_body(html)


def test_build_description_places_photo_above_source_url():
    desc = mod.build_description(
        "https://example.com/1.html", "本文です。", False,
        status_header="📝 市長ブログ更新 (公開日: 2026-07-28)",
        images=["https://www.city.hanno.lg.jp/material/a.jpg"],
    )
    lines = [l for l in desc.split("\n") if l.strip()]
    assert lines[0].startswith("📝")
    assert lines[-2] == "写真: https://www.city.hanno.lg.jp/material/a.jpg"
    assert lines[-1].startswith("市長ブログ「市政一直線」: ")


def test_build_description_unchanged_without_images():
    before = mod.build_description("https://example.com/1.html", "本文です。", False)
    assert before == "本文です。\n\n市長ブログ「市政一直線」: https://example.com/1.html"


def test_build_description_truncated_marker_precedes_photo():
    desc = mod.build_description(
        "https://example.com/1.html", "本文です。", True,
        images=["https://www.city.hanno.lg.jp/material/a.jpg"],
    )
    lines = [l for l in desc.split("\n") if l.strip()]
    assert lines == [
        "本文です。",
        "（続きはリンク先で）",
        "写真: https://www.city.hanno.lg.jp/material/a.jpg",
        "市長ブログ「市政一直線」: https://example.com/1.html",
    ]


def test_build_description_photo_only_when_body_extraction_failed():
    desc = mod.build_description(
        "https://example.com/1.html", "", False,
        images=["https://www.city.hanno.lg.jp/material/a.jpg"],
    )
    assert desc == (
        "写真: https://www.city.hanno.lg.jp/material/a.jpg\n\n"
        "市長ブログ「市政一直線」: https://example.com/1.html"
    )


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all shicho-blog image tests passed")
