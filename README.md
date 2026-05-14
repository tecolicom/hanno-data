# hanno-data

[hanno.tecoli.com](https://hanno.tecoli.com) のデータソース。

飯能市および奥武蔵エリアに関する事実情報を YAML / JSON で管理し、`hanno-tecoli` のビルド時に取り込まれる。

## ライセンス

データは [CC0 1.0](./LICENSE) で提供する(事実情報のため)。
ただし、各データには出典(source)を必ず明示し、利用者にも明示的な参照を推奨する。

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
│   ├── area-mapping.yaml         # 町名 → コース対応表
│   └── dictionary.yaml           # 分別事典(Phase 2)
├── bus/                          # バス時刻表 (ファイル名 = feed_id、各 YAML の meta.feed_id と一致)
│   ├── 5931bus.yaml                       # 国際興業バス (NaviTime/5931bus 由来、native shape)
│   ├── eaglebus.yaml                      # イーグルバス飯能駅・宮沢路線 (KML+PDF 由来、legacy shape)
│   ├── hannocity-minamikoma.yaml          # 飯能市乗合ワゴン 南高麗 (GTFS-JP、native shape)
│   ├── hannocity-seimei-kaji.yaml         # 飯能市乗合ワゴン 精明・加治 (GTFS-JP、native shape)
│   ├── hannocity-haraichiba.yaml          # 飯能市乗合ワゴン 原市場 (GTFS-JP、native shape)
│   ├── seibu.yaml                         # 西武バス 飯26 (GTFS-JP, ODPT、native shape)
│   └── coords-override.yaml               # 停留所座標オーバーライド + 表記揺れ alias
├── aed/                          # AED 設置場所 (リンクのみ、本リポジトリでは未管理)
└── spots/                        # スポットマスタ(Phase 3、計画中)
    ├── hiking/
    ├── cycling/
    └── ...
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

## ドキュメント

- [docs/categories.md](./docs/categories.md) — ゴミ種別 enum の命名規則と調査
  (5374.jp、横浜市・東京 23 区・札幌市・大阪市・京都市の英語版を比較)

## 編集方針

- 機械抽出(Claude API)した結果を人間レビュー後に PR でマージ
- 直接編集する場合も schema 検証を通すこと
- 公式情報源の更新を年1回(年度更新時)突合する
