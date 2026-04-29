# ゴミ収集データの英語カテゴリ命名規則

本リポジトリ(hanno-data)が提供するゴミ収集スケジュール YAML で使うゴミ種別の
英語識別子(snake_case enum)について、設計判断と調査の記録。

> このドキュメントは [CC0 1.0](../LICENSE) で提供する。
> 他の自治体オープンデータや civic tech プロジェクトでの参考利用を歓迎する。

---

## 採用する enum

```
burnable        可燃ごみ          Burnable garbage
non_burnable    不燃ごみ          Non-burnable garbage
plastic         プラスチック類    Plastic containers / packaging
pet_bottle      ペットボトル      PET bottle
beverage_can    飲料缶            Beverage can
glass_bottle    びん              Glass bottle
paper_cloth     紙・布            Paper and cloth
hazardous       有害ごみ          Hazardous waste
oversized       粗大ごみ          Oversized garbage
```

> 注: 飯能市の PDF は日本語側で「有害ごみ」と表記している(「危険物」とは書いていない)。
> 内容は意味的に hazardous(発火性・刃物・電池等の物理的危険物)に該当するため、
> 英語 enum は `hazardous` を採用。日本語ラベルは PDF 表記に合わせて「有害ごみ」を使う。

JSON Schema 上の正規定義は [`schema/gomi-schedule.json`](../schema/gomi-schedule.json) を参照。

---

## 設計方針

1. **意味的に正確であること**
   自治体ごとに微妙に異なる運用(同じ「缶」でも飲料缶のみか、缶詰の缶を含むか等)を
   汎用 enum が握り潰さないよう、必要に応じて細分化する。

2. **snake_case**
   JSON Schema / Zod / TypeScript / Python のいずれでも扱いやすい形式に統一。

3. **複数自治体の英語表記の最大公約数を採用**
   横浜市・東京 23 区・札幌市・大阪市・京都市の英語版ガイドで一致する用語を優先。
   どれか一つの市の独自用語に過剰に寄せない。

4. **civic tech の既存実装と非衝突**
   後述の 5374.jp は日本語文字列をそのまま使っており、英語 enum の業界標準は
   存在しない。本提案はそうした空白の中での pragmatic な合意提案。

---

## 調査 1: 5374.jp(Code for Kanazawa)

[5374.jp](https://5374.jp/) は Code for Kanazawa が原作の日本各地ゴミ収集日アプリ。
複数都市で派生実装されている代表的 civic tech プロジェクト。

- リポジトリ: https://github.com/codeforkanazawa-org/5374

**カテゴリは日本語文字列のまま CSV に格納される**:
- `data/area_days.csv` のヘッダ: `燃やすごみ, 燃やさないごみ, 資源, びん`
- `data/target.csv` の `label` 列: 日本語値
- `js/script.js` の `TrashModel` クラスはラベルを free-form 文字列として消費

→ **英語識別子の de facto 標準は存在しない。**
civic tech の慣行は「日本語ラベルをそのまま保存」。

本リポジトリは静的サイトビルドや ICS 出力等のためのコード上の扱いやすさを優先して
英語 enum を採用するが、表示層では `categoryLabels` で日本語ラベルに変換する。

---

## 調査 2: 主要自治体の英語版表記

各市の公式英語版ページや英語パンフレットから抽出。同じ日本語に対する英訳が
バラついていることが分かる。

| 日本語 | 横浜市 | 東京 23 区(集計) | 札幌市 | 大阪市 | 京都市 |
|---|---|---|---|---|---|
| 可燃ごみ | Burnable garbage | Burnable / Combustible | Burnable | Household waste | Combustible |
| 不燃ごみ | Non-burnable garbage | Non-combustible | Non-burnable | (粗大等に集約) | (主要分類なし) |
| プラスチック | Plastic resources | Plastic | (Recyclables) | Plastic Containers and Packaging | Plastic containers and packages |
| ペットボトル | (缶・びんと統合) | Plastic bottle | (Recyclables) | Plastic Bottles (PET) | (缶・びんと統合) |
| 飲料缶 | (缶・びんと統合) | Cans / Aluminum can | (Recyclables) | Cans | (缶・びんと統合) |
| びん | Glass bottles | Glass | (Recyclables) | Bottles | (缶・びんと統合) |
| 粗大ごみ | Oversized garbage | Oversized refuse | Bulky waste | Bulky Waste | Furniture etc. |
| 危険物 / 有害ごみ | Batteries / Spray cans 等に細分化 | Hazardous | "Kiken" 表示 | "Kiken" 表示 | 個別分類 |

出典は [§出典](#出典) 参照。

### 主要自治体の特徴

- **`Burnable` / `Non-burnable` 系が多数派**(横浜・札幌・東京 23 区)。
  `Combustible` も使われるが少数派。
- **`Oversized` と `Bulky` は拮抗**。横浜・東京 23 区は Oversized、大阪・札幌は Bulky。
- **缶・びん・ペットボトルを 1 カテゴリに統合する自治体**(横浜・札幌・京都)と
  **個別カテゴリで分ける自治体**(大阪・東京 23 区の一部・飯能市)に分かれる。
- **危険物 / 有害ごみ**は自治体ごとの差が大きい。横浜のように電池・スプレー缶・
  小型金属を独立カテゴリに分ける運用、東京 23 区のように `Hazardous` で総称する運用、
  通常袋に「危険」と書いて出す運用などが混在。

---

## 各カテゴリの選定根拠

### `burnable` / `non_burnable`(可燃 / 不燃)

横浜市・札幌市・東京 23 区の英語版で `Burnable` / `Non-burnable` が標準。
`Combustible` も誤りではないが少数派のため不採用。

### `plastic`(プラスチック類)

容器包装プラスチック・プラスチック資源・プラスチックごみ等、各自治体で
微妙に異なるが、共通項として `plastic` で統一。

### `pet_bottle`(ペットボトル)

「プラスチックボトル」(plastic bottle)でも通じるが、日本では一般的に
**ペットボトル(PET = polyethylene terephthalate の略)**と呼ばれており、
飲料用 PET ボトルに限定された分別運用がほぼすべての自治体で行われている。
東京・大阪の英語版でも "PET bottles" / "Plastic bottles (PET)" の表記。
本スキーマでは `pet_bottle` を採用。

### `beverage_can`(飲料缶)— ⚠️ Hanno 固有の判断

汎用的な `can` ではなく **`beverage_can`(飲料缶)** とした理由:

- 飯能市では「飲料缶の日」は文字通り飲料用のアルミ缶・スチール缶のみ回収する
- それ以外の金属缶は別のカテゴリに振り分けられる:
  - **缶詰の缶**(食品缶)・空きペンキ缶等 → `non_burnable`(不燃ごみ)
  - **スプレー缶**(発火/爆発の危険) → `hazardous`(有害ごみ)
- 単に `can` とすると「全ての金属缶」という誤読を招く

この区別が無い自治体では `beverage_can` を「全ての飲料缶」と読めば矛盾しない。
区別がある自治体ではこの enum で意味を保てる。汎用 `can` を選ぶよりも安全。

### `glass_bottle`(びん)

横浜・大阪が `Glass bottles` を使用。`bottle` 単独では `pet_bottle` との混同が
生じうるため、ガラス瓶であることを明示。

### `paper_cloth`(紙・布)

飯能市の運用では紙類と布類が同日収集・同一カテゴリ。両者を分けるべき自治体では
将来的に `paper` と `cloth` を別 enum として追加すれば良い。

### `hazardous`(有害ごみ)— enum と日本語ラベルでズレあり

- **enum**: `hazardous`(物理的危険物 = 発火性・電池・刃物等)
- **日本語ラベル**: 「有害ごみ」(飯能市 PDF の表記そのまま)

英語と日本語で意味のニュアンスが微妙に違う点に注意:

- 英語の `hazardous` = 物理的危険(発火・爆発・刃物)
- 英語の `harmful` = 化学的・毒性的に有害(蛍光灯、水銀、農薬)

飯能市はこのカテゴリに**ライター・スプレー缶・電池**等の発火/爆発リスクがある物を含める。
缶詰の缶等の単純な金属缶は不燃ごみ(`non_burnable`)で、有害ごみには含まれない。
内容は意味的に `hazardous` に対応するため、英語 enum はそちらを採用。

一方、日本語の表示ラベルは PDF と運用に合わせて「有害ごみ」と表記する:
- 「危険物」と表示すると、住民にとって不燃ごみとの区別が付きにくい
- 飯能市の PDF も一貫して「有害」と表記している

将来、化学的な有害ごみ(蛍光灯・水銀等)を別カテゴリにしたい自治体が現れた場合は、
`harmful` を別 enum として追加する(現時点では未使用)。

### `oversized`(粗大ごみ)

横浜市・東京 23 区が `Oversized garbage / refuse`、大阪・札幌が `Bulky waste`。
拮抗しているが横浜・東京の方が広域人口をカバーしているため `oversized` を採用。
意味上はどちらでも通じる。

---

## 飯能市固有のメモ

飯能市の公式英語版ページが Google 翻訳出力をそのまま使用しているため、
英語表記は信頼できる固定の出典として扱わない。

飯能市のカテゴリ運用に関する固有の判断:

- **缶詰の缶・スプレー缶は「危険物」**(`hazardous`)。
  飲料缶の日には出せない。
- **びんと飲料缶は別の収集日**。色も別(凡例で確認)。
- **粗大ごみは申込制ではなく定期収集**。
  第 1 水曜(不燃・有害と同日)と第 3 月曜(可燃と同日)の 2 スロット運用が
  確認されている(コース A-2 中央南の 2026 年度時点)。

---

## 将来追加候補(必要になり次第)

| 日本語 | enum 候補 | 想定自治体 |
|---|---|---|
| 有害ごみ(蛍光灯・水銀) | `harmful` | 横浜・東京等で 危険物 と区別される場合 |
| スプレー缶 | `spray_can` | 単独カテゴリ運用の自治体 |
| 電池 | `battery` | 同上 |
| 小型金属 | `small_metal` | 横浜等 |
| 衣類 | `clothing` | 一部自治体 |
| 古紙 | `paper` | 紙と布を分ける自治体 |
| 古布 | `cloth` | 同上 |

これらを追加する際は本ドキュメントを更新すること。

---

## 出典

### 5374.jp / Code for Kanazawa
- リポジトリ: https://github.com/codeforkanazawa-org/5374
- 関連ファイル: `data/area_days.csv`, `data/target.csv`, `data/description.csv`,
  `js/script.js`, `LOCALIZE_en.md`

### 自治体英語版ガイド
- 横浜市: https://www.city.yokohama.lg.jp/lang/residents/en/garbage/sortinganddisposal.html
- 大阪市(英語版 PDF): https://www.city.osaka.lg.jp/contents/wdu020/enjoy/en/environment1.pdf
- 京都市(京都留学生ガイド): https://www.studykyoto.jp/en/currentstudents/kyotolife/trash/
- 札幌市英語版: https://www.city.sapporo.jp.e.ain.hp.transer.com/seiso/gomi/wakekata.html
- 東京 23 区(集計): https://resources.realestate.co.jp/living/how-to-sort-garbage-in-japan-official-english-guidelines-for-garbage-disposal-in-tokyo-by-ward/

### 飯能市
- 家庭ごみ収集カレンダー一覧: https://www.city.hanno.lg.jp/soshikikarasagasu/kankyokeizaibu/cleancenter/4/893.html

---

## 更新履歴

- **2026-04-29**: 初版作成。9 カテゴリの enum を確定。
