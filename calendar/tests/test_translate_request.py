#!/usr/bin/env python3
"""cal-translate-en の translate() が組み立てるリクエストのユニットテスト。
httpx を差し替えるのでネットワーク非依存。
実行: python3 calendar/tests/test_translate_request.py

回帰の由来 (2026-08-22, CI run 32590407302):
翻訳結果を「JSON を返せ」という指示だけで受け取っていたため、原文の「」を
英語の " に訳した瞬間にエスケープされない " が JSON 文字列の中に入り、
json.loads が落ちて 1 件だけ翻訳できず CI が赤になった。応答形式を
output_config.format (json_schema) でサーバ側に強制させることで塞ぐ。
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-translate-en")
loader = importlib.machinery.SourceFileLoader("cal_translate_en", SCRIPT)
spec = importlib.util.spec_from_loader("cal_translate_en", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHttpx:
    """httpx.post を記録して応答を返す。texts を複数渡すと 1 回ずつ順に返す
    (最後の 1 つは以降ずっと返る)。"""

    def __init__(self, *texts):
        self.calls = []
        self._texts = list(texts) or ['{"summary": "S", "description": "D"}']

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json,
                           "timeout": timeout})
        i = min(len(self.calls) - 1, len(self._texts) - 1)
        return _FakeResponse({"content": [{"text": self._texts[i]}]})


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


def test_request_constrains_output_to_json_schema():
    """応答形式をサーバ側に強制する。プロンプトの「JSON を返せ」だけに頼らない。"""
    fake = _FakeHttpx()
    mod.httpx = fake
    _with_key(lambda: mod.translate("要約", "本文"))
    body = fake.calls[0]["json"]
    fmt = body.get("output_config", {}).get("format")
    assert fmt, f"output_config.format が無い: {body}"
    assert fmt["type"] == "json_schema", fmt
    schema = fmt["schema"]
    assert schema["type"] == "object", schema
    assert set(schema["required"]) == {"summary", "description"}, schema
    assert schema["properties"]["summary"]["type"] == "string", schema
    assert schema["properties"]["description"]["type"] == "string", schema
    assert schema["additionalProperties"] is False, schema


def test_translate_returns_parsed_fields():
    fake = _FakeHttpx('{"summary": "EN sum", "description": "EN body"}')
    mod.httpx = fake
    got = _with_key(lambda: mod.translate("要約", "本文"))
    assert got == {"summary": "EN sum", "description": "EN body"}, got
    assert len(fake.calls) == 1, fake.calls


def test_translate_retries_when_json_is_broken():
    """スキーマ強制は 100% ではない (実測 95 回に 1 回)。引き直して拾う。"""
    broken = '{"summary": "a "b"", "description": "d"}'
    fake = _FakeHttpx(broken, '{"summary": "S", "description": "D"}')
    mod.httpx = fake
    got = _with_key(lambda: mod.translate("要約", "本文"))
    assert got == {"summary": "S", "description": "D"}, got
    assert len(fake.calls) == 2, fake.calls


def test_translate_gives_up_after_max_attempts():
    """引き直しても駄目なら None (呼出側が errors を数えて CI を赤にする)。"""
    fake = _FakeHttpx('{"summary": "a "b"", "description": "d"}')
    mod.httpx = fake
    assert _with_key(lambda: mod.translate("要約", "本文")) is None
    assert len(fake.calls) == mod.LLM_MAX_ATTEMPTS, fake.calls


def test_translate_does_not_retry_transport_failure():
    """通信・HTTP の失敗は引き直さない (翌日の実行が拾う)。"""

    class _Boom:
        def __init__(self):
            self.calls = 0

        def post(self, *a, **kw):
            self.calls += 1
            raise RuntimeError("boom")

    boom = _Boom()
    mod.httpx = boom
    assert _with_key(lambda: mod.translate("要約", "本文")) is None
    assert boom.calls == 1, boom.calls


def test_translate_returns_none_when_httpx_missing():
    """golden 網 (cal-golden-test.yml) は pyyaml しか入れない。httpx 不在でも
    このモジュールが import でき、translate() が None を返すこと
    (import 自体が失敗すると CI がテスト実行前に落ちる)。"""
    mod.httpx = None
    assert _with_key(lambda: mod.translate("要約", "本文")) is None


def test_translate_returns_none_without_api_key():
    mod.httpx = _FakeHttpx()
    old = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        assert mod.translate("要約", "本文") is None
    finally:
        if old is not None:
            os.environ["ANTHROPIC_API_KEY"] = old


def test_rehash_does_not_grow_a_blank_line():
    """--rehash-only は translation_hash 行だけを差し替え、行を増やさないこと。

    回帰の由来: 正規表現の `(\s*)$` が行末の改行まで捕まえ、それを書き戻した
    うえで `\n` を足していたため、rehash するたび translation_hash の直後に
    空行が 1 行増えていた。YAML としては読めてしまうので静かに壊れる
    (2026-08-30、議会の URL 差し替えで実際に踏んだ)。
    """
    import tempfile

    src = (
        'uid: "x@example"\n'
        'summary: "s"\n'
        "translations:\n"
        "  en:\n"
        '    summary: "S"\n'
        '    translation_hash: "sha256-0000000000000000"\n'
        '    model: "claude-haiku-4-5"\n'
        "    format_version: 3\n"
    )
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        assert mod._rewrite_translation_hash(path, "sha256-1111111111111111")
        first = open(path, encoding="utf-8").read()
        assert mod._rewrite_translation_hash(path, "sha256-2222222222222222")
        second = open(path, encoding="utf-8").read()

    assert len(first.splitlines()) == len(src.splitlines()), first
    assert len(second.splitlines()) == len(src.splitlines()), second
    assert '    translation_hash: "sha256-2222222222222222"\n' in second, second
    assert "\n\n" not in second, second


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all translate request tests passed")
