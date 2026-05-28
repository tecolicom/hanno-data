# calendar/

Myはんのう Google カレンダー群 (`tecolicom@gmail.com` 所有、`city.tecoli.com/@hanno/` から ical 配信) を YAML で canonical に管理する仕組み。日本語 + 英語の 4 カレンダー構成。

## 基本方針

- **YAML が canonical**: `events/<year>/<MM-DD>_<uid>.yaml` (1 イベント 1 ファイル) が真の正本
- **Google Calendar は投影先**: 全イベントを終日にし、時刻情報は description 冒頭の `🕒 HH:MM–HH:MM` marker で保持
- **`source:` フィールドの有無で識別**:
  - `source:` あり → クローラ管理 (自動で更新・再生成される)
  - `source:` なし → 手動キュレーション (クローラは絶対に触らない、不可侵)
- **英訳は YAML 内 `translations.en.*` に格納**: 元の summary/description は不変、英訳が追加情報として隣に並ぶ

## カレンダー構成

JP/EN の 2 言語 × 用途別 2 系統 = 4 カレンダーを Service Account 1 つで管理:

| logical key | calendar 名 | 内容 | 対応 source.type |
|---|---|---|---|
| `default` | Myはんのう | 観光・市民会館・コミュニティ等 | hanno-tourism-jp / city-hanno-shiminkaikan / (手動) |
| `gikai` | 飯能市役所 | 市政情報・市長ブログ・お知らせ | city-hanno-gikai / city-hanno-shicho-blog / city-hanno-oshirase |
| `default.en` | Myはんのう（EN） | `default` の英訳 (同 source.type) | (同上) |
| `gikai.en` | 飯能市役所（EN） | `gikai` の英訳 (同 source.type) | (同上) |

routing は `source.type` ベース。`source.type` → `default` or `gikai` のマッピングが
`bin/cal-myhanno` の `SOURCE_TYPE_TO_CALENDAR` に定義。英語カレンダーは
`<base>.<lang>` 命名で base routing と lang を直交的に組み合わせる。

## ディレクトリ構成

```
calendar/
├── bin/
│   ├── _lib.py                  全 crawler の共通ヘルパ (HTTP fetch / cache / YAML 整形 / etc.)
│   ├── cal-myhanno              Google Calendar API ラッパ (Python + gws)
│   ├── cal-tourism-fetch        hanno-tourism.jp 決定論パーサ (LLM 不使用)
│   ├── cal-shiminkaikan-fetch   飯能市民会館 公演スケジュール取得
│   ├── cal-gikai-fetch          飯能市議会 議事日程取得
│   ├── cal-shicho-blog-fetch    市長ブログ取得 + 本文掲載 (LLM 不使用)
│   ├── cal-oshirase-fetch       飯能市公式お知らせ取得 + LLM 要約
│   └── cal-translate-en         events/ 全 YAML を英訳して translations.en.* に格納
├── events/                      canonical YAML (1 イベント 1 ファイル)
│   └── <year>/<MM-DD>_<uid>.yaml
├── snapshots/                   Calendar 状態のミラー (バックアップ + 監査台帳)
│   └── <calendar-key>/events/<uid>.json
├── sources/                     クローラ用設定
│   └── hanno-tourism/urls.txt
└── .http-cache.json             HTTP Conditional GET 用 ETag / Last-Modified 永続化
```

### bin/_lib.py

各 crawler が共通利用するヘルパモジュール。引数命名規約は `s` (テキスト) / `path` (単一ファイル) / `out_dir` / `url` で統一。

| カテゴリ | 提供 |
|---|---|
| 定数 | `USER_AGENT`, `UID_NAMESPACE`, `AI_DISCLAIMER_JP` |
| HTTP fetch | `fetch(url)`, `fetch_binary(url, dest)`, `fetch_with_cache(url, etag, last_modified)` |
| HTTP cache | `load_http_cache()`, `save_http_cache(cache)`, `HTTP_CACHE_PATH` |
| HTML/text | `strip_html`, `collapse_space`, `normalize_fullwidth_digits`, `normalize_tilde`, `normalize_body`, `strip_markdown(s, bullet)` |
| HTML メタ | `infer_year_from_og(html)` |
| 暦変換 | `reiwa_to_gregorian(N)`, `gregorian_to_reiwa(year)` |
| YAML 整形 | `yaml_escape_str`, `yaml_block_scalar` |
| event YAML 操作 | `read_yaml_scalar`, `existing_content_hash_matches`, `output_path_for`, `find_existing_by_uid` |

## 認証

Google Cloud プロジェクト `city-tecoli` の Service Account
`myhanno-bot@city-tecoli.iam.gserviceaccount.com`。各カレンダーに対し
SA メアドを「予定の変更権限」(writer) で共有済み。

```
# ローカル
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/myhanno/sa.json

# CI (GitHub Actions secret に SA JSON 全文を入れる)
secrets.GWS_SA_JSON
```

`cal-myhanno` は env 未設定時に `~/.config/myhanno/sa.json` を自動 fallback する。

LLM 利用スクリプト (`cal-oshirase-fetch`, `cal-translate-en`) は
`ANTHROPIC_API_KEY` 環境変数が必要。

## 依存

- [googleworkspace/cli](https://github.com/googleworkspace/cli) (`gws`) — `brew install googleworkspace-cli`
- Python 3.10+
- `pyyaml`, `httpx`

## bin/cal-myhanno

Google Calendar 側を操作するためのコマンド群。内部で `gws` を呼ぶ。

```
cal-myhanno find [-q QUERY] [--time-min ISO] [--time-max ISO] [--json]
cal-myhanno show <event-id>
cal-myhanno set-allday <event-id> [--dry-run]                       # 時刻指定 → 終日 (marker 付き)
cal-myhanno set-timed  <event-id> [--dry-run]                       # 終日 (marker 付き) → 時刻指定
cal-myhanno fetch       [-o events] [--force] [--update-manual]     # Calendar → YAML 一括吸い上げ
cal-myhanno apply      <yaml-file> [--dry-run] [--lang LANG]        # YAML 1 件 → Calendar
cal-myhanno apply-all  [-d events] [--dry-run] [--lang LANG] [--only-managed]
                                                                    # events/ 全件 → Calendar
cal-myhanno diff       [-d events] [--lang LANG]                    # YAML と Calendar の整合チェック
cal-myhanno snapshot   [-o snapshots]                               # Calendar → JSON でバックアップ
cal-myhanno wipe       --confirm [--dry-run]                        # Calendar 全削除 (内部で先に snapshot)
```

### `--lang` (apply / apply-all / diff)

- `default` (default): YAML 直の `summary`/`description` を JP カレンダー群 (`default`/`gikai`) に反映
- `en`: YAML の `translations.en.{summary,description}` を EN カレンダー群 (`default.en`/`gikai.en`) に反映
- 翻訳未整備の YAML は skip される (apply 時は SKIPPED ログ、diff 時は対象外)

### 終日 ↔ 時刻指定の往復

`set-allday` は時刻情報を description 先頭に保存:

```
🕒 10:00–15:30

<元の description>
```

- 区切り: en dash (U+2013) を出力。パース時はハイフン/em dash/en dash いずれも受理
- TZ: カレンダー既定 (`Asia/Tokyo`) 前提
- 複数日跨ぎの時刻指定イベントは未対応

`set-timed` は marker をパースして時刻指定に戻す。

### apply / apply-all の動作

YAML を読んで `render.gcal.mode` (`single-allday` / `span-allday` / `timed`) に応じて Calendar event body を生成し、`iCalUID` で既存を検索:
- 存在しなければ `events.import` で iCalUID 付きで新規挿入
- 存在すれば `events.update` で上書き

**削除は行わない** (YAML 側で削除しても Calendar event は残る、安全策)。

### snapshot

Calendar 全イベントを JSON で `snapshots/<calendar-key>/events/<safe-iCalUID>.json` に
書き出す。stable filename なので git diff で「いつ何が変わったか」が読める。
Google が頻繁に変動させる `etag` は除外、`updated` は残す。

**真の mirror セマンティクス**: Calendar から削除されたイベントの snapshot ファイルも自動で削除 (削除自体は git history が保持)。これにより各 calendar-key 配下のファイル数は常に現在 Calendar 件数と一致する。

### wipe + apply-all による完全再構築

事故時の復旧手順:
```bash
cal-myhanno snapshot          # (念のため) 最新 snapshot
cal-myhanno wipe --confirm    # Calendar 全削除 (内部で自動 snapshot 取得)
cal-myhanno apply-all         # YAML から完全再投入 (iCalUID も復元)
cal-myhanno diff              # 整合確認 (0 件差分)
```

## bin/cal-tourism-fetch

`hanno-tourism.jp/hanno-eco/tour/<slug>/` の決定論的パーサ。LLM 不使用。

```
cal-tourism-fetch [--url URL | --urls-file PATH]
                  [--out-dir events] [--uid-prefix tourism] [--dry-run]
                  [--min-sessions 5]
```

- ページの `<dl><dt>開催日・時間</dt><dd>…</dd></dl>` を正規表現で解析
- 1 ツアー = 複数開催日のケース (`①5/9 ②5/17 ③5/25`) は **1 セッション 1 YAML** に展開
- UID: `tourism-<slug>-<YYYYMMDD>@hanno.city.tecoli.com`
- `source:` ブロックに provenance を記録 (type / id / url / fetched_at / content_hash)
- 内容に本質的変化がない場合は write 自体を skip (`existing_content_hash_matches` で `translations:` 等を温存)
- ツアー全体中止 (本文に「中止しました」等) は WARN ログを出すが Calendar には載せる (= 本文に中止表示が含まれる)
- **HTTP Conditional GET 非対応** (`hanno-tourism.jp` はサーバが ETag/Last-Modified を返さない)

URL リスト: [`sources/hanno-tourism/urls.txt`](./sources/hanno-tourism/urls.txt)。
新ツアー追加時はここに 1 行追加。

LLM 版 (ad-hoc 用、ページ構造変化時の代替) は別リポにある: `city-tecoli/tools/hanno-tourism-extractor/`。

## bin/cal-shicho-blog-fetch

飯能市長ブログ「市政一直線」(`www.city.hanno.lg.jp/.../shichoblog/`) の決定論的パーサ + 本文取り込み。LLM 不使用。

```
cal-shicho-blog-fetch [--out-dir events] [--year YYYY]
                      [--refetch-existing] [--dry-run] [--min-articles 0]
```

- 年/月 index を巡回し、各記事の本文を取得
- description に本文を取り込む:
  - 800 字以下: 全文掲載
  - 800 字超: 冒頭 ~600 字を段落境界優先で抜粋 + 「（続きはリンク先で）」
- `--refetch-existing` で既存 YAML も再評価 (本文が修正された記事の追従用)
- content_hash は (title, date, body, body_truncated) ベース → 本文変化を検知
- **HTTP Conditional GET 対応**: 各 month index の ETag を `.http-cache.json` に保存、304 受けたら article 巡回を skip (= 月途中の記事追加が無ければ article fetch 0 件)

## bin/cal-oshirase-fetch

飯能市公式サイト「新着情報」RSS パーサ + 本文取り込み + LLM 要約 (Claude Haiku 4.5)。
要約方針は [docs/ai-content-policy.md](../docs/ai-content-policy.md) 参照。

```
cal-oshirase-fetch [--out-dir events] [--refetch-existing] [--dry-run] [--min-items 0]
```

3 方式で description を生成 (本文長で自動分岐):

| method | 条件 | description |
|---|---|---|
| `url-only` | 本文抽出失敗 (<50字) | URL のみ。**LLM は呼ばない** (ハルシネーション防止の安全装置) |
| `full` | 50〜400字 | 元記事の本文をそのまま全文転載 + URL |
| `llm-haiku-4-5` | 400字超 | Claude Haiku 4.5 で要約、冒頭に「AI による要約 (正確な情報は元記事をご確認ください)」明示 |

実装ポイント:
- 本文抽出は `<div id="contents-in">` を境界に統一 (`free-layout-area` あり/なし両 HTML 構造に対応)
- LLM 出力は Markdown 記法除去 post-process あり (Google Calendar は plain text 扱い)
- content_hash は (title, date, body, method, format_version) ベース → **LLM 出力は含めない**
  - LLM 非決定性に関わらず idempotent
  - body 変化がなければ LLM を呼ばずに既存 YAML を温存
  - `DESCRIPTION_FORMAT_VERSION` 定数を bump すると wrapper 文言改変を全件に伝播
- **HTTP Conditional GET 非対応** (`feed.php` は動的生成で cache header を返さない)

`source.summary_method` フィールドに上記 method が記録される (後の再生成判定に利用)。

## bin/cal-translate-en

`events/` 全 YAML を Claude Haiku 4.5 で英訳し、各 YAML 内に
`translations.en.{summary,description,translation_hash,model,translated_at,format_version}`
を in-place 格納するスクリプト。

```
cal-translate-en [--events-dir DIR] [--dry-run] [--limit N] [--only-uid UID]
```

- 翻訳トーンは Plain English (一般読者向け、行政用語は意訳、固有名詞はローマ字)
- 出力 description の冒頭に「Automated translation (refer to source for accuracy)」disclaimer
- 元記事 URL を「Source (Japanese): URL」として末尾保持
- Markdown 記法は除去 (出力先が plain text Google Calendar 想定)
- 入力前処理: 元 description の冒頭「AI による要約…」行と末尾 URL 行は LLM に渡さない (重複翻訳防止)
- `translation_hash` は (元 summary, 元 description, format_version, lang) ベース
  - 元の日本語が変わった時のみ再翻訳
  - LLM 非決定性に関わらず idempotent
  - `TRANSLATION_FORMAT_VERSION` を bump すると wrapper 文言改変を全件に伝播

## CI (GitHub Actions)

`.github/workflows/cal-daily.yml` 1 本に統合 (毎日 03:00 JST 起動 + `calendar/bin/**` 変更時の push trigger):

1. **Pre-sync snapshot** — Calendar 状態を `snapshots/` に backup
2. **各 source crawler を順次実行** (tourism / shiminkaikan / gikai / shicho-blog / oshirase)
3. **Fetch manual edits** — Calendar UI で手動編集された event を YAML に取り込み (`--update-manual`)
4. **Safety check** — 変更ファイル数上限 / スコープ制限 / 異常検知
5. **Commit events + http-cache changes** — `events/` と `.http-cache.json` を commit + push
6. **Apply JP to Calendar (if drift)** — `--only-managed` で手動 event 温存しつつ反映
7. **Translate to English** — stale / 新規 YAML だけ `cal-translate-en` で英訳
8. **Commit translation changes** — `translations.en.*` 追加分を commit + push
9. **Apply EN to Calendar (if drift)** — `--only-managed` **無し** で適用 (= 手動 event の英訳も Calendar に届く)
10. **Post-sync snapshot** — 反映後の状態を再度 `snapshots/` に保存
11. **Discord 通知** — 当日の差分まとめを送信

### `--only-managed` の非対称性 (JP / EN)

| 言語 | `apply-all` | 理由 |
|---|---|---|
| JP (`default`) | `--only-managed` 付き | 手動 event は Calendar UI で人が編集する → CI で上書きさせない |
| EN (`en`) | filter 無し | EN は LLM 生成、人が Calendar UI で手編集する想定無し → 翻訳更新は手動 event にも届ける |

Safety policy:
- `timeout-minutes: 10` でフリーズ強制 kill
- 件数閾値 (各 fetcher の `--min-*`) で異常時 apply 拒否
  - 抽出件数 (= written + 304 skipped) で判定 (write-skip による誤発火回避)
- 変更ファイル数の上限 (events 50 / snapshots 200) で巨大誤更新を拒否
- スコープ制限 (`events/` / `snapshots/` / `.http-cache.json` 外への変更を拒否)
- `concurrency` group で並列実行禁止
- URL ホワイトリスト + canonical URL 一致でリダイレクト誤データ排除

### HTTP Conditional GET (efficiency)

city.hanno.lg.jp 配下の静的ページは ETag / Last-Modified 対応のため、`fetch_with_cache()` で 304 を受けて parse / write を全 skip。ETag / Last-Modified は `calendar/.http-cache.json` に永続化 (git で commit して CI runs 間で持続)。

対応状況:
- ✅ `cal-shiminkaikan`, `cal-gikai`, `cal-shicho-blog` (city.hanno.lg.jp)
- ❌ `cal-tourism` (`hanno-tourism.jp` がヘッダ非対応)
- ❌ `cal-oshirase` (`feed.php` は動的生成)

## YAML スキーマ例

最小例 (手動キュレーション):

```yaml
uid: "evt-20260606-01@hanno.city.tecoli.com"
summary: "西武・電車フェスタ2026 in 武蔵丘車両検修場"
location: "武蔵丘車両検修場"
dtstart: "2026-06-06"
dtend: "2026-06-06"

render:
  gcal:
    mode: single-allday
```

クローラ管理 + 本文取り込み + 英訳済み (oshirase 例):

```yaml
uid: "oshirase-13166@hanno.city.tecoli.com"
summary: "ℹ️ 課税(非課税)・所得証明書のみコンビニ交付サービスを停止します"
url: "https://www.city.hanno.lg.jp/soshikikarasagasu/sogoseisakubu/johosystem/13166.html"
dtstart: "2026-05-15"
dtend: "2026-05-15"
description: |-
  AI による要約 (正確な情報は元記事をご確認ください)

  令和8年5月31日(日曜日)〜令和8年6月2日(火曜日)終日、システム年度更新のため、…

  飯能市公式サイト 新着情報: https://www.city.hanno.lg.jp/...

render:
  gcal:
    mode: single-allday

source:                        # ← クローラ管理マーカー (手動なら無し)
  type: city-hanno-oshirase
  id: "13166"
  url: "https://www.city.hanno.lg.jp/..."
  fetched_at: "2026-05-19T..."
  content_hash: "sha256-…"
  summary_method: "llm-haiku-4-5"  # url-only | full | llm-haiku-4-5

translations:                  # ← cal-translate-en が in-place 追加
  en:
    summary: "ℹ️ Convenience store service for tax/non-taxable and income certificates suspended"
    description: |-
      Automated translation (refer to source for accuracy)

      Due to system maintenance for the annual update, …

      Source (Japanese): https://www.city.hanno.lg.jp/...
    translation_hash: "sha256-…"
    model: "claude-haiku-4-5"
    translated_at: "2026-05-19T..."
    format_version: 1
```

## 関連ドキュメント

- [docs/ai-content-policy.md](../docs/ai-content-policy.md) — LLM 要約 / 翻訳の表示方針、調査根拠 (AI事業者ガイドライン、著作権法 32 条引用、Yahoo!ニュース実例)
