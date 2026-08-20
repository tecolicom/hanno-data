#!/usr/bin/env python3
"""cal-cci-chef-fetch のパース部のユニットテスト。
実行: python3 calendar/tests/test_chef_parse.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-cci-chef-fetch")
loader = importlib.machinery.SourceFileLoader("cal_cci_chef_fetch", SCRIPT)
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


HTML = '''<html><body>
<script>
  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: 'dayGridMonth',
    events: [{"start":"2026-04-14","title":"\\u6d6e\\u304d\\u96f2\\n\\u30c0\\u30eb\\u30d0\\u30fc\\u30c8","allDay":true},{"start":"2026-04-02","title":"\\u5317\\u4eac\\u3054\\u306f\\u3093","allDay":true}],
    contentHeight: 'auto'
  });
</script>
</body></html>'''


def test_extract_events_json():
    got = m.extract_events_json(HTML)
    assert len(got) == 2, got
    assert got[0]["start"] == "2026-04-14", got[0]
    assert got[0]["title"] == "浮き雲\nダルバート", got[0]


def test_extract_raises_when_structure_changes():
    try:
        m.extract_events_json("<html><body>no calendar here</body></html>")
    except ValueError:
        return
    raise AssertionError("構造変化を検知できていない")


def test_split_title_newline_separated():
    name, menu = m.split_title("北京ごはん\n魯肉飯（ﾙｰﾛｰﾊﾝ）\nタピオカ\n他")
    assert name == "北京ごはん", name
    assert menu == ["魯肉飯（ルーローハン）", "タピオカ", "他"], menu


def test_split_title_ideographic_space_padded():
    src = "N.Teatime　　　　　日替わりランチ　　　　手網焙煎珈琲"
    name, menu = m.split_title(src)
    assert name == "N.Teatime", name
    assert menu == ["日替わりランチ", "手網焙煎珈琲"], menu


def test_split_title_keeps_single_space_inside_name():
    # 空白 1 個は区切りにしない (店名の一部)
    name, menu = m.split_title("Bouguet　Bagle　　　　　焼きたてﾍﾞｰｸﾞﾙ・ﾄﾞﾘﾝｸ")
    assert name == "Bouguet　Bagle", name
    assert menu == ["焼きたてベーグル・ドリンク"], menu


def test_split_title_name_only():
    name, menu = m.split_title("ひだまりcafeほわっと（認知症支援）")
    assert name == "ひだまりcafeほわっと（認知症支援）", name
    assert menu == [], menu


def test_split_title_normalizes_variants():
    for src in ["Ｎ．Ｔｅａｔｉｍｅ", "Ｎ．Teatime", "N．Teatime", "Ｎ.Teatime"]:
        name, _ = m.split_title(src)
        assert name == "N.Teatime", (src, name)


def test_build_items():
    got = m.build_items(HTML)
    assert got == [
        {"date": "2026-04-02", "summary": "北京ごはん", "description": ""},
        {"date": "2026-04-14", "summary": "浮き雲", "description": "ダルバート"},
    ], got


def test_non_chef_entries_are_kept():
    html = HTML.replace(
        '{"start":"2026-04-02","title":"\\u5317\\u4eac\\u3054\\u306f\\u3093","allDay":true}',
        '{"start":"2026-04-02","title":"\\u6bce\\u9031\\u706b\\u66dc\\u65e5\\u3000\\u3000\\u3000\\u51fa\\u5e97\\u8005\\u52df\\u96c6\\u4e2d","allDay":true}')
    got = m.build_items(html)
    assert {"date": "2026-04-02", "summary": "毎週火曜日",
            "description": "出店者募集中"} in got, got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all chef parse tests passed")
