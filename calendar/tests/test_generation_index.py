#!/usr/bin/env python3
"""cal-oshirase-fetch の世代索引のユニットテスト。ネットワーク非依存。
実行: python3 calendar/tests/test_generation_index.py
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


def _yaml(uid, dtstart, content_hash):
    return (f'uid: "{uid}"\n'
            f'dtstart: "{dtstart}"\n'
            f'dtend: "{dtstart}"\n'
            f'source:\n'
            f'  content_hash: "sha256-{content_hash}"\n')


def _make_events(specs):
    """specs: [(filename, uid, dtstart, content_hash)] → 一時 events dir を作る."""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "2026"), exist_ok=True)
    for fname, uid, dtstart, ch in specs:
        with open(os.path.join(d, "2026", fname), "w", encoding="utf-8") as f:
            f.write(_yaml(uid, dtstart, ch))
    return d


def test_groups_by_page_id():
    d = _make_events([
        ("05-01_oshirase-7334.yaml", "oshirase-7334@x", "2026-05-01", "aaaaaaaaaaaaaaaa"),
        ("08-08_oshirase-7334-497925.yaml", "oshirase-7334-497925@x", "2026-08-08", "497925995081bafc"),
        ("06-13_oshirase-13691-6f01a7.yaml", "oshirase-13691-6f01a7@x", "2026-06-13", "6f01a79efed9044c"),
    ])
    idx = mod._existing_generations(d, "oshirase")
    assert set(idx) == {"7334", "13691"}
    assert len(idx["7334"]) == 2
    assert len(idx["13691"]) == 1


def test_newest_generation_first():
    d = _make_events([
        ("05-01_oshirase-7334.yaml", "oshirase-7334@x", "2026-05-01", "aaaaaaaaaaaaaaaa"),
        ("08-08_oshirase-7334-497925.yaml", "oshirase-7334-497925@x", "2026-08-08", "497925995081bafc"),
    ])
    idx = mod._existing_generations(d, "oshirase")
    dtstart, uid, path, ch = idx["7334"][0]
    assert dtstart == "2026-08-08"
    assert uid == "oshirase-7334-497925@x"
    assert ch == "497925995081bafc"
    assert idx["7334"][1][0] == "2026-05-01"


def test_same_dtstart_tiebreak_is_stable():
    d = _make_events([
        ("07-08_oshirase-500-aaaaaa.yaml", "oshirase-500-aaaaaa@x", "2026-07-08", "aaaaaaaaaaaaaaaa"),
        ("07-08_oshirase-500-bbbbbb.yaml", "oshirase-500-bbbbbb@x", "2026-07-08", "bbbbbbbbbbbbbbbb"),
    ])
    idx = mod._existing_generations(d, "oshirase")
    # 同 dtstart は path 降順 → bbbbbb が先
    assert idx["500"][0][1] == "oshirase-500-bbbbbb@x"
    assert idx["500"][1][1] == "oshirase-500-aaaaaa@x"


def test_ignores_other_prefixes():
    d = _make_events([
        ("07-08_shicho-blog-99-aaaaaa.yaml", "shicho-blog-99-aaaaaa@x", "2026-07-08", "aaaaaaaaaaaaaaaa"),
    ])
    assert mod._existing_generations(d, "oshirase") == {}


def test_empty_dir():
    d = tempfile.mkdtemp()
    assert mod._existing_generations(d, "oshirase") == {}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all generation-index tests passed")
