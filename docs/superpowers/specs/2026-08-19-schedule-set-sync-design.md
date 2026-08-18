# 集合同期型クローラ (schedule set sync) — 設計

ステータス: 設計 (2026-08-19 起案)。実装は未着手。

第一の利用者は飯能商工会議所「日替わりシェフレストラン」の当番表。ただし本設計の
主眼は**クローラの新系統を立てる**ことにあり、シェフの店はその最初の 1 例である。

## 1. 背景

`calendar/bin/cal-*-fetch` は現在 6 本あるが、すべて**記事 1 本 = イベント 1 個**の
**追記型**である。記事が増えれば YAML が増え、消えたものは判別できない (元記事が
取り下げられたのか、単に一覧から溢れたのかを区別する材料がない)。

一方、飯能商工会議所が配布する日替わりシェフの当番表は性質が違う。**1 ページに
全期間の予定が集合として載り、毎回まるごと差し替わる**。ゴミ収集日程や時刻表と
同じ「あらかじめ確定した表」であり、1 件ごとに固有の物語がない。

この系統には既に 1 例がある。**`cal-shiminkaikan-fetch`** (飯能市民会館 催し物
予定表) は 1 ページの `<table>` に全予定が載るソースを扱っており、追記型の枠に
無理に載せている。中止になった公演が残り続ける構造的な弱点を抱えている。

調査で見つかった同系統の候補:

| ソース | 形式 |
|---|---|
| 商工会議所 日替わりシェフレストラン | FullCalendar の `events:` に JSON を直接埋め込み |
| 飯能市民会館 催し物予定表 | 1 ページの `<table>` (実装済み・追記型のまま) |
| 商工会議所 イベントカレンダー `/event-calendar/` | XO Event Calendar。`admin-ajax.php?action=xo_event_calendar_month` が月次グリッドを返す |
| 飯能市立図書館 開館日カレンダー | Angular SPA (`ilisod011.apsel.jp/hanno/calendars`)。裏の JSON API は未調査 |
| ごみ収集カレンダー | japan-gomi-data で表として管理済み (この系統の先例) |

## 2. 目的と非目的

**目的**

- 集合として配布される予定表を扱う共通の枠組みを `calendar/` に立てる
- その最初の利用者として日替わりシェフレストランを実装する
- 予定表から消えた予定を Google カレンダーまで確実に伝播させる

**非目的 (今回やらない)**

- `cal-shiminkaikan-fetch` の移行。枠組みが新規ソースで動くことを確認してから別途行う
- 図書館・商工会議所イベントカレンダーの取り込み
- 公民館「センターだより」等の PDF ソース
- 英訳。§8 参照

## 3. 系統の定義

| | 追記型 (既存 6 本) | 集合同期型 (本設計) |
|---|---|---|
| 配布単位 | 記事 1 本 = イベント 1 個 | 1 エンドポイントに全件 |
| UID の根拠 | 記事 ID | 日付 + 連番 |
| 消えたものの解釈 | **判別不能** | **不在 = 予定から外れた** |
| 同期 | upsert | **upsert + prune** |
| 該当 | tourism / tourism-news / oshirase / shicho-blog / gikai / shiminkaikan | **cci-chef** (将来 shiminkaikan) |

## 4. 危険な相互作用 — 削除したイベントの蘇生

**この設計で最も注意を要する点**であり、実装順序を規定する。

`cal-daily.yml` はクローラ群の後に `cal-myhanno fetch --update-manual` を走らせる。
これは「Calendar 上にあって YAML に無い event を新規 YAML 化」する経路である。
生成される YAML は `event_to_yaml()` が作るため **`source:` ブロックを持たない**
(Google 側の `source.url` は `url:` に落ちるだけ)。

したがって素朴に「クローラが YAML を消す」だけだと、同じ CI 実行内で:

```
crawler が YAML 削除
  → Calendar には残存
  → fetch --update-manual が拾う
  → source: なしの YAML として復活
  → 以後「手動キュレーション」扱いで不可侵
  → クローラは二度と触れず、Calendar に永久に残る
```

**削除したはずの予定が、不可侵な手動イベントとして蘇生する。**

対策: Calendar からの削除 (prune) を **`fetch --update-manual` より前**に置く。
CI のステップ順序がこの設計の一部である (§9)。

## 5. データフロー

```
商工会議所ページ (HTML 埋め込み JSON)
  ↓  cal-cci-chef-fetch      決定論パース (LLM 不使用)
  ↓  _lib.sync_set()          集合照合 → 追加 / 更新 / 削除
calendar/events/<year>/<MM-DD>_chef-*.yaml      ← canonical
  ↓  cal-myhanno prune        YAML に無い Calendar event を削除 (UID prefix 限定)
  ↓  cal-myhanno apply-all    upsert
Google Calendar「📍 日替わりシェフレストラン」
  ↓  city-tecoli が google_calendar_id 経由で読む
飯能商工会議所の店舗ページ
```

## 6. ソースの実態

取得元: `https://www.hanno-cci.or.jp/manage/founded/` の `#02` セクション。

FullCalendar の初期化コードに `events:` として JSON 配列が直接埋め込まれている。
**REST API も AJAX も不要で、HTML を 1 回取れば全件得られる。LLM も不要。**

2026-08-18 時点の実測:

- 95 件 / 2026-03-01 〜 2026-09-27 (過去約 5.5 か月 + 未来約 1.5 か月のローリングウィンドウ)
- distinct な title は 42 種。**同一日に 2 件以上のエントリは存在しない**
- 形式: `{"start":"2026-04-14","title":"浮き雲\nダルバート（ネパール料理）","allDay":true}`

### 6.1 title の構造

2 通りのレイアウト規約が混在する。

- 改行区切り: `"北京ごはん\n魯肉飯（ﾙｰﾛｰﾊﾝ）\nタピオカ\n他"`
- 全角スペースによる詰め物: `"N.Teatime　　　…　　日替わりランチ　　…　手網焙煎珈琲"`

**分割規則: 改行、または空白 2 個以上。** 95 件全件で検証済み。1 行目が店名、
残りがメニューになる。`"Bouguet　Bagle"` のように店名内の全角スペース 1 個は
保持される (だから「2 個以上」でなければならない)。

### 6.2 表記揺れ

同一店が原文で最大 6 通りに揺れる:

`Ｎ．Ｔｅａｔｉｍｅ` / `Ｎ．Teatime` / `N．Teatime` / `Ｎ.Teatime` / `N.Teatime` / `N.teatime`

**採用する正規化は機械的な文字種変換のみ**とする。

- 全角英数 → 半角
- 半角カナ → 全角 (`ﾍﾞｰｸﾞﾙ` → `ベーグル`)

判断を含まないので golden テストで固定でき、LLM も要らない。上記 6 通りは
`N.Teatime` 5 種 + `N.teatime` 1 種に減る (大小文字の差は残る)。

**店名エイリアス表は作らない。** 残差は 1 件であり、新しい店が出るたび表を保守する
コストに見合わない。また「事実情報を勝手に書き換えない」というこのリポジトリの
方針とも整合する。将来ひどく揺れたら、この正規化の上に足せばよい。

### 6.3 シェフ以外のエントリ

`くるくるマルシェ` / `夏まつり` / `吊るし飾りの会（ＰＭ）` / `毎週火曜日　出店者募集中`
といった、日替わりシェフ以外のエントリが混在する。**除外せず同様に登録する。**
いずれも同じ施設で起きることであり、利用者にとって有用な情報である。

## 7. 設計

### 7.1 `_lib.sync_set()`

集合同期の中核。新規ソースが増えたときは、この関数に「取得した集合」を渡すだけで
済むようにする。

```python
def sync_set(out_dir, uid_prefix, source_type, items, max_delete=10) -> dict:
    """予定表の集合を events/ に同期する。

    items: [{"date": "YYYY-MM-DD", "summary": str, "description": str}, ...]
    返り値: {"added": n, "updated": n, "deleted": n, "unchanged": n}
    """
```

処理:

1. `items` から UID を生成 — `{uid_prefix}-{YYYYMMDD}-{NN:02d}@hanno.city.tecoli.com`
   (`cal-shiminkaikan-fetch` と同じ規約)。連番は同一日内を **summary でソートした
   決定論的な順**で振る。実データに同日重複はないが、将来出ても UID が安定する
2. `out_dir` 配下から `uid` が `{uid_prefix}-` で始まる YAML を集め、現行集合とする
3. **追加**: 取得側のみに存在 → YAML 生成
4. **更新**: 両方に存在し内容が異なる → 上書き。`content_hash` 一致なら書かない
   (mtime も git diff も増やさない。既存クローラと同じ作法)
5. **削除**: 既存側のみに存在し、**かつ**以下を両方満たすもの
   - 取得した集合の日付範囲 `[min(date), max(date)]` に含まれる
   - `dtstart >= 今日`
6. **安全弁**: 削除対象が `max_delete` を超えたら**何も書かずに異常終了**する

#### 削除ガードの根拠

ソースはローリングウィンドウである。商工会議所が古い月を配列から落とせば、素朴な
「配列にないものを消す」では**過去の記録が一斉に消える**。

- **日付範囲での限定**が、ウィンドウ外の過去分を守る
- **今日以降への限定**が、「時間が経って流れていった予定」を記録として残す
- **上限**が、パース失敗時にカレンダーが空になる事故を止める

なお「ページから消えた」という事実からは、中止なのか予定変更なのか入力ミスの訂正
なのかを**我々は知り得ない**。したがって `status: canceled` のような**根拠のない
状態表示は行わない**。単に削除する。

### 7.2 `cal-cci-chef-fetch`

やることは 3 つだけ。

1. `_lib.fetch_with_cache()` で HTML を取得 (ETag / Last-Modified による条件付き GET)
2. `events:` の JSON 配列を抽出し、§6 の規則で `items` に変換
3. `_lib.sync_set()` に渡す

`--out-dir` / `--min-events` (取得件数の下限。既存クローラと同じ健全性チェック) を
受ける。設定値は `sources.yaml` の `cci-chef` から読む。

生成される YAML の形:

```yaml
uid: "chef-20260414-01@hanno.city.tecoli.com"
summary: "浮き雲"
location: "日替わりシェフレストラン"
url: "https://www.hanno-cci.or.jp/manage/founded/#02"
dtstart: "2026-04-14"
dtend: "2026-04-14"
description: |-
  ダルバート（ネパール料理）

  https://www.hanno-cci.or.jp/manage/founded/#02
render:
  gcal:
    mode: single-allday
source:
  type: hanno-cci-chef
  id: "20260414-01"
  url: "https://www.hanno-cci.or.jp/manage/founded/#02"
  fetched_at: "..."
  content_hash: "sha256-..."
```

**summary への絵文字 prefix は付けない。** 専用カレンダーなので全件同じ prefix に
なり、情報量がない (既存クローラの `📢` `🎪` `ℹ️` `📝` は 1 カレンダーに複数
ソースが混ざるための識別子である)。

### 7.3 `cal-myhanno prune`

新設サブコマンド。**YAML に対応が無い Calendar イベントを削除する。**

```
cal-myhanno prune --uid-prefix chef [-d events] [--dry-run] [--max-delete N]
```

- **対象の特定は iCalUID の prefix** (`chef-*@hanno.city.tecoli.com`)。Google 側の
  イベントは `source.type` を持たないため、prefix が唯一の確実な手掛かりである
- `--uid-prefix` は**必須引数**。指定しない限り何も消えない (既存 4 カレンダーへの
  誤爆を構造的に防ぐ)
- JP / EN 両方のカレンダーを対象にする (本件は JP のみだが、汎用性のため)
- 削除上限あり。`--dry-run` あり。実行前に snapshot を取る

**この prefix 限定には第 2 の効用がある。** 同じカレンダーに人間が Google カレンダー
UI から直接足した予定は UID が異なるため、**prune の対象に入らない**。
`calendar/README.md` の「`source:` なし = 手動キュレーション = 不可侵」という原則が
カレンダー内でも保たれる。

既存の `apply-all` は insert/update しか行わず、削除経路は全消しの `wipe` しかない。
`prune` はその間を埋める。

### 7.4 `sources.yaml`

```yaml
cci-chef:
  uid_prefix: chef
  source_type: hanno-cci-chef
  page_url: "https://www.hanno-cci.or.jp/manage/founded/"
  anchor: "02"
  location: "日替わりシェフレストラン"
  url_host_allowlist: www.hanno-cci.or.jp
  max_delete: 10
```

### 7.5 `cal-myhanno` の routing

```python
CALENDARS = {
    ...
    "chef": "ae1577f36d2b51db208baec59cc84e90ceab25d41bad166b42c37fb7063f4a46@group.calendar.google.com",
}
SOURCE_TYPE_TO_CALENDAR = {
    ...
    "hanno-cci-chef": "chef",
}
```

`chef.en` は作らない (§8)。

## 8. 英訳を行わない判断

**EN カレンダーは作らず、`cal-translate-en` から除外する。**

理由は **consumer が存在しない**こと。既存の `default.en` / `gikai.en` が要るのは
`city.tecoli.com/@hanno/` が ical を 2 言語で配信しているためである。一方この
カレンダーは店舗ページに紐付いた shop カレンダーであり、その配信経路に乗らない。
そして **city-tecoli の店舗ページには i18n の仕組みが存在しない** (`src/lib` /
`src/pages` に `i18n` / `translations.en` の参照なし)。

内容面でも価値は薄い。`北京ごはん` `浮き雲` `N.Teatime` `Bouguet Bagle` といった
固有名詞の店名が主体で、訳しても音写にしかならない。

**実装上の注意**: `cal-translate-en` は `events/` を全件処理する設計なので、
**明示的に除外を書かないと `translations.en.*` が勝手に付き、日々 LLM 呼出の
コストがかかる**。`source.type` で skip する分岐を、既存の `translation_hash`
一致 skip の隣に追加する。

## 9. CI (`cal-daily.yml`)

ステップの**順序が設計の一部**である (§4)。

```
… 既存 crawler 群 …
+ Crawl hanno-cci-chef          ./calendar/bin/cal-cci-chef-fetch --out-dir calendar/events --min-events 20
+ Prune removed chef events     ./calendar/bin/cal-myhanno prune --uid-prefix chef -d calendar/events
  Fetch manual Calendar additions + sync manual edits   ← prune より後でなければならない
  Safety check (blast radius cap)
  Commit events changes
  Apply events to Calendar (if drift)
  …
```

既存の `Safety check` (既定 50 ファイル) はそのまま効く。`sync_set` の `max_delete`
とは別の層の防御であり、両方あってよい。

## 10. テスト

### golden (ネットワーク非依存、CI 実行)

`calendar/tests/run-golden` の `CRAWLERS` に追加する。fixture は取得済み HTML 1 枚。

| シナリオ | seed | 見るもの |
|---|---|---|
| `cal-cci-chef-fetch` | なし | 初回取込。95 件が期待どおりの YAML になる |
| `cal-cci-chef-update` | 既存 YAML 一式 | 内容変更が更新として反映され、無変化は書き換わらない |
| `cal-cci-chef-delete` | 取得側に無い未来の YAML を含む | **削除される** (golden にそのファイルが無いことで検出) |
| `cal-cci-chef-keep-past` | 取得側に無い**過去**の YAML を含む | **削除されない** |

`run-golden` は生成ファイルの key set を golden と比較するので、削除シナリオは
「golden にそのファイルが無い」という形で自然に表現できる。

### ユニット (`calendar/tests/test_*.py`)

- `test_chef_title_split.py` — §6.1 の分割規則。全角スペース 1 個は保持、2 個以上は区切り
- `test_chef_normalize.py` — §6.2 の文字種正規化
- `test_sync_set.py` — 削除ガード (範囲外 / 過去 / 上限超過) を純粋関数として検証

`sync_set` の削除判定は**「今日」に依存する**ので、テスト可能にするため
`today` を引数で受け取れるようにする (既定は実日付)。

**実カレンダーに対する破壊的検証は行わない。** 削除挙動は golden とユニットで見る。

## 11. 運用状況 (2026-08-19 時点で完了済み)

- Google カレンダー作成済み
  - ID: `ae1577f36d2b51db208baec59cc84e90ceab25d41bad166b42c37fb7063f4a46@group.calendar.google.com`
  - 名前: `📍 日替わりシェフレストラン` (`📍` はアプリが自動付与)
  - オーナー: `tecolicom@gmail.com`
  - 一般公開済み (ICS が HTTP 200)
- 飯能商工会議所の店舗ページ (`ChIJ_aM0DDcmGWAR3KV7H6eOrIs`) に
  **アプリ専用カレンダー**として登録済み
- Service Account `myhanno-bot@city-tecoli.iam.gserviceaccount.com` に
  「予定の変更権限」で共有済み

### カレンダーを取り巻く 3 者

| 立場 | 誰 | できること |
|---|---|---|
| オーナー | `tecolicom@gmail.com` | 全権。共有・公開設定・削除 |
| 作成したアプリ | city-tecoli の OAuth クライアント | 読み書き。**ACL は触れない** (`calendar.app.created` のみで `calendar.acls` 非取得) |
| 委託された管理者 | SA `myhanno-bot@…` | 予定の追加・変更・削除 |

一般公開は「シェフの店の店舗ページにも公開カレンダーとして登録できる」余地を
残すためのもので、本設計の動作には不要である (SA の書き込みには公開設定は無関係)。

## 12. リスクと残課題

- **ソースの HTML 構造が変わる** — FullCalendar の初期化コードに依存している。
  `--min-events` の下限チェックで検知し、CI を赤にする
- **ローリングウィンドウの挙動が未確認** — 商工会議所が古い月をいつ落とすかは
  観測できていない。削除ガードはこの不確実性を前提に組んである
- **`cal-shiminkaikan-fetch` は追記型のまま** — 中止公演が残る弱点は未解決。
  枠組みが本件で安定してから移行する

### 本設計の作業中に見つかった city-tecoli 側の問題 (別件)

- **カレンダー作成後のフィードバックがない** — OAuth から戻った店舗ページが
  キャッシュから配られ、作成したのに何も増えていないように見える。実際に
  `?cb=` を付けて取り直すまで古い件数が表示された
- **`removeShopGcalToken()` がどこからも呼ばれていない** — カレンダー登録を削除
  しても、リフレッシュトークンが `<place_id>/gcal-tokens` に残り続ける
