#!/usr/bin/env python3
"""_lib.normalize_char_width のユニットテスト。
実行: python3 calendar/tests/test_char_width.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "_lib.py")
loader = importlib.machinery.SourceFileLoader("_lib", SCRIPT)
spec = importlib.util.spec_from_loader("_lib", loader)
lib = importlib.util.module_from_spec(spec)
loader.exec_module(lib)


def test_fullwidth_latin_to_ascii():
    # 実データの表記揺れ 6 種のうち 5 種が N.Teatime に寄る
    assert lib.normalize_char_width("Ｎ．Ｔｅａｔｉｍｅ") == "N.Teatime"
    assert lib.normalize_char_width("Ｎ．Teatime") == "N.Teatime"
    assert lib.normalize_char_width("N．Teatime") == "N.Teatime"
    assert lib.normalize_char_width("Ｎ.Teatime") == "N.Teatime"
    assert lib.normalize_char_width("N.Teatime") == "N.Teatime"


def test_case_difference_is_preserved():
    # 大小文字は判断を含むので寄せない (残差 1 件は許容する設計)
    assert lib.normalize_char_width("N.teatime") == "N.teatime"


def test_fullwidth_digits():
    assert lib.normalize_char_width("（８月は夏季休業）") == "（8月は夏季休業）"


def test_parens_are_preserved():
    # 日本語文中の全角括弧は保つ
    assert lib.normalize_char_width("ダルバート（ネパール料理）") == "ダルバート（ネパール料理）"
    assert lib.normalize_char_width("吊るし飾りの会（ＰＭ）") == "吊るし飾りの会（PM）"


def test_halfwidth_kana_to_fullwidth():
    assert lib.normalize_char_width("焼きたてﾍﾞｰｸﾞﾙ・ﾄﾞﾘﾝｸ") == "焼きたてベーグル・ドリンク"
    assert lib.normalize_char_width("魯肉飯（ﾙｰﾛｰﾊﾝ）") == "魯肉飯（ルーローハン）"


def test_fullwidth_tilde_is_left_to_normalize_tilde():
    # U+FF5E は normalize_tilde() の担当 (波ダッシュ U+301C に寄せる)。
    # ここで `~` にすると _lib 内で同じ文字の扱いが食い違う。
    assert lib.normalize_char_width("10時～17時") == "10時～17時"
    assert lib.normalize_tilde("10時～17時") == "10時〜17時"


def test_ideographic_space_untouched():
    # 店名内の全角スペース 1 個は原文のまま
    assert lib.normalize_char_width("Bouguet　Bagle") == "Bouguet　Bagle"


def test_japanese_text_untouched():
    for s in ["北京ごはん", "浮き雲", "日替わりランチ", "手網焙煎珈琲", "出店者募集中"]:
        assert lib.normalize_char_width(s) == s, s


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all char-width tests passed")
