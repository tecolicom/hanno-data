# hanno-tourism ツアー URL の自動発見

作成日: 2026-07-11

## 背景 / 問題

`Calendar daily` ワークフロー (tecolicom/hanno-data) が 2026-06-30 から毎日失敗している。

失敗ステップは `cal-tourism-fetch --min-sessions 5`。原因は hanno-tourism.jp 側のサイト更新:

- URL リスト `calendar/sources/hanno-tourism/urls.txt` にハードコードされた 10 個のツアー URL
  (`ec-morikaori-rose` 等、春〜初夏の季節もの) が会期終了で削除され、アクセスすると
  トップ `https://hanno-tourism.jp/` に 301 リダイレクトされるようになった。
- `cal-tourism-fetch` は canonical URL 不一致で全件 skip → 抽出 0 件 →
  `--min-sessions 5` を下回り exit 2 (壊れたデータの commit を防ぐ安全弁が正しく発火)。

`urls.txt` は初回コミット以来一度も更新されておらず、継続メンテされていない。
サイトは季節の変わり目にツアーを丸ごと入れ替えるため、手動リストは構造的に陳腐化し、
この失敗は季節ごとに再発する。

現在サイトには新しいツアーが 17 件公開中で、パス構造 `…/hanno-eco/tour/<slug>/` 自体は健在。
一覧ページ `/hanno-eco/` の静的 HTML に全 17 件のリンクが含まれる (JS 依存なし)。

## ゴール

`urls.txt` の手動メンテを不要にする。一覧ページから現行ツアー URL を自動発見して抽出対象にする。

## 設計

### 発見処理 (新規)

`cal-tourism-fetch` に一覧ページ crawl を追加する。

1. `https://hanno-tourism.jp/hanno-eco/` を取得。
2. HTML から `href="…/hanno-eco/tour/<slug>/"` 形式のリンクを抽出。
3. 既存の `URL_ALLOWLIST_PATTERN`
   (`^https://hanno-tourism\.jp/hanno-eco/tour/[a-z0-9\-]+/?$`) で検証。
4. 末尾スラッシュを正規化し、重複を除去。

### URL ソースの合成

- 抽出対象 = **自動発見した URL ∪ `urls.txt` のシード URL** (和集合、dedup)。
- `urls.txt` は「一覧に出ないツアーを手動でピン留めする」シードとして温存する。
  普段は空でよい。ファイルが無い/空でも動作する。

### 既存の安全網は温存

- 各ページの canonical チェック、セッション抽出、`--min-sessions` ガードは変更しない。
- 一覧ページ側が壊れて発見 0 件になった場合も、min-sessions ガードで大声で失敗し、
  壊れたデータは commit しない (現状と同じ挙動)。
- 加えて「一覧から発見 0 件」を示す WARN を stderr に出し、原因診断を容易にする。

### インターフェース

- `--index-url URL` オプションを追加 (default: `https://hanno-tourism.jp/hanno-eco/`)。
  自動発見の起点を差し替え可能にし、テストとサイト移転に備える。
- `--no-discover` フラグを追加し、自動発見を無効化して urls.txt のみで動かせるようにする
  (回帰時の緊急退避・デバッグ用)。

## テスト

- 一覧ページ HTML の固定サンプルを入力に、tour リンクのみを正しく抽出し
  allowlist 外・重複・末尾スラッシュ差を正規化することを検証するユニットテスト
  (ネットワーク非依存)。
- 発見 URL と urls.txt シードの和集合・dedup の検証。

## 非ゴール / YAGNI

- 一覧ページ以外 (`/event/` 等) の横断発見はしない。必要になったら別途。
- LLM 抽出は導入しない (現行の決定論パーサを維持)。
- 過去に撤去された古いイベント YAML の掃除は本タスクの対象外。
