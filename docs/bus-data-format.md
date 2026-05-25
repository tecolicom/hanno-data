# バスデータ YAML 形式

`bus/` 以下の YAML ファイル形式の reference。GTFS-JP の構造に揃えた **native shape**
が現行で、`eaglebus.yaml` のみ独自圧縮の **legacy shape** で残っている。

このドキュメントはデータ subrepo 単独で完結する人間向けリファレンス。詳細設計は
city-tecoli の [GTFS-native 内部データモデル設計](https://github.com/tecolicom/city-tecoli/blob/main/docs/superpowers/specs/2026-05-13-bus-gtfs-native-design.md) 参照。

## ファイル一覧と命名

ファイル名 = `<feed_id>.yaml`、各 YAML の `meta.feed_id` と一致。

| ファイル | feed_id | shape | 出典 |
|---|---|---|---|
| `5931bus.yaml` | `5931bus` | native | NaviTime (国際興業バス公式 PWA) |
| `seibu.yaml` | `seibu` | native | ODPT 公共交通オープンデータセンター (西武バス) |
| `hannocity-haraichiba.yaml` | `hannocity-haraichiba` | native | gtfs-data.jp (飯能市む-ま号 原市場) |
| `hannocity-minamikoma.yaml` | `hannocity-minamikoma` | native | gtfs-data.jp (む-ま号 南高麗) |
| `hannocity-seimei-kaji.yaml` | `hannocity-seimei-kaji` | native | gtfs-data.jp (む-ま号 精明・加治) |
| `eaglebus.yaml` | (legacy) | legacy | イーグルバス公式 KML + PDF |
| `coords-override.yaml` | — | (override) | 手動メンテ。座標オーバーライド + 表記揺れ alias |

## ID prefix の規約

native shape の全 entity ID は `<feed_id>:<raw_id>` の prefix 付き形式。cross-feed
での collision を防ぐための規約 (例: む-ま号 haraichiba と minamikoma がいずれも
内部で `stop_id: 17_2` を使うが、prefix で区別される)。

```yaml
trip_id: 5931bus:名栗線:weekday:飯02:名栗車庫:3
route_id: 5931bus:名栗線
service_id: 5931bus:weekday
stop_id: 5931bus:00021942
```

cross-feed 参照 (主に `transfers` の `to_trip_id` 等) では別 feed の prefix が
そのまま現れる:

```yaml
transfers:
  - from_trip_id: 5931bus:名栗線:weekday:飯02:名栗車庫:3
    to_trip_id: hannocity-haraichiba:2+0+月～金+1   # 別 feed への参照
```

## native shape

GTFS-JP の各テーブルを直訳した構造。

```yaml
meta:
  feed_id: <feed_id>          # ファイル名と一致
  source: <出典の人間向け説明>
  source_url: <ダウンロード元 URL>
  extracted_at: <YYYY-MM-DD>
  license: <ライセンス名、例: CC0 1.0>
  attribution: <表記、例: 飯能市>
  feed_publisher: ...         # GTFS feed_info.txt 由来
  feed_version: ...
  feed_start_date: ...
  feed_end_date: ...

agencies:
  - agency_id: <ID、prefix なし>      # 運行会社の単一識別子
    agency_name: <例: 飯能市乗合ワゴン>
    agency_url: ...
    agency_timezone: Asia/Tokyo

routes:
  - route_id: <feed_id>:<raw>         # GTFS routes.txt の route_id
    agency_id: <agency_id>            # 上記 agencies の id
    route_long_name: <例: 名栗線>
    route_short_name: <例: 飯02> (optional)
    route_type: 3                     # バス固定
    route_color: <hex>  (optional)    # UI 色分け用
    route_text_color: <hex>  (optional)

trips:
  - trip_id: <feed_id>:<raw>
    route_id: <route_id>
    service_id: <service_id>
    trip_headsign: <例: 中沢>
    direction_id: 0 | 1               # GTFS 標準。feed 固有
    direction_name: <例: 中沢・中藤方面>  # 利用者向け方面名 (GTFS 拡張)
    # optional 将来 hooks: wheelchair_accessible, block_id, shape_id

stops:
  - stop_id: <feed_id>:<raw>
    stop_name: <例: 飯能駅 北口>
    stop_lat: <float>
    stop_lon: <float>
    location_type: 0                  # 0=停留所, 1=駅 (parent)
    parent_station: <stop_id>  (optional)
    # optional 将来 hooks: stop_code, wheelchair_boarding, tts_stop_name

stop_times:
  - trip_id: <trip_id>
    stop_sequence: <int、1 から>
    stop_id: <stop_id>
    arrival_time: <HH:MM:SS>
    departure_time: <HH:MM:SS>        # 通常 arrival と同じ
    # optional: stop_headsign, pickup_type, drop_off_type, timepoint

services:
  - service_id: <feed_id>:<raw>
    monday: 0 | 1
    tuesday: 0 | 1
    wednesday: 0 | 1
    thursday: 0 | 1
    friday: 0 | 1
    saturday: 0 | 1
    sunday: 0 | 1
    start_date: <YYYY-MM-DD>
    end_date: <YYYY-MM-DD>

calendar_dates:                       # 祝日例外、特定日の追加/削除
  - service_id: <service_id>
    date: <YYYY-MM-DD>
    exception_type: 1 | 2             # 1=add, 2=remove

transfers:
  - from_stop_id: <stop_id>
    to_stop_id: <stop_id>
    transfer_type: 0 | 1 | 2 | 3      # 1=timed (車両待つ)
    from_trip_id: <trip_id>  (optional)
    to_trip_id: <trip_id>  (optional)
    from_route_id: <route_id>  (optional)
    to_route_id: <route_id>  (optional)
    min_transfer_time: <int seconds>  (optional)
```

### `direction_name` (GTFS 非標準フィールド)

GTFS の `direction_id` は 0/1 の 2 値で、3 系統以上に分岐する路線 (む-ま号など)
を表現できないため、利用者向けの「方面」ラベルを `direction_name` で別途付与。
city-tecoli UI はこれをグルーピングキーに使う。

例: `中沢・中藤方面` / `名栗・湯の沢方面` / `原市場行政センター方面` /
    `飯能駅・東飯能駅方面`。

### Route 分類は運行会社の系統名に拘らない (synthesized routes)

`route_long_name` は運行会社の公式系統名と一致する場合もしれば、利用者目線で
切り出した「synthesized route」になる場合もある (例: `5931bus:こまニュータウン循環`)。
NaviTime course の中で複数系統が同居していて、利用者目線で別物として扱う方が
分かりやすい場合に、`tools/bus-timetable-extractor/routes-hanno-2026.yaml` の
`code_overrides` で trip code 単位に line を切り出して別 route とする。
詳細は extract.py の `assign_trip_ids` / `build_routes_from_records` 参照。

### Cross-feed transfer

`5931bus.yaml` の `transfers` は NaviTime の ●/※ マーカーから合成された
trip-level 乗り継ぎ情報を含む。例:

- 名栗線 ●便 → 新寺で む-ま号 中沢方面便 に乗り換え可
- 名栗線 ※便 → 新寺で む-ま号 行政センター便 (月水金限定) に乗り換え可

`from_trip_id` は `5931bus:` prefix、`to_trip_id` は `hannocity-haraichiba:` prefix。

## legacy shape (eaglebus.yaml のみ残置)

旧形式。停留所×方面で trip 構造を圧縮し、各 dep を直接スケジュール配列に持つ。

```yaml
meta:
  source: ...
  operator: ...
  extracted_at: ...

routes:                               # ← native の routes と意味が違う点に注意
  - line: <例: 飯能駅・宮沢路線>
    stop_id: <文字列>
    stop_name: <例: 飯能駅 北口>
    direction: <例: メッツァ・宮沢方面>
    lat: <float>
    lng: <float>
    source_url: ...
    schedule:
      weekday:
        - time: '07:02'
          route: '飯02'  (optional)
          dest: '宮沢'  (optional)
          note: '●'  (optional)        # ●=む-ま号接続、※=む-ま号接続(月水金のみ)
          trip_id: ...  (optional)
      saturday: [...]
      holiday: [...]
```

city-tecoli の `loadBusData()` は両 shape を吸収し、内部的に共通の `BusRoute[]`
形式に変換して UI に渡す (legacy はそのまま、native は adapter で展開)。

## coords-override.yaml

`stops[]` の lat/lng と stop_name を後付けで補正するためのファイル。手動メンテ。

```yaml
overrides:
  飯能駅 北口:                        # canonical な stop_name
    google_maps: <Google Maps short URL>  # 座標出典 (resolve-coords.py が再解決可)
    lat: <float>
    lng: <float>
    aliases:                          # 別表記をこの canonical 名に統一
      - 飯能駅
      - 飯能駅北口
```

normalize 規則 (loadBusData 内の自動正規化、override より先に走る):

- `（飯能市）` 末尾を削除 (西武 GTFS が他市と区別するために付ける suffix)
- `〔...〕` を `（...）` に正規化 (NaviTime と他 feed の括弧表記揺れ)

## データ品質チェック

city-tecoli 側で `make sanity-check` を実行すると、以下を一括検査:

- 参照整合性 (stop_times → trips/stops、trips → routes/services 等)
- 孤児検出 (stop_times を持たない trips、未参照 routes/services)
- ID 一意性 (cross-feed prefix 重複)
- 時刻単調性 (trip 内 stop_sequence 順で時刻が増える)
- 緯度経度範囲 (飯能エリア bbox 内)
- transfer 妥当性 (to_trip 出発 ≥ from_trip 到着)
- 期待 fixture (飯能駅 / 中沢線 / 名栗線 等の必須 entity 存在)

ダイヤ改正で再生成した後の sanity チェックに使う。
