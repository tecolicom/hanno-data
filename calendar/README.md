# calendar/

Myはんのう Google カレンダー (`tecolicom@gmail.com` 所有、city.tecoli.com/@hanno/ から配信) を管理する仕組み一式。

## 基本方針

- **YAML が canonical**: `events/<year>/<MM-DD>_<uid>.yaml` (1 イベント 1 ファイル) が真の正本
- **Google Calendar は投影先の 1 つ**: 全イベントを終日にし、時刻情報は description 冒頭の `🕒 HH:MM–HH:MM` marker で保持
- **`source:` フィールドの有無で識別**:
  - `source:` あり → クローラ管理 (自動で更新・再生成される)
  - `source:` なし → 手動キュレーション (クローラは絶対に触らない、不可侵)

## ディレクトリ構成

```
calendar/
├── bin/
│   ├── cal-myhanno          Google Calendar API ラッパ (Python + gws)
│   └── cal-tourism-fetch    hanno-tourism.jp 専用パーサ (Python、LLM 不使用)
├── events/                  canonical YAML (1 イベント 1 ファイル)
│   └── <year>/<MM-DD>_<uid>.yaml
├── snapshots/               Calendar 状態のミラー (バックアップ + 監査台帳)
│   └── events/<uid>.json    各イベントの API JSON (stable filename → git diff 可読)
└── sources/                 クローラ用設定
    └── hanno-tourism/urls.txt
```

## 認証

Google Cloud プロジェクト `city-tecoli` の Service Account `myhanno-bot@city-tecoli.iam.gserviceaccount.com`。
カレンダー「Myはんのう」に対し SA メアドを「予定の変更権限」で共有済み。

```
# ローカル
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/myhanno/sa.json

# CI (GitHub Actions secret に SA JSON 全文を入れる)
secrets.GWS_SA_JSON
```

`cal-myhanno` は env 未設定時に `~/.config/myhanno/sa.json` を自動 fallback する。

## 依存

- [googleworkspace/cli](https://github.com/googleworkspace/cli) (`gws`) — `brew install googleworkspace-cli`
- Python 3.10+
- `pyyaml`

## bin/cal-myhanno

Google Calendar 側を操作するためのコマンド群。内部で `gws` を呼ぶ。

```
cal-myhanno find [-q QUERY] [--time-min ISO] [--time-max ISO] [--json]
cal-myhanno show <event-id>
cal-myhanno set-allday <event-id> [--dry-run]     # 時刻指定 → 終日 (marker 付き)
cal-myhanno set-timed  <event-id> [--dry-run]     # 終日 (marker 付き) → 時刻指定
cal-myhanno pull       [-o events] [--force]      # Calendar → YAML 一括吸い上げ
cal-myhanno apply      <yaml-file> [--dry-run]    # YAML 1 件 → Calendar
cal-myhanno apply-all  [-d events] [--dry-run]    # events/ 全件 → Calendar
cal-myhanno diff       [-d events]                # YAML と Calendar の整合チェック
cal-myhanno snapshot   [-o snapshots]             # Calendar → JSON でバックアップ
cal-myhanno wipe       --confirm [--dry-run]      # Calendar 全削除 (内部で先に snapshot)
```

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

Calendar 全イベントを JSON で `snapshots/events/<safe-iCalUID>.json` に書き出す。stable filename なので git diff で「いつ何が変わったか」が読める。Google が頻繁に変動させる `etag` は除外、`updated` は残す。

**真の mirror セマンティクス**: Calendar から削除されたイベントの snapshot ファイルも自動で削除 (削除自体は git history が保持)。これにより `snapshots/events/` のファイル数は常に現在 Calendar 件数と一致する。

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
- 内容に本質的変化がない場合は `fetched_at` を流用 (git diff ゼロを維持)

URL リスト: [`sources/hanno-tourism/urls.txt`](./sources/hanno-tourism/urls.txt)。新ツアー追加時はここに 1 行追加。

LLM 版 (ad-hoc 用、ページ構造変化時の代替) は別リポにある: `city-tecoli/tools/hanno-tourism-extractor/`。

## CI (GitHub Actions)

`.github/workflows/`:

| workflow | 時刻 (JST) | 役割 |
|---|---|---|
| `cal-snapshot.yml` | 06:00 | Calendar → `snapshots/` 取得、変化があれば commit |
| `cal-tourism-crawl.yml` | 07:00 | hanno-tourism.jp を fetch、`events/` に commit |
| `cal-sync.yml` | 08:00 | `events/` → Google Calendar に反映 (drift 検出時のみ apply) |

各 workflow に Safety check:
- `timeout-minutes: 5-8` でフリーズ強制 kill
- 件数閾値 (min-sessions / YAML 数の上下限) で異常時 apply 拒否
- 変更ファイル数の上限 (crawl 30 / snapshot 100) で巨大誤更新を拒否
- スコープ制限 (`events/` or `snapshots/` 外への変更を拒否)
- `concurrency` group で並列実行禁止
- URL ホワイトリスト + canonical URL 一致でリダイレクト誤データ排除
- 時刻 / 日付 / 年範囲 validation で入力ミス由来の不正データ排除

## YAML スキーマ例

```yaml
uid: "tourism-ec-chokotto-tenranzan-syoka-20260509@hanno.city.tecoli.com"
summary: "ちょこっとお手軽ツアー〜天覧山〜"
location: "集合 飯能市立博物館前（…）"
url: "https://hanno-tourism.jp/hanno-eco/tour/ec-chokotto-tenranzan-syoka/"
dtstart: "2026-05-09T14:00:00+09:00"
dtend: "2026-05-09T16:00:00+09:00"
description: |-
  …

render:
  gcal:
    mode: single-allday        # single-allday | span-allday | timed
    time_marker: "14:00–16:00" # description 冒頭に挿入

source:                        # ← クローラ管理マーカー (手動なら無し)
  type: hanno-tourism-jp
  id: "ec-chokotto-tenranzan-syoka"
  url: "https://hanno-tourism.jp/hanno-eco/tour/ec-chokotto-tenranzan-syoka/"
  fetched_at: "2026-05-16T15:09:05Z"
  content_hash: "sha256-…"     # 抽出後データの hash (HTML 変動に左右されない)
```
