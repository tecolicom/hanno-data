#!/usr/bin/env python3
"""cal-tourism-fetch の normalize_tour_url のユニットテスト。
ネットワーク非依存。実行: python3 calendar/tests/test_tourism_discovery.py

ツアー一覧の取得は REST API 化されたので、その検証は test_tourism_api.py にある。
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


def test_normalize_adds_trailing_slash():
    assert mod.normalize_tour_url(
        "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru"
    ) == "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"
    assert mod.normalize_tour_url(
        "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"
    ) == "https://hanno-tourism.jp/hanno-eco/tour/ec-agano-hotaru/"


if __name__ == "__main__":
    test_normalize_adds_trailing_slash()
    print("OK: all normalize tests passed")
