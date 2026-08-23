# calendar/

Myはんのう Google カレンダー群 (`tecolicom@gmail.com` 所有、`city.tecoli.com/@hanno/` から ical 配信) を YAML で canonical に管理する仕組み。日本語 + 英語の 4 カレンダー構成。

## 基本方針

- **YAML が canonical**: `events/<year>/<MM-DD>_<uid>.yaml` (1 イベント 1 ファイル) が真の正本
- **Google Calendar は投影先**: 全イベントを終日にし、時刻情報は description 冒頭の `🕒 HH:MM–HH:MM` marker で保持
- **`source:` フィールドの有無で識別**:
  - `source:` あり → クローラ管理 (自動で更新・再生成される)
  - `source:` なし → 手動キュレーション (クローラは絶対に触らない、不可侵)
- **英訳は YAML 内 `translations.en.*` に格納**: 元の summary/description は不変、英訳が追加情報として隣に並ぶ

## クローラの 2 系統

ソースが**どういう単位で配布されるか**で、扱いが根本的に変わる。

| | 追記型 | 集合同期型 |
|---|---|---|
| 配布単位 | 記事 1 本 = イベント 1 個 | 1 エンドポイントに全件 |
| UID の根拠 | 記事 ID | 日付 + 連番 |
| 消えたものの解釈 | **判別不能** (取り下げか、一覧から溢れただけか区別できない) | **不在 = 予定から外れた** |
| 同期 | upsert のみ | **upsert + prune** |
| 該当 | tourism / tourism-news / oshirase / shicho-blog / gikai / shiminkaikan | **cci-chef** |

集合同期型の中核は `_lib` の 2 関数。削除の可否を決める純粋関数
`plan_set_sync()` と、その決定を実行する I/O ラッパ `sync_set()`。
Calendar 側への削除の伝播は `cal-gcal prune` が担う。

### 削除ガード

`plan_set_sync()` が削除するのは、以下を**すべて**満たすものだけ:

1. 既存側にあり取得側に無い
2. `dtstart` が取得集合の日付範囲 `[min, max]` の内側 — ソースはローリング
   ウィンドウなので、範囲外の過去分を守る
3. `dtstart >= today` — 時間が経って流れていった予定は記録として残す

加えて削除数が上限を超えたら `SetSyncTooManyDeletions` を投げ、**1 バイトも
書かずに**中止する。取得が 0 件のときは日付範囲を定義できないので何も削除しない。

「ページから消えた」という事実からは、中止なのか予定変更なのか入力ミスの訂正
なのかを**我々は知り得ない**。したがって `status: canceled` のような**根拠の
ない状態表示は行わない**。単に削除する。

### prune は `fetch --update-manual` より前に置く

CI のステップ順序が設計の一部である。`cal-gcal fetch --update-manual` は
「Calendar にあって YAML に無い event を新規 YAML 化」する経路で、生成される
YAML は `event_to_yaml()` が作るため **`source:` を持たない**。

したがって prune を後ろに置くと:

```
crawler が YAML 削除 → Calendar には残存 → fetch --update-manual が拾う
  → source: なしの YAML として復活 → 以後「手動キュレーション」扱いで不可侵
  → クローラは二度と触れず、Calendar に永久に残る
```

**削除したはずの予定が、不可侵な手動イベントとして蘇生する。**

なお `prune` の対象は `--uid-prefix` で限定される (必須引数)。これは既存
カレンダーへの誤爆を防ぐと同時に、**同じカレンダーに人間が手で足した予定を
守る**役割も持つ (UID が違うので対象に入らない)。

設計の詳細は
[`docs/superpowers/specs/2026-08-19-schedule-set-sync-design.md`](../docs/superpowers/specs/2026-08-19-schedule-set-sync-design.md)。

## カレンダー構成

JP/EN の 2 言語 × 用途別 2 系統 = 4 カレンダー、加えて店舗カレンダー 1 本を
Service Account 1 つで管理:

| logical key | calendar 名 | 内容 | 対応 source.type |
|---|---|---|---|
| `default` | Myはんのう | 観光・市民会館・コミュニティ等 | hanno-tourism-jp / city-hanno-shiminkaikan / (手動) |
| `gikai` | 飯能市役所 | 市政情報・市長ブログ・お知らせ | city-hanno-gikai / city-hanno-shicho-blog / city-hanno-oshirase |
| `default.en` | Myはんのう（EN） | `default` の英訳 (同 source.type) | (同上) |
| `gikai.en` | 飯能市役所（EN） | `gikai` の英訳 (同 source.type) | (同上) |
| `chef` | 日替わりシェフレストラン | 商工会議所の当番表 (**EN なし**) | hanno-cci-chef |
| `cci` | 商工会議所からのお知らせ | 商工会議所の告知 (検定を除く 4 カテゴリ) | hanno-cci-event |
| `cci.en` | 商工会議所からのお知らせ（EN） | `cci` の英訳 | (同上) |

`chef` だけ EN 版が無い。理由は「**店名という固有名詞を訳しても情報が増えない**」
の一点。`cal-translate-en` の `NO_TRANSLATION_SOURCE_TYPES` で明示的に除外している
(除外を書かないと `translations.en.*` が付き、毎日 LLM を無駄に呼ぶ)。

同じ shop カレンダーでも `cci` は英訳する。告知は補助金・相談窓口・セミナーの
説明文で、本文の中央値は 370 字あり、訳す価値がある。

> **shop カレンダーだから英訳しない、ではない。** `publicCalendars()` が除外するのは
> `kind: 'todo'` だけで (city-tecoli の `storage/shops.ts:127-129`)、**言語による
> 絞り込みは存在しない**。登録すれば英語カレンダーもそのまま店舗ページに並ぶ。
> `default.en` / `gikai.en` が店舗ページに出ないのは、それらが街レベルのカレンダーで
> **そもそも店舗に登録されていない**ためであって、英語だからではない。

routing は `source.type` ベース。`source.type` → `default` or `gikai` のマッピングが
`bin/cal-gcal` の `SOURCE_TYPE_TO_CALENDAR` に定義。英語カレンダーは
`<base>.<lang>` 命名で base routing と lang を直交的に組み合わせる。

## ディレクトリ構成

```
calendar/
├── bin/
│   ├── _lib.py                  全 crawler の共通ヘルパ (HTTP fetch / cache / YAML 整形 / config 読込 / etc.)
│   ├── cal-gcal              Google Calendar API ラッパ (Python + gws)
│   ├── cal-tourism-fetch        hanno-tourism.jp の tour 投稿タイプ、決定論パーサ (LLM 不使用)
│   ├── cal-tourism-news-fetch   hanno-tourism.jp の news 投稿タイプ、LLM 抽出 + 機械検算
│   ├── cal-shiminkaikan-fetch   飯能市民会館 公演スケジュール取得
│   ├── cal-gikai-fetch          飯能市議会 議事日程取得
│   ├── cal-shicho-blog-fetch    市長ブログ取得 + 本文掲載 (LLM 不使用)
│   ├── cal-oshirase-fetch       飯能市公式お知らせ取得 + LLM 要約
│   ├── cal-cci-chef-fetch       商工会議所 日替わりシェフ当番表 (集合同期型、LLM 不使用)
│   ├── cal-cci-event-fetch      商工会議所の告知 (xo_event)、長文は LLM 要約
│   └── cal-translate-en         events/ 全 YAML を英訳して translations.en.* に格納
├── city.yaml                    都市 (data repo) 固有設定 (uid_namespace / カレンダー ID / routing)
├── sources.yaml                 クローラの source 別 city 固有設定 (URL / prefix 等、多都市化用)
├── events/                      canonical YAML (1 イベント 1 ファイル)
│   └── <year>/<MM-DD>_<uid>.yaml
├── snapshots/                   Calendar 状態のミラー (バックアップ + 監査台帳)
│   └── <calendar-key>/events/<uid>.json
├── sources/                     クローラ用の入力データ (設定とは別物)
│   └── hanno-tourism/urls.txt
├── tests/                       golden 回帰テスト (出力 YAML をバイト一致でロック)
│   ├── run-golden               比較 runner (hermetic、CI 実行)
│   ├── capture-fixtures         fixtures を実サイトから取得する dev tool
│   ├── capture-news-fixtures    news の fixtures + LLM 応答を採取する dev tool (要 API キー)
│   ├── eval-news-prompt         news の抽出プロンプト評価 (LLM 実呼出、CI 非実行)
│   ├── fixtures/<crawler>/      入力 HTML/RSS + manifest.json
│   ├── seed/<scenario>/         out-dir に事前展開する既存 YAML (更新検知シナリオ用)
│   ├── corpus/                  プロンプト評価用の生 API レスポンス (seed とは別物)
│   └── golden/<scenario>/       期待出力 YAML (日付正規化済み)
└── .http-cache.json             HTTP Conditional GET 用 ETag / Last-Modified 永続化
```

> 注: `sources.yaml` (クローラの設定ファイル) と `sources/` (tourism の URL リスト等の入力データ) は
> 別物。`sources.yaml` は city 固有値を外出ししたもので、多都市展開時は各 data repo がこれを持つ。

### bin/_lib.py

各 crawler が共通利用するヘルパモジュール。引数命名規約は `s` (テキスト) / `path` (単一ファイル) / `out_dir` / `url` で統一。

| カテゴリ | 提供 |
|---|---|
| 定数 | `USER_AGENT`, `UID_NAMESPACE`, `AI_DISCLAIMER_JP`, `STATUS_MARKERS` |
| HTTP fetch | `fetch(url)`, `fetch_binary(url, dest)`, `fetch_with_cache(url, etag, last_modified)` |
| HTTP cache | `load_http_cache()`, `save_http_cache(cache)`, `HTTP_CACHE_PATH` |
| HTML/text | `strip_html`, `collapse_space`, `normalize_fullwidth_digits`, `normalize_tilde`, `normalize_body`, `strip_markdown(s, bullet)` |
| HTML メタ | `infer_year_from_og(html)` |
| 暦変換 | `reiwa_to_gregorian(N)`, `gregorian_to_reiwa(year)`, `last_modified_to_jst_date`, `dtstart_from_last_modified` |
| YAML 整形 | `yaml_escape_str`, `yaml_block_scalar` |
| event YAML 操作 | `read_yaml_scalar`, `read_yaml_block(path, key)`, `existing_content_hash_matches`, `output_path_for`, `find_existing_by_uid` |
| description 分解 | `strip_status_header(text)` — 冒頭の 🆕/🔄/📝 ブロックを除去 / `split_description(text)` — AI disclaimer 行と末尾 URL 行を剥がし `(本文, source_url)` を返す (status 行は残す。EN 側で訳すため) / `split_photo_lines(text)` — 末尾の `写真: <url>` 行群を剥がし `(本文, [url,…])` を返す / `format_photo_lines(urls, label, number_sep)` — その逆 (1 枚なら `写真:`、複数なら `写真1:` …) |
| クローラ設定 | `load_source_config(source_key)` — `../sources.yaml` から source 別の city 固有設定 dict を読む (不在 key は KeyError) |
| 文字種正規化 | `normalize_char_width(s)` — 全角 ASCII → 半角、半角カナ → 全角。**寄せないもの**: 大小文字の差、全角スペース U+3000、全角括弧、全角ティルダ (`normalize_tilde` の担当) |
| 集合同期 | `plan_set_sync(existing, incoming, dates, today, max_delete)` — 削除可否の判定 (純粋関数、上記「削除ガード」) / `sync_set(out_dir, uid_prefix, items, render_doc, today, max_delete, dry_run)` — その実行 / `set_sync_uid` / `set_sync_hash` (**イベント単位**の content_hash) / `SetSyncTooManyDeletions` |
| LLM 呼出 | `call_llm(system, user, *, model, max_tokens, temperature, timeout, output_schema)` — Messages API を 1 回叩く。**JSON を受け取るなら `output_schema` を必ず渡す** (下記) |
| LLM 出力の検算 | `drop_unchanged_claims(text)` — 「A から A に変更」を含む文を落とす。**差分行を作る全クローラが共有する** (`cal-oshirase-fetch` / `cal-cci-event-fetch`)。片方にだけ置くと後日片方だけ直る事故が起きるので `_lib` に置いている |

**LLM に JSON を書かせる箇所は `output_schema` を渡すこと。** プロンプトに
「JSON で返せ」と書くだけでは形式は保証されない。原文の `「」` を英語の `"` に
訳す・写すと、エスケープされない `"` が JSON 文字列に混ざって `json.loads` が
落ちる。渡すと API 側が形式を保証する。詳細と実測値は
「bin/cal-translate-en → 応答形式はサーバ側で強制する + 引き直す」。

## 認証

Google Cloud プロジェクト `city-tecoli` の Service Account
`myhanno-bot@city-tecoli.iam.gserviceaccount.com`。各カレンダーに対し
SA メアドを「予定の変更権限」(writer) で共有済み。

```
# ローカル
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/city-tecoli/calendar-sa.json

# CI (GitHub Actions secret に SA JSON 全文を入れる)
secrets.GWS_SA_JSON
```

`cal-gcal` は env 未設定時に `~/.config/city-tecoli/calendar-sa.json` を自動 fallback
する (旧 `~/.config/myhanno/sa.json` も候補に残してあるが、2026-08-21 に移動済み)。

鍵の持ち主は **city-tecoli プロジェクトの service account** で、街にもツールにも
属さない。1 本の SA に各カレンダーの writer を委託していく形なので、街が増えても
鍵は 1 本のまま。街ごとに主体を変えたいときは `GOOGLE_APPLICATION_CREDENTIALS` で
上書きする (CI がそうしている)。

### カレンダーを新規に作る

新しい配信元を足すとき、既存カレンダーに相乗りしないなら 3 手順で作る。すべて
`gws` で完結する (UI は不要)。**カレンダーはそのデータを管理している主体の
アカウントに作る** — 名前と実態の不整合を防ぐため (商工会議所の当番表を
tecolicom 側に作って作り直した前例がある)。

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/city-tecoli/calendar-sa.json

# 1. 作成 (owner = 実行した主体)
gws calendar calendars insert --format json \
  --json '{"summary":"<表示名>","timeZone":"Asia/Tokyo"}'
# → 返る "id" が Calendar ID

# 2. 一般公開 (アプリの ICS / 埋め込みで読ませるなら必須)
gws calendar acl insert --format json --params '{"calendarId":"<ID>"}' \
  --json '{"role":"reader","scope":{"type":"default"}}'

# 3. SA に書き込みを委託 (これが無いとクローラが apply できない)
gws calendar acl insert --format json --params '{"calendarId":"<ID>"}' \
  --json '{"role":"writer","scope":{"type":"user","value":"myhanno-bot@city-tecoli.iam.gserviceaccount.com"}}'
```

出来上がりの ACL はこの形になる (`gws calendar acl list` で確認できる):

| role | scope |
|---|---|
| owner | カレンダー自身 / 作成したアカウント |
| reader | `default` (= 一般公開) |
| writer | `myhanno-bot@city-tecoli.iam.gserviceaccount.com` |

作ったら `city.yaml` の `calendars` に logical name で登録し、`source_type_to_calendar`
にルーティングを足す。両方やらないと **YAML は増えるがカレンダーに出ない**。

### 商工会議所の REST API は使えない → RSS に切替済み

`cal-cci-event-fetch` は **RSS (カテゴリ別フィード) から取得する**。REST API
(`/wp-json/`) は GitHub Actions の IP から遮断されるため使わない。

```
https://www.hanno-cci.or.jp/xo_event_cat/<slug>/feed/[?paged=N]
```

slug は `promotion` (地域振興) / `seminar` (セミナー) / `manage` (経営支援) /
`news` (お知らせ)。`exam` (検定) は取り込まない。`content:encoded` に本文全文が
入るので REST の利点 (1 リクエストで本文まで) はほぼ保たれる。実測 9 リクエストで
49 件、**REST と完全一致** (記事 ID で名寄せして差分ゼロ)。

**記事 ID で重複排除が要る。** 複数カテゴリを持つ記事があり、名寄せ前は 60 件に
見える (`merge_posts` が担当)。

**REST と RSS で本文が微妙に違う。** REST の `content.rendered` はリンク行の先頭に
`◾️` が入るが、RSS の `content:encoded` には入らない (WordPress のフィルタ適用範囲の
差)。2026-08 の切替時、49 件中 6 件の `content_hash` が変わった。**取得経路を
変えると本文も変わりうる。**

`cal-daily.yml` での自動実行は**まだ有効化していない**。RSS が CI から通るかを
確認できていないため (下記)。手元 (日本の回線) からは動く。

#### CI から遮断された経緯

観測 (2026-08-20、ランナーは Azure eastus2 / 米国バージニア、IP 135.119.132.147):

| 時刻 | HTML (`/manage/founded/`) | REST (`/wp-json/`) |
|---|---|---|
| 15:56 | timeout | timeout |
| 16:43 | **200** | **403** |
| 16:52 | **200** | **403** |
| 17:01 | **000 (到達不能)** | **000 (到達不能)** |

同時刻に日本国内のローカル回線からは REST も HTML も 200。CDN / WAF の
ヘッダは無く `server: nginx` のみ。UA は両クローラで同一なので UA 起因ではない。

**403 の原因は確定している。** エックスサーバーの WordPress セキュリティ設定に
ある「国外アクセス制限設定 → REST API アクセス制限」で、**デフォルトで ON**
([事例](https://qiita.com/benjuwan/items/fc7a1e3d7357ea42c95f))。公開 HTML は通し
`/wp-json/` だけ海外 IP から弾く。同じ症状を han-note.com で先に踏んでおり
`WatchCrow/README.md` に記録がある。

**商工会議所が意図的に閉じたとは限らない。** 既定値なので、依頼すれば管理画面の
トグル 1 つで解除できる可能性がある (交渉というより情報提供)。ただし RSS で
足りているので急がない。

**timeout は別の現象で、原因未特定。** 403 は即座に返るが、こちらは応答が無く
HTML も巻き込む。403 とは切り離して考える必要がある。「403 を繰り返した結果 IP
全体が締め出された」という説明を一度立てたが、REST を叩く前の最初の実行
(15:52) で既に timeout しており、それだけでは説明できない。

**止めた理由は 2 つ。**

1. **相手のサイトに迷惑** — 遮断されると分かっている先を毎日叩かない
2. **timeout との切り分け** — chef (HTML) も timeout する日があり、原因が
   未特定。REST を叩き続けると、それが原因かどうかを判定できなくなる

> 当初は「REST の 403 を繰り返した結果 IP 全体が締め出され、chef まで巻き添えに
> なった」と書いていたが、**因果は確認できていない**。chef の timeout は REST を
> 叩く前の最初の実行から起きている。

取り込み済みの 49 件は `events/` とカレンダーに残る。手元 (日本の回線) からは
問題なく動くので、更新が必要なら手動で流す:

```
./calendar/bin/cal-cci-event-fetch --out-dir calendar/events --min-items 1
```

#### sitemap は使えなかった

はんのーとの解決策 (`post-sitemap.xml`、`WatchCrow/README.md` 参照) はそのまま
使えない。商工会議所の sitemap は Google Sitemap Generator 製で
`sitemap-pt-page-*` (固定ページ) しか含まず、**カスタム投稿タイプ `xo_event` が
載っていない**。

#### RSS は CI から通る (2026-08-22 実測)

**確認済み。** 2 日空けて CI から実行し、`Fetched 49 posts` で成功した
(run 32496084844)。遮断されているのは `/wp-json/` だけで、RSS は通常の
WordPress URL なので同じ制限に当たらない。

判定に先立ち、同じホストの **HTML** が CI から取れることを `cal-cci-chef-fetch`
の成功で確認した (2026-08-21)。2026-08-20 に HTML まで到達不能だったのは
403 の連発による一時的な IP 締め出しで、時間を置いて解けたことになる。

`WatchCrow/README.md` の `sitemap` 型は「REST API や **RSS** が使えないサイト
向け」とあり RSS も遮断されうると示していたが、少なくとも hanno-cci.or.jp では
該当しなかった。他サイトでは改めて確認すること。

`--min-items` は **1 以上**にすること。0 は「1 件も取れない異常を CI が緑のまま
通す」設定で、実際 2026-08-20 の REST 遮断はこれで見逃された。

CI では **chef の後ろ**に置いている。遮断されると同一 IP の chef まで巻き添えで
落ちるため (2026-08-20 実測)、先に安定しているものを通す。

### 落とし穴: ユーザー OAuth が SA 認証を上書きする (対処済み)

`gws` は保存済みのユーザー認証 (`~/.config/gws/credentials.enc`) を
`GOOGLE_APPLICATION_CREDENTIALS` より**優先する**。`cal-gcal` は Service
Account 専用のツールなので、これを拾うと 2 つの問題が起きる。

- スコープが足りなければ全操作が `Request had insufficient authentication
  scopes` で止まる
- スコープが足りてしまうと、**意図しない主体で本番カレンダーを書き換える**

2026-08-21 に実際に踏んだ。カレンダーを CLI で作るため `gws auth login` を
`tecolicom@gmail.com` で通したところ、そのトークンが `calendar.events` を
持たず (作成用に `calendar.calendars` + `calendar.acls` へ絞っていた)、
`cal-gcal` の全操作が失敗した。**CI は毎回まっさらなランナーなので影響を
受けず、ローカルでだけ壊れる**形だった。

対処済み: `cal-gcal` が `gws` を呼ぶとき
`GOOGLE_WORKSPACE_CLI_CONFIG_DIR` を専用ディレクトリに固定し、ユーザー認証を
見せないようにしてある (`GWS_CONFIG_DIR`)。`gws` を直接叩く削除処理 2 箇所も
同じ環境を渡す。**どう呼んでも常に SA** になる。

なお `gws` をカレンダー作成等でユーザーとして使うこと自体は問題ない。
`cal-gcal` から隔離されているだけで、共存できる。

### 落とし穴: 古いトークンキャッシュで `source` が欠ける

`gws` は取得済みトークンを `~/.config/gws/sa_token_cache.json` にキャッシュする。
このキャッシュが古いと、**イベントの `source` フィールドが API から返ってこなくなる**
(2026-08-08 に遭遇。同じ SA・同じ `gws` バージョンでも、キャッシュを消して
トークンを再発行させると `source` が返るようになった)。

`source` は `COMPARE_FIELDS` に含まれるため、この状態でローカル実行すると:

- `snapshot` が 785 ファイルから `source` を落とした差分を作る (コミットするとデータ後退)
- `apply-all` / `diff` が CI と食い違う判定を出す

CI は毎回トークンを新規発行するので影響しない。ローカルで snapshot / apply / diff の
結果が CI とずれたら、まずキャッシュを消して再実行する:

```
rm ~/.config/gws/sa_token_cache.json
```

LLM 利用スクリプト (`cal-oshirase-fetch`, `cal-tourism-news-fetch`,
`cal-translate-en`) は `ANTHROPIC_API_KEY` 環境変数が必要。呼び出し自体は
`_lib.call_llm()` に集約してある。

**鍵が無いと description の組み立て方が変わり `content_hash` が動くので、CI では
必ず渡すこと** (2026-05-26 に oshirase で重複イベントが大量発生した原因)。

## 依存

- [googleworkspace/cli](https://github.com/googleworkspace/cli) (`gws`) — `brew install googleworkspace-cli`
- Python 3.10+
- `pyyaml`, `httpx`

## bin/cal-gcal

> **2026-08-21 に `cal-myhanno` から改名。** 機能が都市非依存になった (都市固有の値は
> `city.yaml` へ移した) のに名前だけ飯能に紐付いていたため。SA 鍵の既定パスも
> `~/.config/city-tecoli/calendar-sa.json` に移し、旧 `~/.config/myhanno/sa.json` は fallback として
> 残している。`docs/superpowers/` の spec / plan は当時の記録なので旧名のまま。

Google Calendar 側を操作するためのコマンド群。内部で `gws` を呼ぶ。

```
cal-gcal find [-q QUERY] [--time-min ISO] [--time-max ISO] [--json]
cal-gcal show <event-id>
cal-gcal set-allday <event-id> [--dry-run]                       # 時刻指定 → 終日 (marker 付き)
cal-gcal set-timed  <event-id> [--dry-run]                       # 終日 (marker 付き) → 時刻指定
cal-gcal fetch       [-o events] [--force] [--update-manual]     # Calendar → YAML 一括吸い上げ
cal-gcal apply      <yaml-file> [--dry-run] [--lang LANG]        # YAML 1 件 → Calendar
cal-gcal apply-all  [-d events] [--dry-run] [--lang LANG] [--only-managed]
                                                                    # events/ 全件 → Calendar
cal-gcal diff       [-d events] [--lang LANG]                    # YAML と Calendar の整合チェック
cal-gcal snapshot   [-o snapshots]                               # Calendar → JSON でバックアップ
cal-gcal wipe       --confirm [--dry-run]                        # Calendar 全削除 (内部で先に snapshot)
```

内部の主なヘルパ:

| 名前 | 役割 |
|---|---|
| `list_all_events(calendar_id)` | `nextPageToken` を辿って全イベント取得。`events.list` はすべてこれ経由 |
| `EventIndex` | calendar_id ごとに 1 回だけ取得する `iCalUID → event` の索引 (`apply-all` の読み取り用) |
| `events_in_sync(existing, new_body)` | `COMPARE_FIELDS` + `normalize_for_diff` で実質同一か判定。`diff` が exit 0 を返す状態と一致 |
| `merge_for_update(existing, new_body)` | `events.update` 用 body。`READ_ONLY_FIELDS` を落とし、YAML に無いフィールドは明示的に消す |

### `--lang` (apply / apply-all / diff)

- `default` (default): YAML 直の `summary`/`description` を JP カレンダー群 (`default`/`gikai`) に反映
- `en`: YAML の `translations.en.{summary,description}` を EN カレンダー群 (`default.en`/`gikai.en`) に反映
- 翻訳未整備の YAML は skip される (apply 時は SKIPPED ログ、diff 時は対象外)

### 終日 ↔ 時刻指定の往復

`set-allday` は時刻情報を description 先頭に保存:

```
🕒 10:00–15:30

<元の description>
```

- 区切り: en dash (U+2013) を出力。パース時はハイフン/em dash/en dash いずれも受理
- TZ: カレンダー既定 (`Asia/Tokyo`) 前提
- 複数日跨ぎの時刻指定イベントは未対応

`set-timed` は marker をパースして時刻指定に戻す。

### apply / apply-all の動作

YAML を読んで `render.gcal.mode` (`single-allday` / `span-allday` / `timed`) に応じて Calendar event body を生成し、`iCalUID` で既存を検索:
- 存在しなければ `events.import` で iCalUID 付きで新規挿入
- 存在すれば `events.update` で上書き

**削除は行わない** (YAML 側で削除しても Calendar event は残る、安全策)。

### apply-all の読み取り (EventIndex)

`apply-all` は起動時に**カレンダー単位で全イベントを一括取得**し、
`iCalUID → event` の索引 (`EventIndex`) を作って反映要否を判定する。
以前は YAML 1 件ごとに `events.list` を呼んでいたため、438 件 × JP/EN で
約 876 回の API 往復が発生し、日次 CI の所要時間の約半分 (135 秒) を占めていた。
現在は同じ `apply-all --only-managed --dry-run` が **3 分 11.7 秒 → 2.8 秒**で完了する
(件数の内訳は前後で完全一致)。

索引は実行開始時のスナップショットなので、apply 中 (数秒) に人が Calendar を
手編集すると見落としうる。そのため**実際に書き込むイベントだけ、`events.update` /
`events.import` の直前に 1 件取り直して**判定し直す:

- 取り直した結果が in-sync なら書かない
- 差分が残るなら**取り直した方**をマージ元にする (古い索引の値で手編集を潰さない)
- 索引にあったが消えていれば import、索引に無いが存在すれば update に回す

書き込みは通常 1 日 0〜数件なので追加コストはほぼゼロ。`--dry-run` では再確認しない。
単体の `apply <file>` は索引を使わず、従来どおり `find_event_by_uid()` で 1 件引く。

`events.list` は `list_all_events()` に集約され、`nextPageToken` を辿って全件取得する
(`maxResults` は API 上限の 2500)。`gws --page-all` は使わない — 出力が NDJSON になり
`gws()` で扱えず、`--page-limit` 既定 10 で静かに切り捨てるため。

### snapshot

Calendar 全イベントを JSON で `snapshots/<calendar-key>/events/<safe-iCalUID>.json` に
書き出す。stable filename なので git diff で「いつ何が変わったか」が読める。
Google が頻繁に変動させる `etag` は除外、`updated` は残す。

**真の mirror セマンティクス**: Calendar から削除されたイベントの snapshot ファイルも自動で削除 (削除自体は git history が保持)。これにより各 calendar-key 配下のファイル数は常に現在 Calendar 件数と一致する。

### wipe + apply-all による完全再構築

事故時の復旧手順:
```bash
cal-gcal snapshot          # (念のため) 最新 snapshot
cal-gcal wipe --confirm    # Calendar 全削除 (内部で自動 snapshot 取得)
cal-gcal apply-all         # YAML から完全再投入 (iCalUID も復元)
cal-gcal diff              # 整合確認 (0 件差分)
```

## bin/cal-tourism-fetch

`hanno-tourism.jp/hanno-eco/tour/<slug>/` の決定論的パーサ。LLM 不使用。

```
cal-tourism-fetch [--url URL | --urls-file PATH] [--no-discover]
                  [--out-dir events] [--uid-prefix tourism] [--dry-run]
                  [--min-tours 20]
```

- ページの `<dl><dt>開催日・時間</dt><dd>…</dd></dl>` を正規表現で解析
- 1 ツアー = 複数開催日のケース (`①5/9 ②5/17 ③5/25`) は **1 セッション 1 YAML** に展開
- UID: `tourism-<slug>-<YYYYMMDD>@hanno.city.tecoli.com`
- `source:` ブロックに provenance を記録 (type / id / url / fetched_at / content_hash)
- 内容に本質的変化がない場合は write 自体を skip (`existing_content_hash_matches` で `translations:` 等を温存)
- ツアー全体中止 (本文に「中止しました」等) は WARN ログを出すが Calendar には載せる (= 本文に中止表示が含まれる)

### ツアー一覧の取得 (REST API)

hanno-tourism.jp は WordPress で、REST API が公開されている (ページの `link:` ヘッダが
`/wp-json/` を自己申告している)。ツアーはカスタム投稿タイプ `tour`。

```
GET /wp-json/wp/v2/tour?_fields=id,link,slug,modified_gmt,tour-month&per_page=100&page=N
```

**掲載制御は `tour-month` タクソノミー。** 開催月が 1 つ以上割り当てられているものだけが
一覧ページに載る = 現在提供中。空のものは「提供していない」という編集意図なので除外する。
実測 (2026-08-08) で、`tour-month` あり 39 件が一覧ページのスクレイピング結果と
**差分ゼロで一致**した。

ページングは `page=1` から辿り、取得件数が `per_page` 未満なら終了。加えて範囲外ページが
返す HTTP 400 (`rest_post_invalid_page_number`) を終端として許容する (総件数が `per_page` の
倍数のとき 1 ページ余分に要求するため)。`x-wp-totalpages` はヘッダなので `_lib.fetch()`
では読めない。

### 更新検知 (modified_gmt)

hanno-tourism.jp は `ETag` / `Last-Modified` を返さないので条件付き GET が使えない。
代わりに API の `modified_gmt` を `calendar/.http-cache.json` に相乗りさせ、一致すれば
HTML を取得しない。

```json
"https://hanno-tourism.jp/hanno-eco/tour/ec-tenta-kaibori/": {
  "modified_gmt": "2026-08-07T01:00:51"
}
```

**処理が成功したツアーだけ記録する**ので、失敗したものは次回リトライされる。
日程は ACF 由来で API に露出していないため (`content.rendered` は紹介文のみ)、
変更分の HTML 取得は避けられない二段構えになる。

実測した日次の変更件数は 40 件中 0〜6 件。ローカル実測で全件取得 15.3 秒に対し、
変更 0 件なら 0.5 秒 (`fetched=0 unchanged=39`)。CI では 55 秒かかっていたステップ。

### サニティチェック

| フラグ / 判定 | 内容 |
|---|---|
| `--min-tours` (既定 20) | API が返すツアー件数がこれ未満なら exit 2。API 崩壊・大量非公開・仕様変更を検知 |
| パース失敗検知 | 取得したページが 1 件以上あり、その全件で 0 セッションなら exit 2 |

`--min-sessions` (抽出セッション総数) は廃止した。取得を skip するようになると、変更 0 件の
日に必ず誤発火するため。API 失敗・JSON パース失敗も exit 2 で止め、スクレイピングへの
フォールバックは持たない。`--no-discover` は「REST API を引かず `urls.txt` のみ使う」
(API 障害時の手動退避用) で、この場合は件数の根拠が無いので `--min-tours` を判定しない。

URL リスト: [`sources/hanno-tourism/urls.txt`](./sources/hanno-tourism/urls.txt) は
**シード (手動ピン留め)**。通常は REST API の結果だけで足りる。

LLM 版 (ad-hoc 用、ページ構造変化時の代替) は別リポにある: `city-tecoli/tools/hanno-tourism-extractor/`。

## bin/cal-tourism-news-fetch (news 投稿タイプ)

`cal-tourism-fetch` が見るのは投稿タイプ `tour` だけ。祭り・花火・盆踊りなどの
単発イベント告知は **`news`** (`/news/<slug>/`) に載るので、こちらは別クローラが扱う。
2026-08-08 の「はんのう昭和盆踊り」を取りこぼしたのがきっかけ。

REST API (`/wp-json/wp/v2/news`) の `content.rendered` に本文が露出しているので
**HTML の追加取得が要らない**。全件が per_page=100 の 2 リクエストで完結する
(実測 137 件)。更新検知は `tour` と同じ `modified_gmt` 方式。

### 告知と本番の 2 系統

1 記事から最大 2 つのイベントを作る。

| | dtstart | UID | 対象 |
|---|---|---|---|
| 告知 | 記事の公開日 | `tourism-news-<id>-<hash6>` | news 全件 |
| 本番 | 抽出した開催日 | `tourism-news-<id>-event` | 開催日が取れたものだけ |

掲載日は事実そのものなので嘘をつきようがない。抽出の当たり外れは本番側だけが
引き受ける。開催日が取れなければ告知だけが残る。

**本番はタイトル先頭の日付を落とす** (`strip_leading_date`)。本番は dtstart
そのものが日付を表すので「8月8日(土) はんのう昭和盆踊りへ♪」が 8/8 に出ると
二重になる。告知は掲載日に置くため、タイトル内の日付は「いつの予定の話か」を
示す情報として残す。先頭以外の日付には触らない (文の一部なので)。

告知は `cal-oshirase-fetch` と同じく**世代を作る** (内容が変われば新 UID、
前世代は残り `source.supersedes` で繋がる)。本番は世代を作らず、中止・延期が
追記されたら同じ UID のまま `summary` を `【中止】…` に書き換える。

### 開催日は二重チェックしたものだけ採る

`news` には `tour` の `<dl><dt>開催日・時間</dt>` に相当する定型フィールドが無い
(実測: 日時ラベルを持つのはイベント系 69 件中 13 件)。正規表現だけでは再現率 65%
に対し適合率が約 1/3 まで落ちる。更新スタンプ・終了日・副イベント・中止追記を
拾ってしまうため。

そこで Haiku 4.5 に「どの日付が開催日か」の**意味判断**をさせ、返ってきた日付を
コード側で**機械検算**する。役割を分けるのがこの設計の要。検算は 6 項目で、
全部通過して初めて本番を作る。

1. LLM が返した根拠文字列が入力に実在するか (幻覚検出)
2. 根拠と結論の月日が一致するか
3. 根拠に曜日表記があれば実際の曜日と一致するか
4. 記事公開日の −31 〜 +400 日の範囲か
5. 根拠が更新スタンプ (`6/16更新` 等) でないか
6. 根拠が和暦なら西暦への換算が合っているか (`令和8年` = 2026)

失格したらログに理由を出して本番を作らない。告知は作る。

### 記事の主題が別にあるときは本番を作らない

日付が正しく取れても、それが「その日に起きること」の案内とは限らない。LLM に
`announces_event_itself` を返させ、false なら本番を作らない (`not-announcement`)。

判断基準は「カレンダーの当日欄にこの記事のタイトルが出て意味が通るか」。

| | 記事 | 判定 |
|---|---|---|
| true | 「8月8日 盆踊りへ」 | その日に起きることの案内 |
| true | 「7月18日・19日 休業のお知らせ」 | その日休むことの案内 |
| false | 「飯能まつり 協賛のお願い」 | 主題は協賛金の募集。11/7 は背景説明 |

迷ったら false に倒す。実データ 40 件で測ったところ、判定が変わるのは
「協賛のお願い」1 件だけで、休業・営業案内 12 件と祭り 8 件は影響を受けない。
タイブレークは一度も発火しなかった (= 迷う事例が無い)。

**これは機械検算できない唯一の判定。** 日付と違ってコード側で裏取りする手段が
無く、LLM を信じる箇所が 1 つ増えている。誤って false を返せば本来載るべき
イベントが落ちるので、理由は必ずログに出す。

判定が false に変わったら、既に作ってある本番は取り下げる。ただし取り下げる
のは `not-announcement` と `manual-conflict` の 2 つだけ (`RETRACT_REASONS`)。
`no-date` や検算失敗は LLM の揺れで一時的に起きうるので、それで消すと正しい
イベントが消えたり復活したりを繰り返す。

検算 6 は実際に誤りを止めている。「令和8年4月1日より休館」に対し LLM が
2027-04-01 を返し、曜日表記が無いため検算 3 では拾えず範囲チェックもすり抜けた。
プロンプトに換算規則を書いた上で、機械換算でも押さえている。

照合は LLM に見せたのと同じ文字列 (公開日 + タイトル + 本文) を対象にする。
日付がタイトルにしか無い記事があるため。引用符は照合時だけ ASCII に畳む
(LLM が `“宵宮”` を `"宵宮"` と打ち直して空振りした実例がある)。

### そのほかの決めごと

- `tag-news` タクソノミー (`イベント`/`飯能まつり`/`エコツアー`) は**掲載可否には
  使わない**。表示用の絵文字を決めるだけ (イベント系 🎪 / それ以外 ℹ️ / 告知 📢)。
  掲載可否は `announces_event_itself` が担う。

  タグで絞る案は一度検討して却下した。**タグ無しの記事 2 件が「第32回 吾野宿まつり」
  と「はんのう昭和盆踊り」**で、どちらも拾いたい祭りだった (盆踊りはこのクローラを
  作る発端になった記事そのもの)。観光協会のタグ付けは祭りで漏れる
- 同じ記事を指す**手動 YAML があれば本番を作らない**。URL はパーセントデコードして
  比較する (手動 YAML と API の `link` でエンコード表記が揺れる)。現に
  `events/2026/07-18_natsumatsuri-20260718.yaml` が該当する
- `--backfill-months` (既定 6) は初回だけでなく**毎回適用するフィルタ**。
  これより古い記事は更新されても処理しない
- 記事が API から消えても**既存 YAML は残す** (追随はスコープ外)
- `--min-news` (既定 100) 未満なら exit 2。`news` は蓄積型で 2017 年の記事も
  残っているため下限を高く置ける
- 抽出失敗率は**判定に使わない**。日付が無いのが正常な記事 (休業案内・会報誌発行)
  を含むので、`tour` の「全件 0 セッションなら異常」は移植できない
- **`short_body` と `llm_fail` は別物**。本文が `MIN_BODY_CHARS` 未満の記事
  (エコツアーチラシのように本文が PDF リンクだけ) は安全装置で LLM を呼ばない。
  これは正常動作なので `llm_fail` に数えず、キャッシュにも記録する。
  「LLM を実際に呼んだ記事が全部失敗」したときだけ exit 2 する。
  混ぜると、変更分がたまたま全部チラシだった日に CI が誤って赤くなる
  (2026-08-10 に実際に発生)

### プロンプトを変えたとき

golden テストが見ているのは「記録済み LLM 応答に対してコード側が正しく振る舞うか」
であって、プロンプト改訂の効果は検証していない。改訂したら
`calendar/tests/eval-news-prompt` を手で回すこと (LLM を実呼び出しするので CI には
載せていない)。入力は `calendar/tests/corpus/news-all.json`。

```
ANTHROPIC_API_KEY=... python3 calendar/tests/eval-news-prompt --limit 40
```

直近の実測は 40 件中 23 件通過 (58%)。残りは日付が無い記事・本文が薄い記事・
「4月から6月まで」のような具体日の無い記述で、いずれも意図した不採用。
**通過率は適合率ではない**ので、通過した日付が本当に開催日かは目視で確認すること。

fixtures を採り直すときは `calendar/tests/capture-news-fixtures` (要 API キー)。

設計の経緯と実データの調査結果:
[`docs/superpowers/specs/2026-08-10-tourism-news-design.md`](../docs/superpowers/specs/2026-08-10-tourism-news-design.md)

## bin/cal-shicho-blog-fetch

飯能市長ブログ「市政一直線」(`www.city.hanno.lg.jp/.../shichoblog/`) の決定論的パーサ + 本文取り込み。LLM 不使用。

```
cal-shicho-blog-fetch [--out-dir events] [--year YYYY]
                      [--once-per-page] [--refetch-existing] [--dry-run] [--min-articles 0]
```

- 年/月 index を巡回し、各記事の本文を取得
- description に本文を取り込む:
  - 800 字以下: 全文掲載
  - 800 字超: 冒頭 ~600 字を段落境界優先で抜粋 + 「（続きはリンク先で）」
- 本文中の写真 (`<figure>` 内の `<img>`) は URL を `写真: <url>` 行として description に置く (最大 5 枚、実際はほぼ 1 枚)。app の event-modal と Google Calendar が平文 URL を自動で anchor 化するので、そのままクリックで開ける
- content_hash は (title, date, body, body_truncated) ベース → 本文変化を検知 (dtstart は含めない = 日付非依存)。**写真 URL は含めない**: 含めると既存記事に写真行を足した時点で hash が変わり別 uid の重複エントリが湧く。写真差し替えは URL 据え置きでファイル実体を置換する運用が普通なので、含めても検知はできない
- **HTTP Conditional GET 対応**: 各 month index の ETag を `.http-cache.json` に保存、304 受けたら article 巡回を skip (= 月途中の記事追加が無ければ article fetch 0 件)

### 2 つの動作モード (oshirase と対称)

| | incremental (デフォルト) | once-per-page (`--once-per-page`、legacy) |
|---|---|---|
| UID | `shicho-blog-<page-id>-<hash6>@…` | `shicho-blog-<page-id>@…` |
| dtstart | **取得日 (today, JST)** | 記事の更新日 |
| publish_date | 記事の更新日を `source.publish_date` に保持 | (dtstart と同じなので無し) |
| 生成単位 | 新規・本文変化ごとに別 YAML | 1 page = 1 YAML |
| description 冒頭 | `📝 市長ブログ更新 (公開日: …)` / 既存 page_id なら `🔄 内容更新 (公開日: …)` | (status 行なし) |
| 用途 | cron (新着検知) | 新規街 onboarding / 過去分 backfill |

incremental が既定。**記事の更新日に依存せず「site に出た / 内容が変わった日 (= 取得日)」を
dtstart にする**ので、市長がバックデート公開 (古い更新日で掲載) しても app トップの「今日以降」
ウィンドウに新着として現れる。status 行 (`📝`/`🔄`) は content_hash に含めない (fetch 時点の状態で
あって本文 identity ではない)。`--refetch-existing` は once-per-page 用。

## bin/cal-oshirase-fetch

飯能市公式サイト「新着情報」RSS パーサ + 本文取り込み + LLM 要約 (Claude Haiku 4.5)。
要約方針は [docs/ai-content-policy.md](../docs/ai-content-policy.md) 参照。

```
cal-oshirase-fetch [--out-dir events] [--once-per-page] [--refetch-existing]
                   [--rehash-only] [--backfill-diff] [--since YYYY-MM-DD]
                   [--dry-run] [--min-items 0]
```

動作モードは shicho-blog と対称: **incremental (デフォルト)** は dtstart=取得日・
`source.publish_date` に RSS 公開日 (dc:date) を保持・description 冒頭に
`🆕 新着掲載 (公開日: …)` / `🔄 内容更新 (公開日: …)`。`--once-per-page` (legacy) は
dtstart=公開日で 1 page = 1 YAML。

### 世代リンクと差分要約 (incremental mode)

同じ `page_id` の記事が更新されると別 YAML が生成されるが、その YAML は
`source.supersedes` に**直前 1 世代の uid** を持つ。チェーンを辿れば全世代に到達する。

```yaml
source:
  id: "7334"
  publish_date: "2026-08-07"
  supersedes: "oshirase-7334@hanno.city.tecoli.com"
```

同一記事の全世代は `grep -rn 'id: "7334"' calendar/events/` で引ける。

`description` 冒頭の status header は更新時に 2 行になる:

```
🔄 内容更新 (公開日: 2026-08-07 / 前回掲載: 2026-05-01)
主な変更: 物件 A・B・C の個別入札を新設。入札日を 6/19 から 9/11 に再設定。
```

「主な変更」は**前世代の description (= 前回の LLM 要約) と今回の本文**を Claude Haiku に
比較させて生成する (`diff_with_llm`)。元記事の本文は保存していないため、旧要約 × 新本文の
非対称な比較になり、要約から漏れていた項目が「新規」に見える誤検出がありうる。
prompt 側で「言い回しの違いを変更として報告しない」「要約に無い項目を新設と断定しない」を
明示して抑えている。LLM 不可 / 前世代が `url-only` / 出力が空 のときは差分行を省く。

### 「A から A に変更」の機械検算

**prompt の指示だけでは足りない。** 「同じ値なら変更ではない」と明示し
`temperature=0` にしてもなお、LLM が同値の対を書く事例が本番で出た
(2026-08-19、`oshirase-7334-62e7b2`):

```
主な変更: 物件Aの最低売却価格が1,970万円から1,970万円に、入札保証金が295.5万円から
295.5万円に変更されました。物件Bの最低売却価格が4,690万円から4,690万円に、…
```

4 対すべてが同値、つまり行全体が根拠のない生成だった。名指しできる変更が存在しない
場面で「何が変わったか」を答えさせられ、手元にある値で型を埋めた形。前回の本文を
保存していないため、そもそも値の異同を確かめる材料が LLM 側に無い。

**プロンプトを強める方向では再発する**ので、生成後に `drop_unchanged_claims()` が
機械的に検査して落とす。

- 単位は**文** (`。` 区切り)。同値の対を 1 つでも含む文は、その文の生成が信用
  できない証拠なので丸ごと捨てる (節だけ削ると日本語が壊れる)。真の変更を述べた
  別の文は残る
- 全部落ちたら `None` = 「主な変更」行を出さない
- 検出は**数値を伴う対に限る**。非数値の同値も理屈上ありうるが、緩いパターンは
  真の変更通知を誤って削除する危険がある
- 左辺は値の maximal な token を取る (直前が数字・カンマでないことを要求)。
  これが無いと「1,970万円から970万円に」の左辺から `970万円` だけを切り出して
  真の変更を同値と誤判定する

テストは `tests/test_diff_verify.py` (本番で出た文字列をそのまま材料にしている)。

`supersedes` も status header も **`content_hash` には含めない**ので、既存 YAML の
hash は動かず、カレンダーが氾濫することはない。

既存イベントへの後付けは `--backfill-diff` (既定の `--since` は前日 = アプリ表示窓の下限):

```
cal-oshirase-fetch --backfill-diff [--since YYYY-MM-DD] [--dry-run]
```

RSS フィードは見ず、`events/` を走査して対象記事だけ再 fetch する。
`content_hash` / `uid` / `dtstart` / ファイル名・要約本体・`translations` ブロックには
触れないので、`cal-daily.yml` には組み込まない一回性の操作。

3 方式で description を生成 (本文長で自動分岐):

| method | 条件 | description |
|---|---|---|
| `url-only` | 本文抽出失敗 (<50字) | URL のみ。**LLM は呼ばない** (ハルシネーション防止の安全装置) |
| `full` | 50〜400字 | 元記事の本文をそのまま全文転載 + URL |
| `llm-haiku-4-5` | 400字超 | Claude Haiku 4.5 で要約、冒頭に「AI による要約 (正確な情報は元記事をご確認ください)」明示 |

実装ポイント:
- 本文抽出は `<div id="contents-in">` を境界に統一 (`free-layout-area` あり/なし両 HTML 構造に対応)
- LLM 出力は Markdown 記法除去 post-process あり (Google Calendar は plain text 扱い)
- content_hash は (title, date, body) ベース → **method / format_version / LLM 出力は含めない**
  - LLM 非決定性に関わらず idempotent
  - body 変化がなければ LLM を呼ばずに既存 YAML を温存
  - `DESCRIPTION_FORMAT_VERSION` 定数を bump すると wrapper 文言改変を全件に伝播
- **HTTP Conditional GET 非対応** (`feed.php` は動的生成で cache header を返さない)

`source.summary_method` フィールドに上記 method が記録される (後の再生成判定に利用)。

## bin/cal-translate-en

`events/` 全 YAML を Claude Haiku 4.5 で英訳し、各 YAML 内に
`translations.en.{summary,description,translation_hash,model,translated_at,format_version}`
を in-place 格納するスクリプト。

```
cal-translate-en [--events-dir DIR] [--dry-run] [--limit N] [--only-uid UID]
```

- 翻訳トーンは Plain English (一般読者向け、行政用語は意訳、固有名詞はローマ字)
- 出力 description の冒頭に「Automated translation (refer to source for accuracy)」disclaimer
- 元記事 URL を「Source (Japanese): URL」として末尾保持
- Markdown 記法は除去 (出力先が plain text Google Calendar 想定)
- 入力前処理: 元 description の冒頭「AI による要約…」行と末尾 URL 行は LLM に渡さない (重複翻訳防止)
- 写真 URL 行 (`写真: <url>`) も `split_photo_lines()` で剥がしてから LLM に渡し、英語側は `Photo: <url>` として機械的に復元する (LLM に URL を触らせない = 改変・脱落を防ぐ)
- `translation_hash` は (元 summary, 元 description, lang) ベース
  - 元の日本語が変わった時のみ再翻訳
  - LLM 非決定性に関わらず idempotent
  - **`format_version` は hash に入っていない。** 入れると wrapper/プロンプトを
    直した瞬間に全件再翻訳が走るため意図的に外してある。既存訳に遡って
    反映したいときは `--rehash-only` で明示的に回す

### 応答形式はサーバ側で強制する + 引き直す

`output_config.format` に `json_schema` を渡している (`OUTPUT_SCHEMA`)。
**プロンプトに「JSON で返せ」と書くだけでは足りない。** 原文の `「」` を英語の
`"` に訳した瞬間、エスケープされない `"` が JSON 文字列の中に入って
`json.loads` が落ちる。2026-08-22 の CI がこれで赤になった
(1 件だけ失敗 → run 32590407302)。

同じ癖は `docs/superpowers/specs/2026-08-10-tourism-news-design.md` にも
記録がある (「そのままコピー」と指示しても引用符を打ち直す)。**LLM に
JSON を書かせる箇所は、原文に括弧類が入りうる時点で同じ穴がある。**

schema を渡しても 100% ではない。同じ記事で **95 回中 1 回**、壊れた JSON が
返った (2026-08-23 実測)。1 件の失敗でジョブ全体が赤になるので、
**JSON が読めなかったときだけ** `LLM_MAX_ATTEMPTS` 回まで引き直す。
通信・HTTP の失敗は引き直さない (呼出側が errors を数え、翌日の実行が拾う)。

## CI (GitHub Actions)

2 本構成:
- **`cal-daily.yml`** — 本番フロー (crawl → apply → translate → snapshot)。下記参照。
- **`cal-golden-test.yml`** — 軽量回帰テスト。`calendar/bin/**` / `sources.yaml` / `tests/**`
  変更時 (push + PR) に `python3 calendar/tests/run-golden` を実行。ネットワーク不使用・数秒。
  出力 YAML がバイト一致で維持されているか (= content_hash 不変 = カレンダー氾濫なし) を検証する。
  詳細は下記「テスト (golden 網)」。

### cal-daily.yml

`.github/workflows/cal-daily.yml` (毎日 03:00 JST 起動 + `calendar/bin/**` 変更時の push trigger):

1. **Pre-sync snapshot** — Calendar 状態を `snapshots/` に backup
2. **各 source crawler を順次実行** (tourism / shiminkaikan / gikai / shicho-blog / oshirase)
3. **Fetch manual edits** — Calendar UI で手動編集された event を YAML に取り込み (`--update-manual`)
4. **Safety check** — 変更ファイル数上限 / スコープ制限 / 異常検知
5. **Commit events + http-cache changes** — `events/` と `.http-cache.json` を commit + push
6. **Apply JP to Calendar (if drift)** — `--only-managed` で手動 event 温存しつつ反映
7. **Translate to English** — stale / 新規 YAML だけ `cal-translate-en` で英訳
8. **Commit translation changes** — `translations.en.*` 追加分を commit + push
9. **Apply EN to Calendar (if drift)** — `--only-managed` **無し** で適用 (= 手動 event の英訳も Calendar に届く)
10. **Post-sync snapshot** — 反映後の状態を再度 `snapshots/` に保存
11. **Discord 通知** — 当日の差分まとめを送信

### `--only-managed` の非対称性 (JP / EN)

| 言語 | `apply-all` | 理由 |
|---|---|---|
| JP (`default`) | `--only-managed` 付き | 手動 event は Calendar UI で人が編集する → CI で上書きさせない |
| EN (`en`) | filter 無し | EN は LLM 生成、人が Calendar UI で手編集する想定無し → 翻訳更新は手動 event にも届ける |

Safety policy:
- `timeout-minutes: 10` でフリーズ強制 kill
- 件数閾値 (各 fetcher の `--min-*`) で異常時 apply 拒否
  - 抽出件数 (= written + 304 skipped) で判定 (write-skip による誤発火回避)
- 変更ファイル数の上限 (events 50 / snapshots 200) で巨大誤更新を拒否
- スコープ制限 (`events/` / `snapshots/` / `.http-cache.json` 外への変更を拒否)
- `concurrency` group で並列実行禁止
- URL ホワイトリスト + canonical URL 一致でリダイレクト誤データ排除

### HTTP Conditional GET (efficiency)

city.hanno.lg.jp 配下の静的ページは ETag / Last-Modified 対応のため、`fetch_with_cache()` で 304 を受けて parse / write を全 skip。ETag / Last-Modified は `calendar/.http-cache.json` に永続化 (git で commit して CI runs 間で持続)。

> **⚠️ 新クローラの初回だけの罠。** 初回取込は手元で実行して差分を見るのが原則だが、
> その実行で `.http-cache.json` に入った ETag を**一緒に commit してはいけない**。
> 最初の CI 実行が 304 を受けて全 skip し、`--min-items 1` なら失敗、0 なら「何も
> していないのに緑」になる。commit するのは `events/` だけにし、`.http-cache.json`
> の新規エントリは戻す (`git checkout -- calendar/.http-cache.json`)。CI が自分で
> 取得して自分で書けば、以降は正しく効く。

対応状況:
- ✅ `cal-shiminkaikan`, `cal-gikai`, `cal-shicho-blog` (city.hanno.lg.jp)
- ✅ `cal-oshirase` の**記事ページ** (city.hanno.lg.jp。実測で 50 件すべて 304)
- ❌ `cal-oshirase` の**フィード** (`feed.php` は動的生成で cache header を返さない)
- ⚠️ `cal-tourism` — `hanno-tourism.jp` が `ETag` / `Last-Modified` を返さないので条件付き
  GET は使えない。代わりに REST API の `modified_gmt` を `.http-cache.json` に相乗りさせて
  同等の効果を得ている (上記「更新検知 (modified_gmt)」参照)

### 調査済み: 市サイトのサイトマップは更新検知に使えない (2026-08-09)

`cal-oshirase-fetch` の所要時間 (CI 実測 35〜53 秒) は、記事 50 件それぞれへの条件付き GET の
往復が支配的。すべて 304 が返るので本文取得もパースも LLM も走っていないが、「304 です」と
言ってもらうための往復 50 回は残る。

これを `https://www.city.hanno.lg.jp/sitemap.xml` の `lastmod` で省けないか調べたが、
**使えなかった**。同じ発想で調べ直さないよう結果を残す。

サイトマップの構造 (実測):

- `sitemapindex` 形式。子サイトマップ 1051 個 = ディレクトリごとに 1 つ、それぞれ `lastmod` 付き
- 親サイトマップは 193KB を 0.19 秒で取得できる (1 リクエスト)
- 子サイトマップには URL 別の `lastmod` がある
- 過去 1 日に `lastmod` が動いたディレクトリは 1051 中 4 件 — 一見すると強力な絞り込みに見える

**却下した理由: `lastmod` がページの更新を反映していない。** `.http-cache.json` に蓄積済みの
実 `Last-Modified` 154 件と突き合わせた結果:

| 対象 | 件数 | ディレクトリ `lastmod` がページの `Last-Modified` より古い | うち 1 日以上古い |
|---|---|---|---|
| 市長ブログ | 75 | 75 | 71 |
| お知らせ系 | 79 | 62 | 53 |

最悪ケースは約 193 日のずれ。例: 市長ブログ 2026 年 1 月の記事群はページの `Last-Modified` が
`2026-08-07 14:36` なのに、ディレクトリの `lastmod` は `2026-01-26 17:20` のまま。
これで条件付き GET を省くと更新を取りこぼす。

サンプル 1 件 (お知らせ 7334) では一致していたので、少数の確認で判断しないこと。
**「更新日時らしきフィールドがある」ことと「それが更新を反映している」ことは別。**
tourism の `modified_gmt` が使えたのは、あれが WordPress の投稿ごとの一次データだったため。

副産物として、`Last-Modified` はサーバ側の一括再生成でも動くことが分かった (市長ブログ
2026 年 1 月の記事が数秒以内に一斉に同じ値へ)。内容が変わっていなくても 304 でなく 200 が
返る日があり、その受け皿が `content_hash` 判定になっている。

なお `https://www.city.hanno.lg.jp/robots.txt` は 404 で、サイトマップ以外に機械可読な
入口は見つかっていない。

## 都市設定 (city.yaml)

`uid_namespace` / `user_agent` / 管理対象カレンダー / `source.type` → カレンダーの
ルーティングを持つ。`calendar/bin/` のコードはこれを読むだけで、都市固有の値を
**1 つも埋め込んでいない** (2026-08-21 時点で `_lib.py` に残る "hanno" はコメントと
解析例の 3 箇所のみ、`cal-gcal` に残るのはツール自身の名前だけ)。

**⚠️ `uid_namespace` を変えてはいけない。** iCalUID の `@` 以降にそのまま入るので、
変えると全イベントの UID が変わり、旧 UID が残ったまま全件が再作成される。

多都市展開時は、各 data repo がこのファイルを自分の値で持つ。

## 配信元を最初に見る

新しい配信元に当たったとき、**コードを書く前の 10 分**でここまで分かる。
「先に決める 4 つ」(skill) の入力はすべてこれで揃う。

```bash
UA="myhanno-calendar-fetcher/0.1 (+https://city.tecoli.com)"

# 1. ヘッダ — 条件付き GET が使えるか、何で動いているか
curl -sI -A "$UA" "$URL" | head -8

# 2. 本文を取って素性を見る
curl -s -A "$UA" "$URL" -o /tmp/src.html -w "bytes=%{size_download}\n"
grep -oE '<title>[^<]*</title>|generator[^>]*content="[^"]*"' /tmp/src.html

# 3. タグを剥がして「何が載っているか」を読む
python3 -c "
import re,sys
h=open('/tmp/src.html',encoding='utf-8',errors='replace').read()
b=re.sub(r'<script.*?</script>|<style.*?</style>','',h,flags=re.S)
print(re.sub(r'\n\s*\n+','\n',re.sub(r'<[^>]+>','\n',b)).strip()[:2000])"

# 4. リンク — 期間の送り、詳細ページ、姉妹カレンダー
python3 -c "
import re
h=open('/tmp/src.html',encoding='utf-8',errors='replace').read()
for u,t in re.findall(r'href=\"([^\"]+)\"[^>]*>([^<]{0,30})',h): print(u,'|',t.strip())" | sort -u

# 5. 明示された制限
curl -s -A "$UA" "$(echo "$URL" | grep -oE '^https?://[^/]+')/robots.txt" | head
```

読み取れることと、その先の判断:

| 見えたもの | 意味すること |
|---|---|
| `Last-Modified` / `ETag` がある | `fetch_with_cache()` の条件付き GET が効く。毎日全文を取らずに済む |
| `generator` が WordPress | REST (`/wp-json/`) と RSS が候補。**ただし REST は国外 IP から遮断されうる** (「先に決める」2 番) |
| 期間を送るリンクが無い | 一度に取れる集合が現在の期間だけ。集合同期型の削除ガードは incoming の日付範囲に閉じるので、これは自然に扱える (範囲外の過去を消さない) |
| 一覧に要約 + 詳細ページ | 二段取得。既存では oshirase / shicho-blog が同じ形 |
| 単発 / 規則 / 状態 が混在 | 普通のこと。規則は `rrule`、状態も落とさない (下の 2 節) |
| `robots.txt` が 404 | **許可ではない**。利用規約は別途確認する (「先に決める」0 番) |

**調査結果をこの README に書き残さないこと。** 個別の配信元の観測は、次に見たときには
変わっている。残すのは「何を見るか」だけでよい — 上のコマンドで 10 分で取り直せる。

## 繰り返し予定 (rrule)

**実装済みだが 2026-08-22 時点で使用例ゼロ**。コード内のコメントが「今は無いはず」と
書いているのはそのため。使ってよい。

YAML に `rrule:` を置くと `cal-gcal` が `RRULE:` を前置して Calendar の `recurrence`
に渡す。値は RFC 5545 の RRULE 本体 (`RRULE:` は付けない)。

```yaml
uid: lib-ohanashi@hanno.city.tecoli.com
summary: おはなしのじかん
dtstart: 2026-04-04
rrule: FREQ=WEEKLY;BYDAY=SA,SU;UNTIL=2027-03-31
```

往復が成立することは実装で確認済み (2026-08-22):

| 経路 | 実装 |
|---|---|
| YAML → Calendar | `doc["rrule"]` → `body["recurrence"] = ["RRULE:..."]` |
| Calendar → YAML | `recurrence` から `RRULE:` を剥がして `rrule:` に戻す |
| 差分検知 | `COMPARE_FIELDS` に `recurrence` が入っている |
| マスターの保全 | 同期経路の `events.list` は `singleEvents: False`。繰り返しマスターが
  インスタンスに展開されないので、読み戻しで壊れない (`find` だけ `True`) |

終日イベントの `UNTIL` は `normalize_rrule_until()` が date-time → date に直す
(Calendar が終日 + date-time UNTIL を弾くため)。

**いつ使うか**: 「毎週土日祝」のような**規則そのものが配信元に書かれている**とき。
規則を N 件の個別イベントに展開すると、規則が変わったときに全件を作り直すことになり、
削除ガードの上限にも当たる。逆に、配信元が個別の日付を列挙しているだけなら展開された
まま扱う (規則を推測しない)。

## 状態 (休館日・開館時間) の扱い

**配信元のカレンダーに書いてあるなら、そのまま出す。** 休館日も含めて取り込む。

判断の経緯 (2026-08-22、施設カレンダーの検討時):

アプリは既に開館状態を持っている。city-tecoli の `src/lib/places.ts` が Google Places
の `regularOpeningHours` を読み、`OpenStatus` (`open` / `opening_today` / `closed` /
`holiday`) として施設カードに出す。だから定例の休館日をカレンダーにも入れると、
情報としては重複する。

**それでも落とさない。** 「これは他所で取れるから要らない」と我々が選り分け始めると、
配信元が伝えようとしていることを、こちらの都合で編集することになる。**その粒度で
制御するのは立ち入りすぎ**という判断。

これは削除ガードの節の「根拠のない状態表示は行わない」と同じ原則の裏返しである。
あちらは*配信元が言っていないことを言わない*、こちらは*配信元が言っていることを
そのまま出す*。どちらも「我々は配信元より事情を知らない」という前提から来ている。

実装上の注意:

- 終日イベントとして出し、タイトルに何が起きるかを書く (「休館」)。`status: canceled`
  のような状態表示は使わない (根拠が無いため — 削除ガードの節と同じ)。
- 規則そのもの (「まいしゅう げつようび は、おやすみです」) が書かれているなら、
  N 件に展開せず `rrule` を使う → 「繰り返し予定 (rrule)」。

## クローラ設定 (sources.yaml)

クローラの city 固有値 (feed/top URL・uid_prefix・summary_prefix・source_type・
allowlist 等) は `calendar/sources.yaml` に外出しし、各クローラが起動時に
`_lib.load_source_config(<key>)` で読む。多都市展開時は各 data repo がこのファイルを
持ち、クローラのコード (`calendar/bin/`) は都市非依存に保つ設計。

```yaml
oshirase:
  uid_prefix: oshirase
  source_type: city-hanno-oshirase
  summary_prefix: "ℹ️ "
  feed_url: "https://www.city.hanno.lg.jp/cgi-bin/feed.php?…"
  url_host_allowlist: www.city.hanno.lg.jp
shicho-blog:
  uid_prefix: shicho-blog
  source_type: city-hanno-shicho-blog
  summary_prefix: "📝 市長："
  top_url: "https://www.city.hanno.lg.jp/…/shichoblog/index.html"
  url_host_allowlist: www.city.hanno.lg.jp
  url_path_prefix: "/…/shichoblog/"
```

- ⚠️ config は必ず **この hanno-data repo 内**に置く。本体 city-tecoli repo の
  `cities/hanno/config.yaml` ではダメ — CI は hanno-data repo だけを checkout するため
  本体 repo のファイルは見えない。
- 移行済み: oshirase / shicho-blog / tourism-news / cci-chef / cci-event。残りは順次。
- 都市そのものの設定 (`uid_namespace` / `user_agent` / カレンダー ID / source_type の
  ルーティング) は **`calendar/city.yaml`** に分けてある。source 単位ではなく repo 単位の
  値なので別ファイルにした。`_lib.load_city_config()` が読む。

## テスト (golden 網)

クローラ出力 YAML はバイト単位で安定していることが要件 (1 バイト変わると content_hash が
変わり全件再生成 → カレンダー氾濫)。`calendar/tests/run-golden` が固定 fixtures を入力に
クローラを hermetic 実行し、出力を golden とバイト一致で照合してこれを守る。

```bash
python3 calendar/tests/run-golden            # 比較 (一致=exit 0、不一致=exit 1 + 差分表示)
python3 calendar/tests/run-golden --update   # golden 再生成 (初回 / 意図的な出力変更時のみ)
python3 calendar/tests/capture-fixtures      # fixtures を実サイトから再取得 (dev tool、ネットワーク使用)
```

golden シナリオ:

| golden dir | crawler | seed | 何を固定するか |
|---|---|---|---|
| `cal-oshirase-fetch` | oshirase | 無し | 新着掲載 (🆕) の出力 |
| `cal-oshirase-update` | oshirase | `seed/cal-oshirase-update/` | 既存 YAML がある状態での更新検知 (🔄 + `supersedes`) |
| `cal-shicho-blog-fetch` | shicho-blog | 無し | 市長ブログの出力 |
| `cal-tourism-news-fetch` | tourism-news | 無し | 告知 / 本番の 2 イベント生成 |
| `cal-tourism-news-existing` | tourism-news | `seed/cal-tourism-news-existing/` | 再実行で重複・移動が起きないこと |
| `cal-cci-chef-fetch` | cci-chef | 無し | 当番表 95 件の初回取込 |
| `cal-cci-event-fetch` | cci-event | 無し | 商工会議所の告知 49 件の初回取込 |
| `cal-cci-event-update` | cci-event | `seed/cal-cci-event-update/` | **追記型**の更新検知 — 旧世代が残り新世代が `supersedes` 付きで増える (50 件) |
| `cal-cci-chef-update` | cci-chef | `seed/cal-cci-chef-update/` | 既存 YAML が更新されること |
| `cal-cci-chef-delete` | cci-chef | `seed/cal-cci-chef-delete/` | 取得側に無い**未来**の予定が消えること |
| `cal-cci-chef-keep-past` | cci-chef | `seed/cal-cci-chef-keep-past/` | 取得側に無くても**過去**の予定は残ること |

集合同期型 (cci-chef) の削除は「**golden にそのファイルが無い**」という形で
表現される — `run-golden` が生成ファイルの key set を golden と比較するため、
消えたファイルは key set の差として検出される。また削除判定は「今日」に依存
するので、`SET_SYNC_TODAY` で基準日を固定して `--today` で渡している (固定
しないと fixture 内の予定が日々「過去」に流れ、削除の可否が変わって golden が
壊れる)。

- `fetch` / `fetch_with_cache` を monkeypatch して `fixtures/<crawler>/`
  (+ `manifest.json` で url→file) を返す。oshirase は `_llm_available()` を False に固定して
  決定論化 (= 要約も差分行も LLM を通らない)。shicho-blog は未捕捉の月を 304 skip。
- `seed/<name>/` を置くと、その中身が `--out-dir` に事前展開されてから crawler が走る
  (= 既存 YAML がある状態の再現)。seed 自身も出力として golden に含まれる。
- dtstart/dtend/fetched_at は incremental では実行日依存なので、比較前にプレースホルダへ
  **正規化**する。content_hash は日付非依存なのでそのまま比較 → ハッシュ回帰は確実に検知。
- **クローラ・`sources.yaml`・fixtures を変更したら必ず `run-golden` を緑にすること。**
  出力を意図的に変えた場合のみ `--update` で golden を更新し、差分を PR で確認する。
- **シナリオを足す手順**: `run-golden` に `_setup_<name>(m, crawler, manifest)` を書いて
  HTTP 層を fixture に差し替え、`# (golden 名, crawler スクリプト名, setup, seed dir 名 | None)`
  のタプル一覧に 1 行足す。fixture は `fixtures/<crawler>/` + `manifest.json` (url→file)。
  既存 YAML がある状態を再現したいときは `seed/<name>/` を置く (seed 自身も golden に含まれる)。
  初回は `--update` で golden を生成し、差分を目で確認してから commit する。
- **スタブは取得の最下層に当てる。** 上位関数 (「記事一覧を組み立てて返す」層) を
  丸ごと差し替えると、解析コードが 1 行も走らないまま golden が緑になる。2026-08-21 に
  cci-event でこれを踏んだ: REST 形状の fixture で `fetch_posts()` をスタブしていたため、
  REST → RSS 切替で書き直した RSS 解析が未検証のまま通っていた。`fetch_feed()` (生の
  フィード本文を返す層) をスタブに変えたところ、6 件の出力差が即座に検出された。
  **判断基準: そのスタブを当てて、今回書いたコードは実行されるか。**

### ユニットテスト

golden 網とは別に、純粋関数・API ラッパのユニットテストがある。すべて
ネットワーク非依存で、`python3 calendar/tests/<file>` で個別に走る。

| ファイル | 対象 |
|---|---|
| `test_last_modified_dating.py` | `_lib` の Last-Modified → dtstart 変換 |
| `test_call_llm.py` | `_lib.call_llm` (httpx 差し替え、temperature / 失敗時 None) |
| `test_normalize_weekday.py` | `_lib` の囲み曜日文字 (㈯/㊏) 正規化 |
| `test_tourism_discovery.py` | tourism の URL 正規化 |
| `test_tourism_api.py` | tourism の REST API 取得 / modified_gmt 判定 / サニティチェック |
| `test_news_api.py` | news の REST API 取得 / ページング / backfill フィルタ |
| `test_news_extract.py` | news の LLM 抽出 (JSON パース / コードフェンス / 公開日送信) |
| `test_news_verify.py` | news の開催日 機械検算 6 項目 (実データの失敗モードを回帰) |
| `test_news_gating.py` | news の本番作成条件 / 手動 YAML 衝突検出 |
| `test_news_yaml.py` | news の YAML 生成 / UID / 先頭日付の除去 |
| `test_news_main.py` | news の process_news / short_body と llm_fail の分離 |
| `test_news_generations.py` | news の告知 世代リンク (supersedes / 状態ヘッダ) |
| `test_news_cancel.py` | news の中止書き換え / 本番の取り下げ |
| `test_description_parts.py` | `_lib` の description 分解 (block 読み出し / status 行 / disclaimer) |
| `test_generation_index.py` | oshirase の page_id 別世代索引 |
| `test_diff_line.py` | oshirase の差分要約行 (LLM は差し替え) |
| `test_backfill_rewrite.py` | oshirase の in-place 書き換えヘルパ |
| `test_calendar_paging.py` | `cal-gcal` の `events.list` ページング |
| `test_apply_helpers.py` | `cal-gcal` の同期判定 / マージ |
| `test_event_index.py` | `cal-gcal` の `EventIndex` |
| `test_apply_recheck.py` | `cal-gcal` の書き込み前再確認 |

## YAML スキーマ例

最小例 (手動キュレーション):

```yaml
uid: "evt-20260606-01@hanno.city.tecoli.com"
summary: "西武・電車フェスタ2026 in 武蔵丘車両検修場"
location: "武蔵丘車両検修場"
dtstart: "2026-06-06"
dtend: "2026-06-06"

render:
  gcal:
    mode: single-allday
```

クローラ管理 + 本文取り込み + 英訳済み (oshirase 例):

```yaml
uid: "oshirase-13166@hanno.city.tecoli.com"
summary: "ℹ️ 課税(非課税)・所得証明書のみコンビニ交付サービスを停止します"
url: "https://www.city.hanno.lg.jp/soshikikarasagasu/sogoseisakubu/johosystem/13166.html"
dtstart: "2026-05-15"
dtend: "2026-05-15"
description: |-
  AI による要約 (正確な情報は元記事をご確認ください)

  令和8年5月31日(日曜日)〜令和8年6月2日(火曜日)終日、システム年度更新のため、…

  飯能市公式サイト 新着情報: https://www.city.hanno.lg.jp/...

render:
  gcal:
    mode: single-allday

source:                        # ← クローラ管理マーカー (手動なら無し)
  type: city-hanno-oshirase
  id: "13166"
  url: "https://www.city.hanno.lg.jp/..."
  fetched_at: "2026-05-19T..."
  content_hash: "sha256-…"
  summary_method: "llm-haiku-4-5"  # url-only | full | llm-haiku-4-5

translations:                  # ← cal-translate-en が in-place 追加
  en:
    summary: "ℹ️ Convenience store service for tax/non-taxable and income certificates suspended"
    description: |-
      Automated translation (refer to source for accuracy)

      Due to system maintenance for the annual update, …

      Source (Japanese): https://www.city.hanno.lg.jp/...
    translation_hash: "sha256-…"
    model: "claude-haiku-4-5"
    translated_at: "2026-05-19T..."
    format_version: 1
```

## 関連ドキュメント

- [docs/ai-content-policy.md](../docs/ai-content-policy.md) — LLM 要約 / 翻訳の表示方針、調査根拠 (AI事業者ガイドライン、著作権法 32 条引用、Yahoo!ニュース実例)
