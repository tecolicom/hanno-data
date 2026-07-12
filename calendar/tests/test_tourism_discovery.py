#!/usr/bin/env python3
"""cal-tourism-fetch の discover_tour_urls / normalize_tour_url のユニットテスト。
ネットワーク非依存。実行: python3 calendar/tests/test_tourism_discovery.py
"""
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-fetch")

loader = importlib.machinery.SourceFileLoader("cal_tourism_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)  # __name__ != "__main__" なので main() は走らない


SAMPLE_HTML = """
<html><body>
  <a href="https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru">ホタル</a>
  <a href="https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/">ホタル(再掲)</a>
  <a href="https://hanno-tourism.jp/hanno-eco/tour/ec-naguricanoe-sup/">SUP</a>
  <a href="https://hanno-tourism.jp/hanno-eco/about/">about(除外)</a>
  <a href="https://hanno-tourism.jp/event/">event(除外)</a>
  <a href="https://hanno-tourism.jp/hanno-eco/tour/BAD_SLUG/">大文字(除外)</a>
</body></html>
"""


def test_normalize_adds_trailing_slash():
    assert mod.normalize_tour_url(
        "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru"
    ) == "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"
    assert mod.normalize_tour_url(
        "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"
    ) == "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"


def test_discover_extracts_dedups_and_filters():
    urls = mod.discover_tour_urls(SAMPLE_HTML)
    assert urls == [
        "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/",
        "https://hanno-tourism.jp/hanno-eco/tour/ec-naguricanoe-sup/",
    ], urls


def test_discover_empty_on_no_links():
    assert mod.discover_tour_urls("<html><body>no tours</body></html>") == []


if __name__ == "__main__":
    test_normalize_adds_trailing_slash()
    test_discover_extracts_dedups_and_filters()
    test_discover_empty_on_no_links()
    print("OK: all discovery tests passed")
