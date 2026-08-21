#!/usr/bin/env python3
"""cal-gcal の「書き込み直前の再確認」のユニットテスト。
索引構築後に Calendar 側が変わった状況を作って、正しく振る舞うか検証する。
gws / find_event_by_uid を差し替えるのでネットワーク非依存。
実行: python3 calendar/tests/test_apply_recheck.py
"""
import argparse
import importlib.machinery
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_myhanno",
                                              os.path.join(BIN, "cal-gcal"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

# 注: この YAML に対する render_yaml_to_event() の実出力は実機で確認済み:
#   {"summary": "ℹ️ テスト記事", "description": "新しい本文",
#    "start": {"date": "2026-08-08"}, "end": {"date": "2026-08-09"}}
# - end.date は排他的終端なので dtstart の翌日になる
# - source: は YAML のメタ情報で、イベント body には出ない
# _calendar_event() はこれに合わせること。ずれると events_in_sync が常に False になり、
# 「in-sync なら書かない」系のテストが誤って落ちる。
YAML_DOC = '''uid: "oshirase-1@hanno.city.tecoli.com"
summary: "ℹ️ テスト記事"
dtstart: "2026-08-08"
dtend: "2026-08-08"
description: |-
  新しい本文

render:
  gcal:
    mode: single-allday

source:
  type: city-hanno-oshirase
  id: "1"
  url: "https://example.com/1.html"
'''

UID = "oshirase-1@hanno.city.tecoli.com"


def _write_yaml():
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(YAML_DOC)
    return path


class StubIndex:
    """EventIndex の代わり。固定の 1 件を返す (または None)。"""

    def __init__(self, event):
        self.event = event

    def get(self, calendar_id, uid):
        return self.event


def _calendar_event(description):
    """Calendar 側にあるイベントを模した dict (render_yaml_to_event の実出力に合わせる)。"""
    return {
        "id": "evt-1",
        "etag": '"e1"',
        "iCalUID": UID,
        "summary": "ℹ️ テスト記事",
        "description": description,
        "start": {"date": "2026-08-08"},
        "end": {"date": "2026-08-09"},   # 終日イベントの end は排他的
    }


def _run(index_event, refetch_event, dry_run=False):
    """cmd_apply を走らせ、(結果 dict, gws 呼び出しログ) を返す。"""
    calls = []

    def fake_gws(*args, params=None, body=None):
        calls.append({"args": args, "params": params, "body": body})
        return {"summary": (body or {}).get("summary", ""), "id": "evt-1"}

    mod.gws = fake_gws
    mod.find_event_by_uid = lambda uid, cal=None: refetch_event

    path = _write_yaml()
    try:
        ns = argparse.Namespace(yaml_file=path, dry_run=dry_run, lang="default",
                                silent=True, index=StubIndex(index_event))
        return mod.cmd_apply(ns), calls
    finally:
        os.remove(path)


def test_skips_write_when_recheck_says_in_sync():
    """索引では差分ありだが、取り直すと既に最新 → 書かない。"""
    stale = _calendar_event("古い本文")        # 索引の値 (差分あり)
    fresh = _calendar_event("新しい本文")      # 実際の値 (差分なし)
    res, calls = _run(stale, fresh)
    assert res["action"] == "in-sync", res
    assert calls == [], "events.update を呼んではいけない"


def test_merges_onto_refetched_event_not_stale_one():
    """再取得しても差分あり → 取り直した方をマージ元にする。"""
    stale = _calendar_event("古い本文")
    fresh = _calendar_event("別の古い本文")
    fresh["colorId"] = "9"                     # 索引には無く、実際の Calendar にはある
    res, calls = _run(stale, fresh)
    assert res["action"] == "updated", res
    assert len(calls) == 1
    body = calls[0]["body"]
    assert body["description"] == "新しい本文"   # YAML の値で上書きされている
    assert body["colorId"] == "9", "取り直した方の値が残っていない = 古い索引をマージ元にしている"


def test_falls_back_to_import_when_event_vanished():
    """索引にはあったが、取り直すと消えている → import に落ちる。"""
    stale = _calendar_event("古い本文")
    res, calls = _run(stale, None)
    assert res["action"] == "imported", res
    assert len(calls) == 1
    assert calls[0]["args"][2] == "import"
    assert calls[0]["body"]["iCalUID"] == UID


def test_promotes_to_update_when_event_appeared():
    """索引には無いが、取り直すと既にある → update に回す (重複作成を防ぐ)。"""
    fresh = _calendar_event("古い本文")
    res, calls = _run(None, fresh)
    assert res["action"] == "updated", res
    assert len(calls) == 1
    assert calls[0]["args"][2] == "update"


def test_dry_run_does_not_refetch():
    """--dry-run は再確認しない (書かないので不要、計測もぶれない)。"""
    stale = _calendar_event("古い本文")
    refetched = {"called": False}

    def spy(uid, cal=None):
        refetched["called"] = True
        return stale

    mod.gws = lambda *a, **kw: {}
    mod.find_event_by_uid = spy
    path = _write_yaml()
    try:
        ns = argparse.Namespace(yaml_file=path, dry_run=True, lang="default",
                                silent=True, index=StubIndex(stale))
        res = mod.cmd_apply(ns)
    finally:
        os.remove(path)
    assert res["action"] == "updated", res
    assert refetched["called"] is False, "dry-run で再取得してはいけない"


def test_without_index_uses_find_event_by_uid_once():
    """索引を渡さない単体 apply は従来どおり 1 回だけ引く (再確認しない)。"""
    fresh = _calendar_event("古い本文")
    lookups = []

    def spy(uid, cal=None):
        lookups.append(uid)
        return fresh

    mod.gws = lambda *a, **kw: {"summary": "", "id": "evt-1"}
    mod.find_event_by_uid = spy
    path = _write_yaml()
    try:
        ns = argparse.Namespace(yaml_file=path, dry_run=False, lang="default",
                                silent=True)
        res = mod.cmd_apply(ns)
    finally:
        os.remove(path)
    assert res["action"] == "updated", res
    assert lookups == [UID], f"1 回だけ引くはず: {lookups}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all apply-recheck tests passed")
