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
├── bus/                          # バス時刻表
│   ├── 2026.yaml                          # 国際興業バス+西武バス (NaviTime/5931bus 由来)
│   ├── 2026-eaglebus.yaml                 # イーグルバス飯能駅・宮沢路線 (KML+PDF 由来)
│   ├── 2026-hannocity-minamikoma.yaml     # 飯能市乗合ワゴン 南高麗 (GTFS-JP, gtfs-data.jp)
│   ├── 2026-hannocity-seimei-kaji.yaml    # 飯能市乗合ワゴン 精明・加治 (GTFS-JP)
│   ├── 2026-hannocity-haraichiba.yaml     # 飯能市乗合ワゴン 原市場 (GTFS-JP)
│   ├── 2026-seibu.yaml                    # 西武バス 飯26 (GTFS-JP, ODPT)
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
詳細設計は city-tecoli の [`docs/superpowers/specs/2026-05-11-gtfs-jp-import-design.md`](https://github.com/tecolicom/city-tecoli/blob/main/docs/superpowers/specs/2026-05-11-gtfs-jp-import-design.md) 参照。

## ドキュメント

- [docs/categories.md](./docs/categories.md) — ゴミ種別 enum の命名規則と調査
  (5374.jp、横浜市・東京 23 区・札幌市・大阪市・京都市の英語版を比較)

## 編集方針

- 機械抽出(Claude API)した結果を人間レビュー後に PR でマージ
- 直接編集する場合も schema 検証を通すこと
- 公式情報源の更新を年1回(年度更新時)突合する
