# hanno-data

[city.tecoli.com/@hanno](https://city.tecoli.com/@hanno/) (「Myはんのう」) のデータソース。

飯能市および奥武蔵エリアに関する事実情報を YAML / JSON で管理し、`city-tecoli` のビルド時に取り込まれる。

## ライセンス

データは [CC0 1.0](./LICENSE) で提供する (事実情報のため)。
ただし、各データには出典 (source) を必ず明示し、利用者にも明示的な参照を推奨する。

## ディレクトリ構成

```
hanno-data/
├── schema/                       # JSON Schema (zod から参照)
│   ├── gomi-schedule.json
│   └── area-mapping.json
├── gomi/                         # 家庭ごみ収集カレンダー
│   ├── 2026/                     # 年度別の各コース YAML
│   │   ├── course-A1.yaml
│   │   ├── course-A2.yaml
│   │   └── ...
│   └── area-mapping.yaml         # 町名 → コース対応表
├── bus/                          # バス時刻表 (ファイル名 = feed_id、各 YAML の meta.feed_id と一致)
│   ├── 5931bus.yaml                       # 国際興業バス (NaviTime/5931bus 由来、native shape)
│   ├── eaglebus.yaml                      # イーグルバス飯能駅・宮沢路線 (KML+PDF 由来、legacy shape)
│   ├── hannocity-minamikoma.yaml          # 飯能市乗合ワゴン 南高麗 (GTFS-JP、native shape)
│   ├── hannocity-seimei-kaji.yaml         # 飯能市乗合ワゴン 精明・加治 (GTFS-JP、native shape)
│   ├── hannocity-haraichiba.yaml          # 飯能市乗合ワゴン 原市場 (GTFS-JP、native shape)
│   ├── seibu.yaml                         # 西武バス 飯26 (GTFS-JP, ODPT、native shape)
│   └── coords-override.yaml               # 停留所座標オーバーライド + 表記揺れ alias
├── calendar/                     # Myはんのう Google カレンダー群管理 (JP/EN × default/gikai)
│   ├── bin/cal-myhanno                    # Google Calendar API ラッパ (--lang en 対応)
│   ├── bin/cal-tourism-fetch              # hanno-tourism.jp 決定論パーサ (LLM 不使用)
│   ├── bin/cal-shiminkaikan-fetch         # 飯能市民会館 公演スケジュール
│   ├── bin/cal-gikai-fetch                # 飯能市議会 議事日程
│   ├── bin/cal-shicho-blog-fetch          # 市長ブログ + 本文取り込み (LLM 不使用)
│   ├── bin/cal-oshirase-fetch             # 飯能市公式お知らせ + LLM 要約 (Claude Haiku)
│   ├── bin/cal-translate-en               # events/ 全件英訳 → translations.en.*
│   ├── events/<year>/<MM-DD>_<uid>.yaml   # canonical YAML (1 イベント 1 ファイル)
│   ├── snapshots/<cal-key>/events/        # 各 Calendar 状態のミラー (バックアップ)
│   └── sources/hanno-tourism/urls.txt     # クローラ対象 URL リスト
├── aed/                          # AED 設置施設一覧
│   └── 2026.yaml                          # 飯能市公式サイトから抽出 + 国土地理院で geocode
└── docs/                         # 設計ドキュメント
    ├── bus-data-format.md
    ├── categories.md
    └── ai-content-policy.md
```

## 出典

### ゴミ収集カレンダー

- 飯能市公式サイト「家庭ごみ収集カレンダー」
  https://www.city.hanno.lg.jp/soshikikarasagasu/kankyokeizaibu/cleancenter/4/893.html
- 各 YAML の `metadata.source` に PDF URL と取得日時を記録する

### バス時刻表

複数ソースを系統別に併用 (各 YAML の `meta` に source 明示):

- **国際興業バス・西武バス** (主要部): NaviTime / 5931bus スクレイピング (`tools/bus-timetable-extractor/extract.py`)
- **飯能市乗合ワゴン**: [gtfs-data.jp](https://gtfs-data.jp/) GTFS-JP (CC0、配信: 一般財団法人日本バス情報協会)
- **西武バス 飯26**: [ODPT 公共交通オープンデータセンター](https://www.odpt.org/) GTFS-JP (要 ODPT_CONSUMER_KEY)
- **イーグルバス飯能駅・宮沢路線**: イーグルバス公式 Google MyMap KML + 停留所別 PDF

GTFS-JP 由来の YAML は `tools/bus-timetable-extractor/extract_gtfs.py` で生成 (city-tecoli 側)。

#### バス YAML の shape: native と legacy

`5931bus.yaml` 等の native shape は GTFS テーブルを直訳した構造 (agencies / routes /
trips / stops / stop_times / services / calendar_dates / transfers)。`eaglebus.yaml`
は legacy shape (停留所×方面で圧縮した独自形式) で、互換性維持のため当面残置。
読み込みは city-tecoli の `loadBusData()` が両 shape を吸収する。

#### Cross-feed transfer

`5931bus.yaml` の `transfers` セクションには NaviTime の ●/※ マーカー由来の
trip-level 乗り継ぎ情報を含む (例: 名栗線 ●便 → 新寺で む-ま号 中沢方面便)。これは
extract.py が む-ま号 native YAML と timing-match で合成する。

#### 設計ドキュメント

city-tecoli リポジトリ:
- [GTFS-JP import 仕様](https://github.com/tecolicom/city-tecoli/blob/main/docs/superpowers/specs/2026-05-11-gtfs-jp-import-design.md)
- [GTFS-native 内部データモデル設計](https://github.com/tecolicom/city-tecoli/blob/main/docs/superpowers/specs/2026-05-13-bus-gtfs-native-design.md)

#### データ品質チェック

city-tecoli 側で `make sanity-check` を実行すると参照整合性 / 孤児検出 / 時刻
単調性 / 緯度経度範囲 / transfer 妥当性 / 期待 fixture を一括検査できる。

### Myはんのうカレンダー

`calendar/` は `tecolicom@gmail.com` 所有の Google カレンダー群を YAML で
canonical に管理する仕組み。JP/EN 2 言語 × default/gikai 2 系統 = 4 カレンダー。
詳細は [`calendar/README.md`](./calendar/README.md) 参照。

主なソース:
- **手動キュレーション**: YAML を直接編集 (UID 形式 `evt-YYYYMMDD-NN@hanno.city.tecoli.com`)
- **飯能ツーリズム協会** (`cal-tourism-fetch`): 決定論パース、LLM 不使用
- **飯能市民会館** (`cal-shiminkaikan-fetch`): 公演スケジュール
- **飯能市議会** (`cal-gikai-fetch`): 議事日程
- **市長ブログ** (`cal-shicho-blog-fetch`): 本文込み掲載、LLM 不使用
- **飯能市公式お知らせ** (`cal-oshirase-fetch`): 長文は Claude Haiku 4.5 で要約
- **英訳** (`cal-translate-en`): 全 events の英訳を `translations.en.*` に in-place 格納

AI 生成コンテンツの表示方針は [`docs/ai-content-policy.md`](./docs/ai-content-policy.md) 参照。

CI 自動化 (GitHub Actions):
- `cal-daily.yml` (07:00 JST) — 全 fetcher 実行 → events commit → JP Calendar 反映 → snapshot
  - 英訳生成 (`cal-translate-en`) と `apply-all --lang en` は CI 未組込み (現状手動運用)

### AED 設置施設

- 飯能市公式サイト「AED 設置施設一覧」
  https://www.city.hanno.lg.jp/iryo_kenko_fukushi/iryo_kenko/iryo_iryokyufu/1/3720.html
- 緯度経度は国土地理院 [Geocoding API](https://msearch.gsi.go.jp/) で住所から付与
- 抽出日時と元 URL を YAML 先頭の `source:` ブロックに記録

## ドキュメント

- [docs/bus-data-format.md](./docs/bus-data-format.md) — バス YAML の形式リファレンス
  (native shape / legacy shape / coords-override / 各フィールドの意味)
- [docs/categories.md](./docs/categories.md) — ゴミ種別 enum の命名規則と調査
  (5374.jp、横浜市・東京 23 区・札幌市・大阪市・京都市の英語版を比較)
- [docs/ai-content-policy.md](./docs/ai-content-policy.md) — LLM 要約 / 翻訳の表示方針、
  調査根拠 (AI事業者ガイドライン、著作権法 32 条引用、Yahoo!ニュース実例)

## 編集方針

- 機械抽出 (Claude API) した結果を人間レビュー後に PR でマージ
- 直接編集する場合も schema 検証を通すこと
- 公式情報源の更新を年 1 回 (年度更新時) 突合する
