#!/usr/bin/env python3
"""_lib.sync_set の I/O のユニットテスト (tmpdir、ネットワーク不使用)。
実行: python3 calendar/tests/test_sync_set_io.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import glob
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "_lib.py")
loader = importlib.machinery.SourceFileLoader("_lib", SCRIPT)
spec = importlib.util.spec_from_loader("_lib", loader)
lib = importlib.util.module_from_spec(spec)
loader.exec_module(lib)

TODAY = "2026-06-01"


def _render(uid, item, source_id, content_hash):
    return (f'uid: "{uid}"\n'
            f'summary: "{item["summary"]}"\n'
            f'dtstart: "{item["date"]}"\n'
            f'dtend: "{item["date"]}"\n'
            f"source:\n"
            f'  type: test-source\n'
            f'  id: "{source_id}"\n'
            f'  content_hash: "{content_hash}"\n')


def _items(*pairs):
    return [{"date": d, "summary": s, "description": ""} for d, s in pairs]


def _yaml_files(d):
    return sorted(os.path.relpath(p, d)
                  for p in glob.glob(os.path.join(d, "**", "*.yaml"), recursive=True))


def test_creates_files_at_expected_paths():
    with tempfile.TemporaryDirectory() as d:
        stats = lib.sync_set(d, "chef", _items(("2026-06-10", "北京ごはん")),
                             _render, today=TODAY)
        assert stats["added"] == 1, stats
        assert _yaml_files(d) == [os.path.join("2026", "06-10_chef-20260610-01.yaml")], _yaml_files(d)


def test_second_run_with_same_data_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        items = _items(("2026-06-10", "北京ごはん"))
        lib.sync_set(d, "chef", items, _render, today=TODAY)
        path = os.path.join(d, "2026", "06-10_chef-20260610-01.yaml")
        before = os.stat(path).st_mtime_ns
        stats = lib.sync_set(d, "chef", items, _render, today=TODAY)
        assert stats == {"added": 0, "updated": 0, "deleted": 0, "unchanged": 1}, stats
        assert os.stat(path).st_mtime_ns == before, "無変化なのに書き換えられた"


def test_changed_summary_updates_in_place():
    with tempfile.TemporaryDirectory() as d:
        lib.sync_set(d, "chef", _items(("2026-06-10", "北京ごはん")), _render, today=TODAY)
        stats = lib.sync_set(d, "chef", _items(("2026-06-10", "浮き雲")), _render, today=TODAY)
        assert stats["updated"] == 1, stats
        path = os.path.join(d, "2026", "06-10_chef-20260610-01.yaml")
        with open(path, encoding="utf-8") as f:
            assert "浮き雲" in f.read()


def test_removed_future_event_is_deleted():
    with tempfile.TemporaryDirectory() as d:
        lib.sync_set(d, "chef",
                     _items(("2026-06-05", "A"), ("2026-06-10", "B"), ("2026-06-20", "C")),
                     _render, today=TODAY)
        stats = lib.sync_set(d, "chef",
                             _items(("2026-06-05", "A"), ("2026-06-20", "C")),
                             _render, today=TODAY)
        assert stats["deleted"] == 1, stats
        assert not os.path.exists(os.path.join(d, "2026", "06-10_chef-20260610-01.yaml"))


def test_same_day_multiple_entries_get_stable_sequence():
    # 連番は summary のソート順で決まる = 入力順が変わっても UID が動かない
    with tempfile.TemporaryDirectory() as d:
        lib.sync_set(d, "chef", _items(("2026-06-10", "ZZZ"), ("2026-06-10", "AAA")),
                     _render, today=TODAY)
        assert _yaml_files(d) == [
            os.path.join("2026", "06-10_chef-20260610-01.yaml"),
            os.path.join("2026", "06-10_chef-20260610-02.yaml"),
        ], _yaml_files(d)
        with open(os.path.join(d, "2026", "06-10_chef-20260610-01.yaml"), encoding="utf-8") as f:
            assert "AAA" in f.read()


def test_other_prefix_yaml_is_untouched():
    # 同じ events/ にある別クローラ / 手動 YAML を巻き込まない
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "2026"))
        other = os.path.join(d, "2026", "06-10_evt-20260610-01.yaml")
        with open(other, "w", encoding="utf-8") as f:
            f.write('uid: "evt-20260610-01@hanno.city.tecoli.com"\ndtstart: "2026-06-10"\n')
        lib.sync_set(d, "chef", _items(("2026-06-05", "A"), ("2026-06-20", "C")),
                     _render, today=TODAY)
        assert os.path.exists(other), "別 prefix の YAML が消された"


def test_too_many_deletions_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        lib.sync_set(d, "chef",
                     _items(("2026-06-05", "A"), ("2026-06-10", "B"),
                            ("2026-06-11", "C"), ("2026-06-20", "D")),
                     _render, today=TODAY)
        before = _yaml_files(d)
        try:
            lib.sync_set(d, "chef", _items(("2026-06-05", "A"), ("2026-06-20", "D")),
                         _render, today=TODAY, max_delete=1)
        except lib.SetSyncTooManyDeletions:
            assert _yaml_files(d) == before, "例外を投げたのにファイルが変わった"
            return
        raise AssertionError("SetSyncTooManyDeletions が投げられなかった")


def test_dry_run_touches_nothing():
    with tempfile.TemporaryDirectory() as d:
        stats = lib.sync_set(d, "chef", _items(("2026-06-10", "北京ごはん")),
                             _render, today=TODAY, dry_run=True)
        assert stats["added"] == 1, stats
        assert _yaml_files(d) == [], _yaml_files(d)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all sync_set I/O tests passed")
