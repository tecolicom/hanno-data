#!/usr/bin/env python3
"""差分行が作れなかったときに「大きな変更は認められませんでした」を出す条件。
ネットワーク非依存。実行: python3 calendar/tests/test_diff_note.py

由来 (2026-09-03):
「🔄 内容更新」の見出しだけが出て中身が無い予定があり、なぜ空なのかが読み手に
分からなかった (実例: 08-19 の市有地売却)。文言を足すことにしたが、**比較を
実施したときにだけ**出さなければならない。LLM が使えない・前世代に比較材料が
無い・API が失敗した、といった「そもそも見ていない」場合に「変更は認められ
ませんでした」と書くと、調べていないのに調べたと述べることになる。

そのため差分関数は (行, 比較したか) の 2 値を返す契約にした。このテストは
その契約 — とりわけ **「見ていない」場合に True を返さないこと** — を守る。
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin")
sys.path.insert(0, BIN)
import _lib  # noqa: E402


def _load(name, modname):
    loader = importlib.machinery.SourceFileLoader(modname, os.path.join(BIN, name))
    spec = importlib.util.spec_from_loader(modname, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


osh = _load("cal-oshirase-fetch", "cal_oshirase_fetch")
cci = _load("cal-cci-event-fetch", "cal_cci_event_fetch")

_PREV_YAML = '''uid: "x@example"
summary: "テスト"
description: |-
  🔄 内容更新 (公開日: 2026-08-07 / 前回掲載: 2026-08-08)

  前回の要約です。最低売却価格は1,970万円、入札日は9月11日です。

  飯能市公式サイト 新着情報: https://example.test/1.html

source:
  type: city-hanno-oshirase
  summary_method: "llm-haiku-4-5"
'''

_BODY = "今回の本文です。" + ("あ" * 80)


def _with_prev(fn):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "prev.yaml")
        with open(p, "w", encoding="utf-8") as f:
            f.write(_PREV_YAML)
        return fn(p)


def _patch(mod, **kw):
    """mod の属性を差し替え、元に戻すための dict を返す。"""
    orig = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    return orig


def _restore(mod, orig):
    for k, v in orig.items():
        setattr(mod, k, v)


# ---------- 文言そのもの ----------

def test_note_is_shared_and_does_not_claim_the_change_was_minor():
    """文言は _lib に 1 つだけ置く (差分行を作るクローラが複数あるため)。

    「軽微な修正」等と断定しないこと。比較は「前回の*要約* × 今回の*本文*」と
    いう非対称なもので、原理的に見落としがありうる。認められなかった、という
    観測の事実だけを述べる。
    """
    note = _lib.DIFF_NO_CHANGE_NOTE
    assert note == "大きな変更は認められませんでした", note
    assert osh.DIFF_NO_CHANGE_NOTE is note
    assert cci.DIFF_NO_CHANGE_NOTE is note
    for word in ("軽微", "些細", "問題ありません"):
        assert word not in note, note


# ---------- 「見ていない」は False ----------

def test_oshirase_llm_unavailable_is_not_compared():
    orig = _patch(osh, _llm_available=lambda: False)
    try:
        got = _with_prev(lambda p: osh._diff_line("t", p, _BODY))
    finally:
        _restore(osh, orig)
    assert got == (None, False), got


def test_oshirase_api_failure_is_not_compared():
    """call_llm が None (通信・HTTP の失敗) は「比較できていない」。

    ここを True にすると、API が落ちている日に全件へ「変更は認められません
    でした」と書いてしまう。
    """
    orig = _patch(osh, _llm_available=lambda: True,
                  call_llm=lambda *a, **k: None)
    try:
        got = _with_prev(lambda p: osh._diff_line("t", p, _BODY))
    finally:
        _restore(osh, orig)
    assert got == (None, False), got


def test_oshirase_thin_body_is_not_compared():
    """本文が短すぎて LLM を呼ばなかった場合も「比較していない」。"""
    orig = _patch(osh, _llm_available=lambda: True,
                  call_llm=lambda *a, **k: (_ for _ in ()).throw(
                      AssertionError("呼んではいけない")))
    try:
        got = _with_prev(lambda p: osh._diff_line("t", p, "短い"))
    finally:
        _restore(osh, orig)
    assert got == (None, False), got


def test_oshirase_prev_url_only_is_not_compared():
    """前世代が URL のみ = 比較材料が無い。"""
    orig = _patch(osh, _llm_available=lambda: True)
    try:
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "prev.yaml")
            with open(p, "w", encoding="utf-8") as f:
                f.write(_PREV_YAML.replace('"llm-haiku-4-5"', '"url-only"'))
            got = osh._diff_line("t", p, _BODY)
    finally:
        _restore(osh, orig)
    assert got == (None, False), got


# ---------- 「見たが何も無かった」は True ----------

def test_oshirase_all_claims_dropped_is_compared():
    """機械検算 (drop_unchanged_claims) で全部落ちても「比較はした」。

    ここが False だと、まさに今回きっかけになった事例 (同値の対だけが返る) で
    見出しだけの空欄が残り続ける。
    """
    bogus = "最低売却価格が1,970万円から1,970万円に変更されました。"
    orig = _patch(osh, _llm_available=lambda: True,
                  call_llm=lambda *a, **k: bogus)
    try:
        got = _with_prev(lambda p: osh._diff_line("t", p, _BODY))
    finally:
        _restore(osh, orig)
    assert got == (None, True), got


def test_oshirase_empty_llm_response_is_compared():
    """LLM が「変更なし」の意味で空文字を返した場合も比較済み。"""
    orig = _patch(osh, _llm_available=lambda: True, call_llm=lambda *a, **k: "  ")
    try:
        got = _with_prev(lambda p: osh._diff_line("t", p, _BODY))
    finally:
        _restore(osh, orig)
    assert got == (None, True), got


def test_oshirase_genuine_change_is_returned():
    real = "入札日が9月11日から10月2日に変更されました。"
    orig = _patch(osh, _llm_available=lambda: True, call_llm=lambda *a, **k: real)
    try:
        line, compared = _with_prev(lambda p: osh._diff_line("t", p, _BODY))
    finally:
        _restore(osh, orig)
    assert compared is True
    assert line and "10月2日" in line, line


# ---------- 商工会議所側も同じ契約 ----------

def test_cci_event_contract_matches():
    """差分行を作るクローラが 2 本ある。片方だけ直る事故を防ぐ。"""
    cases = [
        (dict(_llm_available=lambda: False), (None, False)),
        (dict(_llm_available=lambda: True, call_llm=lambda *a, **k: None),
         (None, False)),
        (dict(_llm_available=lambda: True,
              call_llm=lambda *a, **k: "価格が1,000円から1,000円に変更されました。"),
         (None, True)),
    ]
    for patch, want in cases:
        orig = _patch(cci, **patch)
        try:
            got = _with_prev(lambda p: cci.diff_line("t", p, _BODY))
        finally:
            _restore(cci, orig)
        assert got == want, (patch.keys(), got, want)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all diff note tests passed")
