# corpus

プロンプト改訂時の手動評価に使う実データのスナップショット。
CI では読まない (`run-golden` が使うのは `../fixtures/`)。

- `news-all.json` — hanno-tourism.jp `/wp-json/wp/v2/news` の全件 (取得時 137 件)

`../seed/` とは別物。`seed/` は「out-dir に事前展開する既存 YAML」で、
こちらは「クローラへの入力となる生の API レスポンス」。

使い方:

```
ANTHROPIC_API_KEY=... python3 calendar/tests/eval-news-prompt --limit 40
```
