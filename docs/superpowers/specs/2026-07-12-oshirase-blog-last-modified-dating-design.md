# お知らせ・市長ブログの掲載日を HTTP Last-Modified 基準にする

作成日: 2026-07-12

## 背景 / 問題

市政お知らせ (`cal-oshirase-fetch`) と市長ブログ (`cal-shicho-blog-fetch`) のカレンダー
掲載日 (`dtstart`) が実態と合っていない。

現状:
- `dtstart` = **取得日 (今日, JST)**。クローラが初検出した日。
- `publish_date` = 記事の自己申告日 (お知らせ=RSS `dc:date`、ブログ=本文「更新日：YYYY年MM月DD日」)。
  カレンダーには使わず参考保持。

2 つの不都合:
1. **catch-up で山ができる**: CI が数日止まると、その間の記事を復旧日に一斉検出し、全部が
   同じ日 (取得日) に積み上がる (2026-07-12 に 23 件)。
2. **記事の自己申告日が信用できない**: 市長ブログは後日書いた記事を過去日付にできる。
   実測で、ある記事は本文「更新日：2026年06月19日」に対し HTTP `Last-Modified` は
   **2026年07月08日** (約3週間のバックデート)。自己申告日を採用すると過去日付になり、
   アプリの「今日以降」ウィンドウに永久に出ない = 毎日見ていても気づけない。

## 洞察: HTTP Last-Modified はサーバ真実

飯能市サイトの各ページは HTTP レスポンスに `Last-Modified` ヘッダを持つ (記事本文からは
操作不可、サーバ上でファイルが実際に書き換わった日時)。実測:

- お知らせ 10072: 自己申告/dc:date 6/25 → `Last-Modified` **7/7**
- 市長ブログ 13864: 自己申告 6/19 → `Last-Modified` **7/8**

`_lib.fetch_with_cache(url, etag, last_modified)` は既に `(body, etag, last_modified)` を返し、
`.http-cache.json` に per-URL の `last_modified` を蓄積済み。基盤は揃っている。

## 設計

### 掲載日ルール (両クローラ共通)

**`dtstart` = HTTP `Last-Modified` を JST に変換した日付 + 1 日**

- 「実際にウェブに現れた翌日」に出る。誠実で、毎日見れば必ず目に入る。
- 記事の自己申告日はカレンダーに一切使わない (`publish_date` に参考保持は継続)。
- 例: ブログ Last-Modified 7/8 (JST) → `dtstart` = 7/9。

### Last-Modified の取得と変換

- 各記事ページ取得時に `Last-Modified` レスポンスヘッダを読む
  (per-article の `fetch()` を `fetch_with_cache()` に寄せ、返り値の `last_modified` を使う)。
- `_lib` に純粋関数を追加:
  `last_modified_to_jst_date(header: str) -> str | None`
  RFC 1123 (`Wed, 08 Jul 2026 02:29:43 GMT`) を `email.utils.parsedate_to_datetime` で
  aware datetime に → JST に変換 → `YYYY-MM-DD` 文字列。パース不能なら `None`。
- `dtstart = (last_modified_to_jst_date + 1 day)`。日付加算は `datetime.date + timedelta(days=1)`。

### フォールバック

- `Last-Modified` ヘッダが無い / パース不能なページのみ、従来どおり **取得日 (今日)** を使う。
  市サイトは全ページ付与しているので稀。フォールバック時は WARN を stderr に出す。

### content_hash / identity への影響

- 両クローラの `content_hash` は `{title, 記事日付, body}` で **`dtstart` を含まない**。
  よって掲載日を変えても identity は変化せず、既存の (page_id, content_hash) による
  重複判定・skip はそのまま機能する。
- `source` ブロックに `last_modified` を1行追加し、掲載日の根拠を追跡可能にする。

### 既存バックログの再配置 (一度きりの migration)

現在 `dtstart = 2026-07-12` に積み上がっている catch-up 分 (お知らせ+ブログ) を対象に、
各 YAML の URL を再取得して `Last-Modified + 1` を求め、**掲載日が変わるものはファイルを
移動** (旧 `MM-DD_...yaml` を削除し新日付名で書き直す) する新モードを追加する。

- モード名: `--redate` (both crawlers)。既存の `--refetch-existing`/`--rehash-only` と同系統の
  保守モード。LLM 呼出なし (description は触らない)、`Last-Modified+1` と現 `dtstart` が
  同じなら無変更。
- スコープは「catch-up クラスタ (現 dtstart が指定日以降)」に限定できるよう
  `--redate-since YYYY-MM-DD` を持たせ、過去の落ち着いた大量イベントを巻き込まない。
- 実行は手動 catch-up と同じ扱い: blast-radius が 50 を超えるなら
  `gh workflow run "Calendar daily" -f max_changes=N`、または手元で diff を確認してから
  commit → CI で Calendar 反映。

## テスト

- `last_modified_to_jst_date` のユニットテスト (ネットワーク非依存):
  - `"Wed, 08 Jul 2026 02:29:43 GMT"` → `"2026-07-08"` (JST 11:29 なので同日)。
  - 日跨ぎ: `"Tue, 07 Jul 2026 20:00:00 GMT"` → JST 7/8 05:00 → `"2026-07-08"`。
  - パース不能 → `None`。
- `dtstart` 算出 (= JST 日付 + 1 日) の境界テスト。
- フォールバック: ヘッダ無しで取得日になること。

## 非ゴール / YAGNI

- sitemap `<lastmod>` の利用は今回入れない (Last-Modified で足りる。将来の精度改善候補)。
- ツーリズム等 他クローラの掲載日ロジックは変更しない。
- 過去の全 oshirase/blog を無制限に再配置しない (`--redate-since` で範囲を絞る)。
