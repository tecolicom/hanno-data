# calendar/

Myはんのう Google カレンダー群 (`tecolicom@gmail.com` 所有、`city.tecoli.com/@hanno/` から ical 配信) を YAML で canonical に管理する仕組み。日本語 + 英語の 4 カレンダー構成。

## 基本方針

- **YAML が canonical**: `events/<year>/<MM-DD>_<uid>.yaml` (1 イベント 1 ファイル) が真の正本
- **Google Calendar は投影先**: 全イベントを終日にし、時刻情報は description 冒頭の `🕒 HH:MM–HH:MM` marker で保持
- **`source:` フィールドの有無で識別**:
  - `source:` あり → クローラ管理 (自動で更新・再生成される)
  - `source:` なし → 手動キュレーション (クローラは絶対に触らない、不可侵)
- **英訳は YAML 内 `translations.en.*` に格納**: 元の summary/description は不変、英訳が追加情報として隣に並ぶ

## カレンダー構成

JP/EN の 2 言語 × 用途別 2 系統 = 4 カレンダーを Service Account 1 つで管理:

| logical key | calendar 名 | 内容 | 対応 source.type |
|---|---|---|---|
| `default` | Myはんのう | 観光・市民会館・コミュニティ等 | hanno-tourism-jp / city-hanno-shiminkaikan / (手動) |
| `gikai` | 飯能市役所 | 市政情報・市長ブログ・お知らせ | city-hanno-gikai / city-hanno-shicho-blog / city-hanno-oshirase |
| `default.en` | Myはんのう（EN） | `default` の英訳 (同 source.type) | (同上) |
| `gikai.en` | 飯能市役所（EN） | `gikai` の英訳 (同 source.type) | (同上) |

routing は `source.type` ベース。`source.type` → `default` or `gikai` のマッピングが
`bin/cal-myhanno` の `SOURCE_TYPE_TO_CALENDAR` に定義。英語カレンダーは
`<base>.<lang>` 命名で base routing と lang を直交的に組み合わせる。

## ディレクトリ構成

```
calendar/
├── bin/
│   ├── _lib.py                  全 crawler の共通ヘルパ (HTTP fetch / cache / YAML 整形 / config 読込 / etc.)
│   ├── cal-myhanno              Google Calendar API ラッパ (Python + gws)
│   ├── cal-tourism-fetch        hanno-tourism.jp 決定論パーサ (LLM 不使用)
│   ├── cal-shiminkaikan-fetch   飯能市民会館 公演スケジュール取得
│   ├── cal-gikai-fetch          飯能市議会 議事日程取得
│   ├── cal-shicho-blog-fetch    市長ブログ取得 + 本文掲載 (LLM 不使用)
│   ├── cal-oshirase-fetch       飯能市公式お知らせ取得 + LLM 要約
│   └── cal-translate-en         events/ 全 YAML を英訳して translations.en.* に格納
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
│   ├── fixtures/<crawler>/      入力 HTML/RSS + manifest.json
│   ├── seed/<scenario>/         out-dir に事前展開する既存 YAML (更新検知シナリオ用)
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
| description 分解 | `strip_status_header(text)` — 冒頭の 🆕/🔄/📝 ブロックを除去 / `split_description(text)` — AI disclaimer 行と末尾 URL 行を剥がし `(本文, source_url)` を返す (status 行は残す。EN 側で訳すため) |
| クローラ設定 | `load_source_config(source_key)` — `../sources.yaml` から source 別の city 固有設定 dict を読む (不在 key は KeyError) |

## 認証

Google Cloud プロジェクト `city-tecoli` の Service Account
`myhanno-bot@city-tecoli.iam.gserviceaccount.com`。各カレンダーに対し
SA メアドを「予定の変更権限」(writer) で共有済み。

```
# ローカル
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/myhanno/sa.json

# CI (GitHub Actions secret に SA JSON 全文を入れる)
secrets.GWS_SA_JSON
```

`cal-myhanno` は env 未設定時に `~/.config/myhanno/sa.json` を自動 fallback する。

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

LLM 利用スクリプト (`cal-oshirase-fetch`, `cal-translate-en`) は
`ANTHROPIC_API_KEY` 環境変数が必要。

## 依存

- [googleworkspace/cli](https://github.com/googleworkspace/cli) (`gws`) — `brew install googleworkspace-cli`
- Python 3.10+
- `pyyaml`, `httpx`

## bin/cal-myhanno

Google Calendar 側を操作するためのコマンド群。内部で `gws` を呼ぶ。

```
cal-myhanno find [-q QUERY] [--time-min ISO] [--time-max ISO] [--json]
cal-myhanno show <event-id>
cal-myhanno set-allday <event-id> [--dry-run]                       # 時刻指定 → 終日 (marker 付き)
cal-myhanno set-timed  <event-id> [--dry-run]                       # 終日 (marker 付き) → 時刻指定
cal-myhanno fetch       [-o events] [--force] [--update-manual]     # Calendar → YAML 一括吸い上げ
cal-myhanno apply      <yaml-file> [--dry-run] [--lang LANG]        # YAML 1 件 → Calendar
cal-myhanno apply-all  [-d events] [--dry-run] [--lang LANG] [--only-managed]
                                                                    # events/ 全件 → Calendar
cal-myhanno diff       [-d events] [--lang LANG]                    # YAML と Calendar の整合チェック
cal-myhanno snapshot   [-o snapshots]                               # Calendar → JSON でバックアップ
cal-myhanno wipe       --confirm [--dry-run]                        # Calendar 全削除 (内部で先に snapshot)
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
cal-myhanno snapshot          # (念のため) 最新 snapshot
cal-myhanno wipe --confirm    # Calendar 全削除 (内部で自動 snapshot 取得)
cal-myhanno apply-all         # YAML から完全再投入 (iCalUID も復元)
cal-myhanno diff              # 整合確認 (0 件差分)
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
  タグ付け漏れが実測 2 件あるため。掲載可否は `announces_event_itself` が担う
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
- content_hash は (title, date, body, body_truncated) ベース → 本文変化を検知 (dtstart は含めない = 日付非依存)
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
- `translation_hash` は (元 summary, 元 description, format_version, lang) ベース
  - 元の日本語が変わった時のみ再翻訳
  - LLM 非決定性に関わらず idempotent
  - `TRANSLATION_FORMAT_VERSION` を bump すると wrapper 文言改変を全件に伝播

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
- 現状 oshirase / shicho-blog の 2 ソースのみ移行済み (Phase 1)。残りは順次。
- `uid_namespace` は今も `_lib.UID_NAMESPACE` 共有定数のまま (Phase 1 では外出ししていない)。

## テスト (golden 網)

クローラ出力 YAML はバイト単位で安定していることが要件 (1 バイト変わると content_hash が
変わり全件再生成 → カレンダー氾濫)。`calendar/tests/run-golden` が固定 fixtures を入力に
クローラを hermetic 実行し、出力を golden とバイト一致で照合してこれを守る。

```bash
python3 calendar/tests/run-golden            # 比較 (一致=exit 0、不一致=exit 1 + 差分表示)
python3 calendar/tests/run-golden --update   # golden 再生成 (初回 / 意図的な出力変更時のみ)
python3 calendar/tests/capture-fixtures      # fixtures を実サイトから再取得 (dev tool、ネットワーク使用)
```

golden シナリオは 3 本:

| golden dir | crawler | seed | 何を固定するか |
|---|---|---|---|
| `cal-oshirase-fetch` | oshirase | 無し | 新着掲載 (🆕) の出力 |
| `cal-oshirase-update` | oshirase | `seed/cal-oshirase-update/` | 既存 YAML がある状態での更新検知 (🔄 + `supersedes`) |
| `cal-shicho-blog-fetch` | shicho-blog | 無し | 市長ブログの出力 |

- `fetch` / `fetch_with_cache` を monkeypatch して `fixtures/<crawler>/`
  (+ `manifest.json` で url→file) を返す。oshirase は `_llm_available()` を False に固定して
  決定論化 (= 要約も差分行も LLM を通らない)。shicho-blog は未捕捉の月を 304 skip。
- `seed/<name>/` を置くと、その中身が `--out-dir` に事前展開されてから crawler が走る
  (= 既存 YAML がある状態の再現)。seed 自身も出力として golden に含まれる。
- dtstart/dtend/fetched_at は incremental では実行日依存なので、比較前にプレースホルダへ
  **正規化**する。content_hash は日付非依存なのでそのまま比較 → ハッシュ回帰は確実に検知。
- **クローラ・`sources.yaml`・fixtures を変更したら必ず `run-golden` を緑にすること。**
  出力を意図的に変えた場合のみ `--update` で golden を更新し、差分を PR で確認する。
- 現状 oshirase / shicho-blog の 2 クローラのみ対象 (Phase 1)。

### ユニットテスト

golden 網とは別に、純粋関数・API ラッパのユニットテストがある。すべて
ネットワーク非依存で、`python3 calendar/tests/<file>` で個別に走る。

| ファイル | 対象 |
|---|---|
| `test_last_modified_dating.py` | `_lib` の Last-Modified → dtstart 変換 |
| `test_tourism_discovery.py` | tourism の URL 正規化 |
| `test_tourism_api.py` | tourism の REST API 取得 / modified_gmt 判定 / サニティチェック |
| `test_description_parts.py` | `_lib` の description 分解 (block 読み出し / status 行 / disclaimer) |
| `test_generation_index.py` | oshirase の page_id 別世代索引 |
| `test_diff_line.py` | oshirase の差分要約行 (LLM は差し替え) |
| `test_backfill_rewrite.py` | oshirase の in-place 書き換えヘルパ |
| `test_calendar_paging.py` | `cal-myhanno` の `events.list` ページング |
| `test_apply_helpers.py` | `cal-myhanno` の同期判定 / マージ |
| `test_event_index.py` | `cal-myhanno` の `EventIndex` |
| `test_apply_recheck.py` | `cal-myhanno` の書き込み前再確認 |

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
