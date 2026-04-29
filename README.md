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
├── gomi/
│   ├── 2026/                     # 年度別の各コース YAML
│   │   ├── course-A1.yaml
│   │   ├── course-A2.yaml
│   │   └── ...
│   ├── area-mapping.yaml         # 町名 → コース対応表
│   └── dictionary.yaml           # 分別事典(Phase 2)
└── spots/                        # スポットマスタ(Phase 3)
    ├── hiking/
    ├── cycling/
    └── ...
```

## 出典

- 飯能市公式サイト「家庭ごみ収集カレンダー」
  https://www.city.hanno.lg.jp/soshikikarasagasu/kankyokeizaibu/cleancenter/4/893.html
- 各 YAML の `metadata.source` に PDF URL と取得日時を記録する

## ドキュメント

- [docs/categories.md](./docs/categories.md) — ゴミ種別 enum の命名規則と調査
  (5374.jp、横浜市・東京 23 区・札幌市・大阪市・京都市の英語版を比較)

## 編集方針

- 機械抽出(Claude API)した結果を人間レビュー後に PR でマージ
- 直接編集する場合も schema 検証を通すこと
- 公式情報源の更新を年1回(年度更新時)突合する
