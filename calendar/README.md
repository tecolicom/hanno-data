# calendar/

Myはんのう Google カレンダー (`tecolicom@gmail.com` 所有) の編集ツール。

## 構成

```
calendar/
├── bin/cal-myhanno    Myはんのう 固定の薄いラッパ
└── sources/           (未実装) 外部ソースのスクレイパ
```

汎用 CLI は [googleworkspace/cli](https://github.com/googleworkspace/cli) (`gws`) をそのまま使う。`cal-myhanno` は Myはんのう カレンダー ID と認証パスのデフォルト値を詰め、終日 ↔ 時刻指定の往復のような頻出操作だけを実装する。

## 認証

Service Account (`myhanno-bot@city-tecoli.iam.gserviceaccount.com`) の JSON key を使う。
カレンダーは「Myはんのう」に対し SA メアドを「予定の変更権限」で共有済み。

ローカル:

```
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/myhanno/sa.json
```

`cal-myhanno` は env が未設定でも `~/.config/myhanno/sa.json` を自動で試す。

CI (将来):

```yaml
- run: |
    echo "$GWS_SA_JSON" > /tmp/sa.json
    export GOOGLE_APPLICATION_CREDENTIALS=/tmp/sa.json
    calendar/bin/cal-myhanno find
  env:
    GWS_SA_JSON: ${{ secrets.GWS_SA_JSON }}
```

## 依存

- `gws` (`brew install googleworkspace-cli`)
- Python 3.10+

## コマンド

```
cal-myhanno find [-q QUERY] [--time-min ISO] [--time-max ISO] [--json]
cal-myhanno show <event-id>
cal-myhanno set-allday <event-id> [--dry-run]
cal-myhanno set-timed  <event-id> [--dry-run]
```

## 終日化フォーマット

`set-allday` は元の時刻情報を description 冒頭に挿入してから終日化する。

```
🕒 10:00–15:30

<元の description>
```

- 改行: 1 行目が marker、空行 1 つ、その下が元の description
- 区切り: en dash (U+2013) を出力。パース時はハイフン/em dash/en dash いずれも受理
- TZ: 現状はカレンダー既定 (`Asia/Tokyo`) 前提
- 複数日跨ぎの時刻指定イベント: 未対応 (エラー)

`set-timed` は marker をパースして時刻指定に戻す (description は marker 部分を除去して復元)。
