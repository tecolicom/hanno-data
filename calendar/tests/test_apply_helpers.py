#!/usr/bin/env python3
"""cal-gcal の apply 判定・マージ関数のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_apply_helpers.py
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "..", "bin"))
loader = importlib.machinery.SourceFileLoader("cal_myhanno",
                                              os.path.join(BIN, "cal-gcal"))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def _existing(**over):
    e = {
        "id": "evt1",
        "etag": '"abc"',
        "iCalUID": "u@x",
        "summary": "タイトル",
        "description": "本文",
        "start": {"date": "2026-08-08"},
        "end": {"date": "2026-08-09"},
        "source": {"title": "src", "url": "https://e.com/a"},
    }
    e.update(over)
    return e


def _new_body(**over):
    b = {
        "summary": "タイトル",
        "description": "本文",
        "start": {"date": "2026-08-08"},
        "end": {"date": "2026-08-09"},
        "source": {"title": "src", "url": "https://e.com/a"},
    }
    b.update(over)
    return b


def test_in_sync_when_identical():
    assert mod.events_in_sync(_existing(), _new_body()) is True


def test_not_in_sync_when_description_differs():
    assert mod.events_in_sync(_existing(), _new_body(description="別の本文")) is False


def test_in_sync_ignores_read_only_fields():
    # etag / id が違っても COMPARE_FIELDS 外なので in-sync
    assert mod.events_in_sync(_existing(etag='"zzz"', id="other"), _new_body()) is True


def test_in_sync_treats_missing_and_empty_as_same():
    # location は両方とも未設定 (normalize_for_diff が None と "" を同一視)
    assert mod.events_in_sync(_existing(location=""), _new_body()) is True


def test_merge_drops_read_only_fields():
    merged = mod.merge_for_update(_existing(), _new_body(summary="新タイトル"))
    for k in mod.READ_ONLY_FIELDS:
        assert k not in merged, f"{k} should be dropped"
    assert merged["summary"] == "新タイトル"


def test_merge_clears_fields_absent_from_new_body():
    # Calendar 側に location があり YAML に無い → 消す
    existing = _existing(location="飯能市役所")
    merged = mod.merge_for_update(existing, _new_body())
    assert "location" not in merged


def test_merge_keeps_unrelated_existing_fields():
    existing = _existing(colorId="5")
    merged = mod.merge_for_update(existing, _new_body())
    assert merged["colorId"] == "5"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all apply-helper tests passed")
