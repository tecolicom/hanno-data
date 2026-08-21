# hanno-data

[city.tecoli.com/@hanno](https://city.tecoli.com/@hanno/) (「Myはんのう」) のデータソース。

飯能市および奥武蔵エリアに関する事実情報を YAML / JSON で管理し、`city-tecoli` のビルド時に取り込まれる。

## ライセンス

データは [CC0 1.0](./LICENSE) で提供する (事実情報のため)。
ただし、各データには出典 (source) を必ず明示し、利用者にも明示的な参照を推奨する。

## ディレクトリ構成

```
hanno-data/
│                                 # (ごみ関連は収集日程・分別辞典とも japan-gomi-data へ移管済み)
├── bus/                          # バス時刻表 (ファイル名 = feed_id、各 YAML の meta.feed_id と一致)
│   ├── 5931bus.yaml                       # 国際興業バス (NaviTime/5931bus 由来、native shape)
│   ├── eaglebus.yaml                      # イーグルバス飯能駅・宮沢路線 (KML+PDF 由来、legacy shape)
│   ├── hannocity-minamikoma.yaml          # 飯能市乗合ワゴン 南高麗 (GTFS-JP、native shape)
│   ├── hannocity-seimei-kaji.yaml         # 飯能市乗合ワゴン 精明・加治 (GTFS-JP、native shape)
│   ├── hannocity-haraichiba.yaml          # 飯能市乗合ワゴン 原市場 (GTFS-JP、native shape)
│   ├── seibu.yaml                         # 西武バス 飯26 (GTFS-JP, ODPT、native shape)
│   └── coords-override.yaml               # 停留所座標オーバーライド + 表記揺れ alias
├── calendar/                     # Google カレンダー群管理 (JP/EN × default/gikai + 店舗カレンダー)
│   ├── bin/cal-gcal                    # Google Calendar API ラッパ (--lang en 対応)
│   ├── bin/cal-tourism-fetch              # hanno-tourism.jp の tour、決定論パーサ (LLM 不使用)
│   ├── bin/cal-tourism-news-fetch         # hanno-tourism.jp の news、LLM 抽出 + 機械検算
│   ├── bin/cal-shiminkaikan-fetch         # 飯能市民会館 公演スケジュール
│   ├── bin/cal-gikai-fetch                # 飯能市議会 議事日程
│   ├── bin/cal-shicho-blog-fetch          # 市長ブログ + 本文取り込み (LLM 不使用)
│   ├── bin/cal-oshirase-fetch             # 飯能市公式お知らせ + LLM 要約 (Claude Haiku)
│   ├── bin/cal-cci-chef-fetch             # 商工会議所 日替わりシェフ当番表 (集合同期型、LLM 不使用)
│   ├── bin/cal-translate-en               # events/ 全件英訳 → translations.en.*
│   ├── sources.yaml                       # クローラの source 別 city 固有設定 (多都市化用)
│   ├── events/<year>/<MM-DD>_<uid>.yaml   # canonical YAML (1 イベント 1 ファイル)
│   ├── snapshots/<cal-key>/events/        # 各 Calendar 状態のミラー (バックアップ)
│   ├── sources/hanno-tourism/urls.txt     # 手動ピン留めのシード (通常は REST API で足りる)
│   ├── .http-cache.json                   # URL ごとの ETag / Last-Modified / modified_gmt
│   └── tests/                             # golden 回帰テスト + ユニットテスト (ネットワーク非依存)
├── aed/                          # AED 設置施設一覧
│   └── 2026.yaml                          # 飯能市公式サイトから抽出 + 国土地理院で geocode
└── docs/                         # 設計ドキュメント
    ├── bus-data-format.md
    ├── categories.md
    └── ai-content-policy.md
```

## 出典

### ごみ (収集日程・分別事典) — 全て japan-gomi-data へ移管済み

**このリポジトリにごみ関連データは無い。** 収集日程 (コース別カレンダー) と
分別事典 (567 品目) はいずれも
[tecolicom/japan-gomi-data](https://github.com/tecolicom/japan-gomi-data) の
`municipalities/saitama/hanno/` にある。

分別事典は当初「japan-gomi-data の scope (収集日程 + 種別定義) の外」として
こちらに残していたが、2026-08 に移管した。**`category` の正典
(`schema/categories.yaml`) が向こうにあるため、別リポジトリでは誰も検査できて
いなかった**のが理由。実際 `not_collected` (45 品目) / `drop_off_only` (9) /
`reference` (15) の 3 キーが正典に無く、アプリ側が独自の表で補って二重管理に
なっていた。移管に合わせて `schema/disposal.yaml` (処分可否を別の軸として定義)
が新設され、未知の category・taxonomy 外の収集種別・同名品目の重複で検査が
止まるようになっている。

> **ライセンス注意**: 分別事典は移管先で `source.license:
> proprietary-municipality` を宣言しており、リポジトリ全体のライセンスの対象外
> として扱われている。飯能市は
> [ホームページについて](https://www.city.hanno.lg.jp/shiseijoho/koho_johohasshin_hodohappyo/johohasshin/5027.html)
> で諸権利の帰属を定めており、政府標準利用規約も CC BY も採用していない。
> 567 品目の選択・配列と note の文言は市の著作物になりえる。市への照会は
> japan-gomi-data 側で進行中。

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
canonical に管理する仕組み。JP/EN 2 言語 × default/gikai 2 系統 = 4 カレンダーに
加え、店舗カレンダー `chef` (日替わりシェフレストラン、EN なし) と
`cci` / `cci.en` (商工会議所からのお知らせ) の計 7 本。
詳細は [`calendar/README.md`](./calendar/README.md) 参照。

主なソース:
- **手動キュレーション**: YAML を直接編集 (UID 形式 `evt-YYYYMMDD-NN@hanno.city.tecoli.com`)
- **飯能ツーリズム協会 / ツアー** (`cal-tourism-fetch`): 決定論パース、LLM 不使用。WordPress REST API で一覧と更新日時を取得し、変更のあったページだけ HTML を取る
- **飯能ツーリズム協会 / お知らせ** (`cal-tourism-news-fetch`): 祭り・盆踊り等の単発イベント告知が載る `news` 投稿タイプ。1 記事から「告知」(掲載日) と「本番」(開催日) の最大 2 イベントを作る。開催日は Claude Haiku 4.5 の抽出をコード側で検算し、根拠文字列の実在・曜日・和暦換算などが全て通ったものだけ採用する
- **飯能市民会館** (`cal-shiminkaikan-fetch`): 公演スケジュール
- **飯能市議会** (`cal-gikai-fetch`): 議事日程
- **市長ブログ** (`cal-shicho-blog-fetch`): 本文込み掲載、LLM 不使用。incremental mode (dtstart=取得日) で バックデート公開も新着として拾う
- **飯能市公式お知らせ** (`cal-oshirase-fetch`): 長文は Claude Haiku 4.5 で要約。同じ記事が更新されたら `source.supersedes` で前世代を辿れ、`description` 冒頭に「前回掲載日」と LLM 生成の「主な変更」が付く
- **飯能商工会議所 / 日替わりシェフレストラン** (`cal-cci-chef-fetch`): **集合同期型の新系統**。ページに埋め込まれた FullCalendar の JSON を決定論パース (LLM 不使用)。既存クローラが「記事 1 本 = イベント 1 個」の追記型なのに対し、こちらは 1 ページに全件が載るので**取得側に無い予定は削除する**。誤削除を防ぐため、削除は取得範囲内かつ今日以降のものに限り、件数が上限を超えたら何も書かずに中止する
- **飯能商工会議所 / 告知** (`cal-cci-event-fetch`): カテゴリ別 **RSS** (`xo_event_cat/<slug>/feed/`)。お知らせ・セミナー・経営支援・地域振興の 4 カテゴリ (**検定は除外** — 大半が合格者番号発表で、掲載日に載せても「その日に何かが起きる」わけではない)。長文は Claude Haiku で要約。**開催日は取れない** (postmeta にあり REST も RSS も出さない) ので dtstart は掲載日。
  **⚠️ CI では未有効化** — WordPress REST API (`/wp-json/`) が GitHub Actions の IP (米国) から遮断されるため RSS に切り替えた。RSS が CI から通るかは未確認。手元 (日本の回線) からは動く。詳細と経緯は [`calendar/README.md`](./calendar/README.md)
- **英訳** (`cal-translate-en`): 全 events の英訳を `translations.en.*` に in-place 格納。ただし EN カレンダーを持たない source (`hanno-cci-chef`) は除外

AI 生成コンテンツの表示方針は [`docs/ai-content-policy.md`](./docs/ai-content-policy.md) 参照。

CI 自動化 (GitHub Actions):
- `cal-daily.yml` (03:00 JST + `calendar/bin/**` push trigger) — 全 fetcher 実行 → **`cal-gcal prune` で削除を Calendar へ伝播** → events commit → JP Calendar 反映 → `cal-translate-en` で英訳 → translations commit → EN Calendar 反映 → snapshot
  - **prune は `fetch --update-manual` より前に置く必要がある。** 後ろだと、YAML を消したのに Calendar に残った孤児を `fetch` が `source:` なしの YAML として拾い、以後「手動キュレーション = 不可侵」扱いになって二度と削除できなくなる (詳細は [`calendar/README.md`](./calendar/README.md) の「クローラの 2 系統」)
- `cal-golden-test.yml` (`calendar/bin/**` / `sources.yaml` / `tests/**` の push・PR) — `calendar/tests/run-golden` でクローラ出力 YAML がバイト一致で維持されているか hermetic 検証 (カレンダー氾濫の回帰防止) + `calendar/tests/test_*.py` のユニットテスト実行

golden 網とは別に、純粋関数・API ラッパのユニットテストが `calendar/tests/test_*.py` にある
(すべてネットワーク非依存)。一覧は [`calendar/README.md`](./calendar/README.md) の
「テスト (golden 網)」参照。

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
- 公式情報源の更新を年 1 回 (年度更新時) 突合する
