# gomi (飯能市ごみ)

## 収集日程 (コース別カレンダー) は japan-gomi-data へ移行しました

飯能市のごみ収集日程は、全自治体を集約する公開オープンデータリポジトリ
**[japan-gomi-data](https://github.com/tecolicom/japan-gomi-data)** の
`municipalities/hanno/` を正典とします (2026-07-12 移行, CC BY 4.0)。
city.tecoli の `make data-sync` はそちらから vendoring します。

**旧 `course-A1〜B3.yaml` は削除しました** (このリポジトリで編集しても反映されません)。
日程の更新・追加は japan-gomi-data 側で行ってください。

## このディレクトリに残すもの (飯能固有・japan-gomi-data のスコープ外)

- `bunbetsu-jiten.yaml` — ごみ分別事典 (品目→種別、567項目)。japan-gomi-data は
  「収集日程 + 種別定義」のみを収録し分別辞書は対象外のため、飯能固有データとして
  ここに残す。city.tecoli の `@hanno/gomi/search` が `make data-sync` の overlay 経由で使用。
- `area-mapping.yaml` — 町名→コース対応 (ドラフト、現状 app 未使用)。
- `sources.yaml` — 旧コース PDF の出典一覧 (参考)。
