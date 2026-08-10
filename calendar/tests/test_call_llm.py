#!/usr/bin/env python3
"""_lib.call_llm のユニットテスト。httpx を差し替えるのでネットワーク非依存。
実行: python3 calendar/tests/test_call_llm.py
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


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHttpx:
    """httpx.post を記録して固定応答を返す。"""

    def __init__(self, text="こんにちは"):
        self.calls = []
        self._text = text

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json,
                           "timeout": timeout})
        return _FakeResponse({"content": [{"text": self._text}]})


def _with_key(fn):
    old = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old


def test_call_llm_passes_system_and_user():
    fake = _FakeHttpx(text="  要約テキスト  ")
    lib.httpx = fake
    got = _with_key(lambda: lib.call_llm("SYS", "USER", model="claude-haiku-4-5",
                                         max_tokens=1024))
    assert got == "要約テキスト", got
    body = fake.calls[0]["json"]
    assert body["system"] == "SYS", body
    assert body["messages"] == [{"role": "user", "content": "USER"}], body
    assert body["model"] == "claude-haiku-4-5", body
    assert body["max_tokens"] == 1024, body
    assert "temperature" not in body, body
    assert fake.calls[0]["headers"]["x-api-key"] == "sk-test"
    assert fake.calls[0]["timeout"] == 60


def test_call_llm_includes_temperature_when_given():
    fake = _FakeHttpx()
    lib.httpx = fake
    _with_key(lambda: lib.call_llm("S", "U", model="m", max_tokens=256,
                                   temperature=0))
    assert fake.calls[0]["json"]["temperature"] == 0, fake.calls[0]["json"]


def test_call_llm_returns_none_without_api_key():
    lib.httpx = _FakeHttpx()
    old = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        assert lib.call_llm("S", "U", model="m", max_tokens=10) is None
    finally:
        if old is not None:
            os.environ["ANTHROPIC_API_KEY"] = old


def test_call_llm_returns_none_when_httpx_missing():
    lib.httpx = None
    assert _with_key(lambda: lib.call_llm("S", "U", model="m", max_tokens=10)) is None


def test_call_llm_returns_none_on_exception():
    class _Boom:
        def post(self, *a, **kw):
            raise RuntimeError("boom")

    lib.httpx = _Boom()
    assert _with_key(lambda: lib.call_llm("S", "U", model="m", max_tokens=10)) is None


def test_llm_available():
    lib.httpx = _FakeHttpx()
    assert _with_key(lib.llm_available) is True
    lib.httpx = None
    assert _with_key(lib.llm_available) is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all call_llm tests passed")
