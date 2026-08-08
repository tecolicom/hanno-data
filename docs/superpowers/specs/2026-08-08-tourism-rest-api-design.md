# cal-tourism-fetch を WordPress REST API ベースの更新検知に変える

作成日: 2026-08-08

## 背景 / 問題

日次 CI (`cal-daily.yml`) の所要時間 130 秒のうち、`Crawl hanno-tourism` が **55 秒**を占める
(次点は `Crawl city-hanno-oshirase` の 37 秒)。

原因は、hanno-tourism.jp が `ETag` / `Last-Modified` を返さないため条件付き GET が使えず、
**39 ページを毎日フル取得している**こと。実測したレスポンスヘッダ:

```
HTTP/2 200
server: nginx
date: Sat, 08 Aug 2026 10:05:56 GMT
content-type: text/html; charset=UTF-8
```

1 ページ約 1.4 秒 × 39 ページ。取得したページの大半は内容が変わっていない。

## 調査で判明したこと (すべて実機で確認、2026-08-08)

### サイトは WordPress で REST API が公開されている

ページのレスポンスヘッダが自己申告している:

```
link: <https://hanno-tourism.jp/wp-json/>; rel="https://api.w.org/"
link: <https://hanno-tourism.jp/wp-json/wp/v2/tour/4390>; rel="alternate"; type="application/json"
```

ツアーはカスタム投稿タイプ `tour`。1 リクエストで全件のメタ情報が取れる:

```
GET /wp-json/wp/v2/tour?_fields=id,link,slug,modified_gmt,tour-month&per_page=100
→ x-wp-total: 40, x-wp-totalpages: 1
```

### 掲載制御は `tour-month` タクソノミー

一覧ページに載る条件は **`tour-month` が 1 つ以上割り当てられていること**だった。

| | 件数 |
|---|---|
| API 全件 | 40 |
| `tour-month` あり | **39** |
| `tour-month` なし | 1 (`ec-tairakuri-wagashi`) |
| 一覧ページのスクレイピング実測 | **39** |

`tour-month` ありの 39 件は、現在のスクレイピング結果と**差分ゼロで完全一致**した。
タクソノミーの件数は 8月=12 / 9月=17 / 10月=17 で、1〜7月・11月・12月は 0 —
過去の月はクリアされ、直近数か月だけ割り当てる運用と読める。

したがって「一覧ページの編集意図を尊重するか、API の全件を取るか」というトレードオフは
存在せず、**API 側で編集意図を正確に再現できる**。

なお `ec-tairakuri-wagashi` (`tour-month: []`、`status: publish`、`modified_gmt` は
40 件中最古の 2025-05-12) を現行クローラが拾っていないのはバグではなく、正しい除外。

### 日次の変更件数は少ない

`modified_after` で実測:

| 期間 | 更新件数 |
|---|---|
| 8/7 以降 (約 1 日) | **6** / 40 |
| 8/6 以降 (約 2 日) | 21 / 40 |
| 8/1 以降 (約 1 週間) | 32 / 40 |
| 7/8 以降 (約 1 か月) | 33 / 40 |

バースト的に編集される (8/6 に 15 件、8/7 に 6 件) が、平常時は 0〜6 件。

### 本文の日程は API から取れない

`content.rendered` は 141 字の紹介文のみで、クローラが抽出している
`<dl><dt>開催日・時間</dt><dd>…</dd></dl>` は含まれない。API レスポンスに `acf` /
`meta` キーは無く、日程は ACF 等のカスタムフィールドからテーマが HTML に描画している。

→ **「API で更新を検知 → 変わったページだけ HTML を取る」の二段構えになる。**
1 リクエストで完結はしない。

### ページングの実動作

`per_page=15` で 3 ページに分割され、`x-wp-totalpages: 3`。
**範囲外のページは HTTP 400** (`{"code":"rest_post_invalid_page_number"}`) を返す。

`_lib.fetch()` はボディのみを返しヘッダを取れないため、`x-wp-totalpages` は読めない。

## 設計

### 1. ツアー一覧の取得を REST API に置き換える

新規の定数と関数:

```python
# Source セクションに追加 (多都市展開時は city 別 config に外出しする対象)
TOUR_API_URL = "https://hanno-tourism.jp/wp-json/wp/v2/tour"
TOUR_API_PER_PAGE = 100


def fetch_json(url: str) -> object:
    """URL を GET して JSON をパースして返す。

    _lib.fetch() (User-Agent 付き) の薄いラッパ。パース失敗は例外を伝播する。
    """


def fetch_tour_index() -> list[dict]:
    """REST API から tour 一覧を取得する。

    tour-month が空でない (= 一覧ページに載る = 現在提供中) ものだけ返す。
    要素は {"url": <末尾スラッシュ正規化済み>, "slug": ..., "modified_gmt": ...}。
    """
```

- エンドポイント:
  `{TOUR_API_URL}?_fields=id,link,slug,modified_gmt,tour-month&per_page=100&page=N`
- `tour-month` が空リストの投稿は除外する。
- `link` は末尾スラッシュ無しで返るので `normalize_tour_url()` を通し、`url_ok()` の
  allowlist で検証する (現行と同じガード)。
- ページング: `page=1` から順に辿り、**取得件数が `per_page` 未満なら終了**。
  加えて HTTP 400 で `rest_post_invalid_page_number` を含むレスポンスは終端として扱う
  (総件数が `per_page` の倍数のときに 1 ページ余分に要求するのを吸収)。
  `apply-all` の `maxResults:500` と同じ「静かな切り捨て」を作らないため。

削除するもの: `discover_tour_urls()`, `fetch_index_urls()`, `_TOUR_HREF_RE`,
`DEFAULT_INDEX_URL`, `--index-url`。

残すもの: `normalize_tour_url()`, `url_ok()`, `urls.txt` シード (手動ピン留め)。

**`--no-discover` の意味を読み替える。** 従来は「一覧ページのスクレイピングを行わず
`urls.txt` のみ使う」だったので、新しくは「**REST API を引かず `urls.txt` のみ使う**」
とする。この場合 API を呼ばないので `--min-tours` の判定も行わない (件数の根拠が無いため)。
ヘルプ文言も合わせて書き換える。

### 2. `modified_gmt` で変更分だけ取得する

状態は既存の `calendar/.http-cache.json` に相乗りさせる。URL キーの辞書に
`modified_gmt` フィールドを追加する:

```json
"https://hanno-tourism.jp/hanno-eco/tour/ec-tenta-kaibori/": {
  "modified_gmt": "2026-08-07T01:00:51"
}
```

このファイルは既に「URL ごとに前回何を知っていたか」を 154 URL 分保持し、git に
コミットされて CI 実行間で永続する。`_lib` の `load_http_cache()` /
`save_http_cache()` をそのまま使える。`fetch_with_cache()` は `etag` /
`last_modified` しか見ないので、キーを増やしても干渉しない。

判定:

- API の `modified_gmt` が保存値と一致 → **HTML を取得せず skip** (`unchanged` として計上)
- 一致しない / 保存値が無い → 従来どおり取得して `process_one()` で処理
- **処理が成功したツアーだけ保存値を更新する。** 失敗したものは更新しないので次回リトライされる

`--url` で単一 URL を指定した場合は API を引かず、`modified_gmt` 判定も行わない
(手動デバッグ用途なので常に取得する)。

### 3. サニティチェックを API 件数ベースに差し替える

現行の `--min-sessions 5` (抽出セッション総数が 5 未満なら exit 2) は、取得をスキップすると
**変更 0 件の日に必ず誤発火する**。2 つの目的に分離する。

- **`--min-tours` (新設、既定 20)**
  `tour-month` あり件数がこれ未満なら exit 2。API の崩壊・大量非公開・仕様変更を検知する。
  変更 0 件の日でも発火しない。現在 39 件なので既定 20 は約半減を許容する水準。
- **パース失敗の検知**
  「実際に取得したページのうちセッションが 1 件も取れなかったもの」を数える。
  1 件以上あれば WARN。**取得したページが 1 件以上あり、その全件が 0 セッションなら exit 2**
  (= HTML 構造変更の疑い)。取得 0 件の日はこの判定を行わない。

`--min-sessions` は廃止する。意味が変わったフラグを同名で残すと誤解を招くため。
`cal-daily.yml:81` の起動行も差し替える:

```yaml
# 変更前
run: ./calendar/bin/cal-tourism-fetch --out-dir calendar/events --min-sessions 5 || echo "hanno-tourism" >> "$RUNNER_TEMP/crawl-failures.txt"
# 変更後
run: ./calendar/bin/cal-tourism-fetch --out-dir calendar/events --min-tours 20 || echo "hanno-tourism" >> "$RUNNER_TEMP/crawl-failures.txt"
```

`--min-sessions` を削除するので、旧引数のまま実行されると argparse がエラーになる。
CI の変更を同じコミットに含めること。

### 4. API 失敗時は exit 2 で止める

スクレイピング経路へのフォールバックは持たない。以下はいずれも exit 2:

- API のリクエストが失敗する (ネットワーク / 4xx / 5xx)
- レスポンスが JSON としてパースできない
- `tour-month` あり件数が `--min-tours` 未満 (0 件を含む)

既存の events YAML は残るので、その日の取り込みが止まるだけ。CI が赤くなって気づける。

### 5. 完了時のログ

現行の `Done. urls ok=39 err=0 total sessions extracted=85` を、skip を可視化した形に変える:

```
Done. tours=39  fetched=6  unchanged=33  ok=6 err=0  sessions=12
```

`unchanged` が出ることで「速いのは手を抜いたからではなく変更が無いから」が読める
(oshirase の `unchanged=50` と同じ思想)。

## テスト

`calendar/tests/test_tourism_discovery.py` を API 版に書き換える。`gws` 相当の
ネットワーク呼び出し (`fetch_json`) を差し替えてネットワーク非依存で回す。

- `normalize_tour_url()` の既存テストは維持する (API の `link` 正規化に使うため)
- `tour-month` が空の投稿を除外する
- `tour-month` あり 0 件なら exit 2 (`--min-tours` 未満)
- 1 ページで収まる場合は 1 リクエストで終わる
- 複数ページある場合は全ページ辿って連結する (件数 < per_page で終了)
- 総件数が `per_page` の倍数のとき、HTTP 400 (`rest_post_invalid_page_number`) を
  終端として扱い例外を投げない
- `modified_gmt` 一致で取得対象から外れる / 不一致・未保存で取得対象になる
- 処理が失敗したツアーの `modified_gmt` を更新しない
- allowlist 外の `link` を除外する

golden テスト (`calendar/tests/run-golden`) は `cal-tourism-fetch` を対象に含んでいない
(現状 oshirase / shicho-blog の 2 クローラのみ) ため影響しない。

## やらないこと (YAGNI)

- **並列化** — 逐次取得が平常時 0〜6 件になるので不要。
- **`content.rendered` からの日程抽出** — API に日程が無いことを確認済み。
- **`ec-tairakuri-wagashi` の救済** — `tour-month` 未割当は「現在提供していない」という
  編集意図。除外が正しい挙動。
- **`fetch_json` を `_lib` に置く** — 今は tourism だけが使う。他のクローラが必要に
  なった時点で移す。
- **oshirase (37 秒) の高速化** — 条件付き GET は既に効いており (50 件すべて 304)、
  残るのは 304 を受けるための往復 50 回。別の設計判断が必要なので本 spec の範囲外。
