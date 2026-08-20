# 飯能商工会議所 お知らせカレンダー — 設計

ステータス: 設計 (2026-08-20 起案)。実装は未着手。

## 1. 背景

飯能商工会議所の告知 (`xo_event` 投稿タイプ、全 440 件) を取り込み、`cci` /
`cci.en` の 2 カレンダーとして配信する。

直接のきっかけは 2 つある。

**(a) 商工会議所のカレンダーが 1 本しかないこと。** 2026-08 に日替わりシェフ
レストランの当番表 (`chef`) を商工会議所の店舗ページに登録したが、同じカレンダーを
店 (日替わりシェフのお店) 側にも登録したため、トップページに 2 本並んだ。ところが
city-tecoli の `calendar-boxes.ts:186` は

```js
const hasGear = metas.length >= 2;
```

としており、**カレンダーが 1 本の店には購読設定の ⚙ が出ない**。結果、どちらの
箱からも購読を切れない状態になった。商工会議所が 2 本目を持てば ⚙ が出る。

ただしこれは副次的な効果であって、本設計の目的ではない。目的は (b)。

**(b) 商工会議所の告知に配信価値があること。** 補助金、専門家相談の日程、
セミナー、地域の催し。市民にも事業者にも実用的で、いまは商工会議所のサイトを
直接見に行くしかない。

## 2. 取り込む範囲

### カテゴリ: 検定を除く 4 つ

| カテゴリ | 全件 | 2026-01-01 以降 |
|---|---|---|
| お知らせ (id=7) | 139 | 24 |
| セミナー (id=20) | 72 | 11 |
| 経営支援 (id=10) | 105 | 12 |
| 地域振興 (id=8) | 31 | 2 |
| **計** | **347** | **49** |
| ~~検定 (id=9)~~ | ~~110~~ | — |

**検定を外す。** 中身の大半が「第173回 日商簿記検定統一試験（1級）合格者番号
発表」のような発表通知で、掲載日に載せても「その日に何かが起きる」わけではない。
受験者は商工会議所のサイトを直接見る。全体の 1/4 を占めるので、入れると
カレンダーが発表通知で埋まる。

### 期間: 暦年 2026-01-01 以降 (49 件)

年度 (2026-04-01 以降) で切ると 33 件になるが、**地域振興が 0 件**になり
「はんのう元気市・西川材フェアー」等の市民向け記事が落ちる。暦年のほうが
カテゴリの偏りが少ない。

## 3. dtstart は掲載日 — その帰結

`dtstart` は記事の掲載日 (`date`)。開催日ではない。

**開催日は取得できない。** XO Event Calendar は開催日を postmeta に持つが、
REST API は `meta` を公開していない (`wp-json/wp/v2/xo_event` のレスポンスに
`meta` キーが存在しない)。`admin-ajax.php?action=xo_event_calendar_month` も
試したが、月グリッドの枠だけを返しイベントを含まない。

したがって取れるのは `date` / `title` / `content` / `link` / `xo_event_cat` のみ。
**RSS に切り替えても同じ** (§8)。`<pubDate>` は掲載日であって開催日ではなく、
postmeta の開催日は RSS にも現れない。開催日が欲しければ本文からの抽出 (LLM +
機械検算) が要る — 本設計の非目的 (§11)。

**帰結: 過去分はトップページに出ない。** アプリのトップは「今日以降」を見るので、
2026-01 に掲載された記事は取り込んでもトップには現れない。店舗ページと
カレンダー本体には残る。新規掲載分は掲載日 = ほぼ取得日なので新着として出る。

これを承知の上で暦年分を入れる。カレンダー本体としての厚みと、店舗ページでの
参照価値のため。

> 既存の `cal-shicho-blog-fetch` は `dtstart` を**取得日**にしてこの問題を
> 回避している (バックデート公開でも新着として出る)。本クローラで同じ手を
> 使わないのは、商工会議所の記事が「掲載日そのもの」に意味を持つため
> (「8/14 は夏季休業」等)。

## 4. カレンダー構成

| logical key | calendar ID |
|---|---|
| `cci` | `b0a56c8e1f5246cda41e2fdb3c449b20c50bb365aac92333a4a9290a21e7edcf@group.calendar.google.com` |
| `cci.en` | `b932613ee11b3b16657b986a7ec1bd82ad7c385c30de75a2db5834ba1a297e32@group.calendar.google.com` |

`source.type` は `hanno-cci-event`。routing は `SOURCE_TYPE_TO_CALENDAR` に
1 行追加。

**英訳する。** 当番表 (`chef`) を英訳しなかった理由は「**店名という固有名詞を訳しても
情報が増えない**」の一点。商工会議所の告知は補助金・相談窓口・セミナーの説明文で、
本文の中央値は 370 字ある。飯能で事業をする外国人にとって実用的な情報であり、訳す
価値がある。

> **訂正**: 起案時に「shop カレンダーは店舗ページに i18n が無いので英訳しても
> 読む場所が無い」と書いたが、これは誤り。`publicCalendars()` が除外するのは
> `kind: 'todo'` だけで (`storage/shops.ts:127-129`)、**言語による絞り込みは
> 存在しない**。登録すれば英語カレンダーもそのまま店舗ページに並ぶ。
> `default.en` / `gikai.en` が店舗ページに出ないのは、それらが街レベルの
> カレンダーで**そもそも店舗に登録されていない**ためであって、英語だからではない。

したがって `cci.en` にも 2 つの経路がある。店舗ページへの登録と、Google カレンダー
での直接購読。どちらで見せるかは運用判断で、本設計は両方を可能にしておく。

### カレンダーは作成済み (2026-08-20)

`tecolicom@gmail.com` 所有、一般公開 (`reader`/`default`)、SA
`myhanno-bot@city-tecoli.iam.gserviceaccount.com` に `writer` を委託。
SA からアクセスできることを確認済み。

作成は `gws` CLI で行った。`gws auth login` を `tecolicom@gmail.com` で通し、
`calendars.insert` → `acl.insert` × 2 を実行。所有者を揃えるため SA 認証では
作っていない (`calendars.insert` は「認証したユーザーが data owner になる」)。
以後カレンダーを増やすときも同じ手順で足りる。

**残る手作業**: 商工会議所の店舗ページへの登録 (公開カレンダーとして ICS URL を
登録)。これで商工会議所のカレンダーが 2 本になり §1(a) の ⚙ も出る。

## 5. 本文と要約

`content.rendered` を `strip_html` + `normalize_body` で整形する。

**長文は LLM で要約する。** `cal-oshirase-fetch` と同じ方式・同じ閾値 (400 字超)。
実データ 30 件の分布は中央値 370 字、400 字超が 13 件、最長 4,529 字
(「商工会議所 インフォメーション（夏号）のご案内」)。4,500 字をそのまま
カレンダーの予定欄に入れるのは現実的でない。

### 既知の罠: `content_hash` に `method` を含めない

`cal-oshirase-fetch` のコメントが正典:

> LLM 環境変化 (key 失効、httpx 抜け等) で hash が変動して flood しない

`content_hash` は **title + date + body のみ**から計算する。要約方式
(`summary_method`) は rendering の選択であって content の identity ではない。
含めると、CI で `ANTHROPIC_API_KEY` が落ちた日に全件が「変化あり」と判定されて
カレンダーが氾濫する (2026-05-26 に実際に起きた障害)。

## 6. 世代管理と「主な変更」

`cal-oshirase-fetch` と同じく、同じ記事が更新されたら**新 UID の別イベント**を
作り、`source.supersedes` で前世代を辿れるようにする。`description` 冒頭に
「前回掲載日」と LLM 生成の差分行を付ける。

### 前提の弱さを明記しておく

差分行は**前世代の要約 × 今回の本文**という非対称な比較で作られる。元記事の
本文を保存していないため、LLM は値の異同を確かめる材料を持たない。この構造が
原因で、2026-08-19 に本番で以下が生成された (`oshirase-7334-62e7b2`):

```
主な変更: 物件Aの最低売却価格が1,970万円から1,970万円に、入札保証金が295.5万円から
295.5万円に変更されました。…
```

4 対すべてが同値、つまり行全体が根拠のない生成だった。`DIFF_SYSTEM_PROMPT` は
これを明示的に禁じており `temperature=0` も入っていたが、守られなかった。

### 対策: `drop_unchanged_claims()` を `_lib` に移して共有する

2026-08-20 に `cal-oshirase-fetch` へ入れた生成後の機械検算を、**`_lib` へ移動
して両クローラで共有する**。片方にだけ置いてコピーすると、後日片方だけ直る
事故が起きる。

移動対象: `drop_unchanged_claims()` / `_CLAIM_RE` / `_claim_value_key()`。
`cal-oshirase-fetch` は `_lib` から import する形に変える。既存テスト
`tests/test_diff_verify.py` は `_lib` を読む形に書き換える。

### 観測事実: 商工会議所では更新運用が見られない

440 件を確認した限り、同じ記事が繰り返し更新される運用は観測されていない
(「7月・8月の専門家相談の日程」「8月・9月の専門家相談の日程」のように、
毎回新しい記事として立つ)。したがって世代管理は当面ほぼ発火しない。

**発火しないコードは検証もされない**という弱さは残る。将来商工会議所が運用を
変えて初めて動くとき、実績のない経路が動くことになる。機械検算を共有する
のはそのための保険でもある。

## 7. イベントの形

UID は `cci-event-<post-id>-<hash6>@hanno.city.tecoli.com`。`<hash6>` は
`content_hash` の先頭 6 文字で、`cal-shicho-blog-fetch` /
`cal-oshirase-fetch` の incremental mode と同じ規約。内容が変われば UID が
変わる = 別世代になる。

```yaml
uid: "cci-event-2778-a1b2c3@hanno.city.tecoli.com"
summary: "🎓 「年収の壁の見直しで注意すべき税制実務のポイント」の開催について"
location: "飯能商工会議所"
url: "https://www.hanno-cci.or.jp/xo_event/xo_event-2778/"
dtstart: "2026-08-11"
dtend: "2026-08-11"
description: |-
  <本文または LLM 要約>

  https://www.hanno-cci.or.jp/xo_event/xo_event-2778/
render:
  gcal:
    mode: single-allday
source:
  type: hanno-cci-event
  id: "2778"
  url: "https://www.hanno-cci.or.jp/xo_event/xo_event-2778/"
  category: "セミナー"
  summary_method: "llm-haiku-4-5" | "full"
  fetched_at: "..."
  content_hash: "sha256-..."
```

### カテゴリ別の絵文字 prefix

1 カレンダーに 4 系統が混ざるので、既存クローラの `📢`/`🎪`/`ℹ️`/`📝` と同じ
役割で識別子を付ける。

| カテゴリ | prefix |
|---|---|
| お知らせ | `ℹ️ ` |
| セミナー | `🎓 ` |
| 経営支援 | `💼 ` |
| 地域振興 | `🏮 ` |

## 8. 取得 — RSS を使う (REST は使えない)

### REST が使えない

起案時は `wp-json/wp/v2/xo_event` を使う設計だったが、**CI から実行できない**
ことが判明したので RSS に切り替える。

観測 (2026-08-20、ランナーは Azure eastus2 / 米国バージニア):

| 時刻 | HTML | REST |
|---|---|---|
| 15:56 | timeout | timeout |
| 16:43 | **200** | **403** |
| 16:52 | **200** | **403** |
| 17:01 | **000 (到達不能)** | **000 (到達不能)** |

同時刻に日本国内のローカル回線からは両方 200。

**同じ現象を別サイトで既に踏んでいた。** `WatchCrow/README.md` に記録がある:

> han-note.com は Xserver の REST API アクセス制限により海外 IP (GitHub
> Actions ランナー含む) からの wp-json が 403 になるため、`sitemap` 型に切替済み。

つまり原因は Xserver 系ホスティングの「国外 IP からの REST API 制限」。公開
ページは通し、`wp-login.php` / `xmlrpc.php` / `wp-json` だけ弾く設定。403 を
繰り返した結果、IP 全体が締め出されたと見られる (17:01 の到達不能)。

**遮断されると分かっている先を叩き続けない。** 巻き添えで
`cal-cci-chef-fetch` まで落ちる (実際 15:56 と 17:01 に落ちた)。

### sitemap は使えない

はんのーとの解決策 (`post-sitemap.xml`) はそのままは使えない。商工会議所の
sitemap は Google Sitemap Generator 製で、**`sitemap-pt-page-*` (固定ページ)
しか含まず、カスタム投稿タイプ `xo_event` が載っていない**。

### RSS を使う

カテゴリ別フィードを回す。

```
https://www.hanno-cci.or.jp/xo_event_cat/<slug>/feed/[?paged=N]
```

| カテゴリ | slug | term id |
|---|---|---|
| 地域振興 | `promotion` | 8 |
| セミナー | `seminar` | 20 |
| 経営支援 | `manage` | 10 |
| お知らせ | `news` | 7 |
| ~~検定~~ | ~~`exam`~~ | ~~9~~ (除外) |

1 フィード 10 件。`?paged=N` でページングでき、`pubDate` が `after` より古く
なったら打ち切る。**実測 9 リクエストで 49 件**。

RSS の各 `<item>` から必要なものが全部取れる。

| 用途 | RSS | (REST での対応物) |
|---|---|---|
| タイトル | `<title>` | `title.rendered` |
| 本文全文 | **`<content:encoded>`** | `content.rendered` |
| 掲載日 | `<pubDate>` | `date` |
| 記事 ID | `<guid>` の `p=NNNN` | `id` |
| カテゴリ | **フィードの slug** | `xo_event_cat` |

**取得結果は REST と完全に一致する** (2026-08-20 実測: 記事 ID で名寄せして
49 件、差分ゼロ)。

### 注意: 記事 ID で重複排除する

**複数カテゴリを持つ記事がある。** カテゴリ別フィードを回すと同じ記事が複数回
現れるので、記事 ID で名寄せしなければ二重に数える (実測: 名寄せ前 60、
名寄せ後 49)。

カテゴリは `CATEGORIES` の定義順で最初に一致したものを採る (§7 と同じ規則)。

### 失うもの

- **`after=` によるサーバ側の絞り込み** — 取得後に `pubDate` でコードが捨てる
- **`modified_gmt`** — RSS に無い。ただし元々使っていない (§8 起案時の
  「2 段の判定」は、REST 一覧が本文まで返すので記事ごとの再取得が発生せず、
  実際に必要なのは `content_hash` 側だけだった)

## 9. テスト

### golden (ネットワーク非依存、CI 実行)

`run-golden` の `CRAWLERS` に追加。`cal-oshirase-fetch` と同じく
`_llm_available()` を `False` に固定して LLM 経路を断ち、決定論化する。

| シナリオ | seed | 見るもの |
|---|---|---|
| `cal-cci-event-fetch` | 無し | 初回取込。カテゴリ別 prefix、本文整形 |
| `cal-cci-event-update` | 既存 YAML | 更新検知 (新 UID + `supersedes`) |

fixture は REST のレスポンス JSON。

### ユニット

- `test_diff_verify.py` を `_lib` 参照に書き換え (§6 の移動に伴う)
- カテゴリ → prefix の対応
- `content_hash` に `summary_method` が影響しないこと (§5 の罠の回帰テスト)

## 10. CI

**RSS 版が CI から動くかは未確認。** REST の 403 を繰り返した結果いま CI の IP
が締め出されている可能性が高く (§8)、この状態で試しても RSS の可否を判定でき
ないうえ、締め出しを長引かせる。**実装を先に済ませ、CI 投入は日を改めて判断する。**

RSS が CI から通らない可能性は実在する。`WatchCrow/README.md` の `sitemap` 型の
説明が「REST API や **RSS** が使えないサイト向け」となっており、RSS も遮断され
うることを示している。

CI に載せる場合の設定:

```yaml
- name: Crawl hanno-cci-event
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  run: ./calendar/bin/cal-cci-event-fetch --out-dir calendar/events --min-items 1 || echo "hanno-cci-event" >> "$RUNNER_TEMP/crawl-failures.txt"
```

`--min-items` は **1 以上にする**。起案時に 0 にしていたが、これは「0 件取得でも
成功扱い」を意味し、**サイトから 1 件も取れない異常が CI を緑のまま通す**。実際
2026-08-20 の REST 遮断はこれで見逃された。0 件は正常な運用では起こらないので、
1 なら誤検知しない。

`ANTHROPIC_API_KEY` は必須 (要約の有無で見え方が変わる)。集合同期型ではないので
`prune` は不要。

CI に載せられない場合は、日本の回線から手動で流す運用になる。

## 11. 非目的

- **開催日の抽出** — REST から取れない。本文から LLM で抽出してコード側で検算する
  (`cal-tourism-news-fetch` と同じ枠組み) ことは可能だが、本設計には含めない
- **検定カテゴリ** — §2 参照
- **2025 年以前の記事** — §2 参照
- **`chef` と `cci` の重複表示の解消** — city-tecoli 側の課題 (`hasGear` の
  前提が「同一カレンダーが複数エンティティに登録されうる」ことを想定していない)。
  本設計は 2 本目を作ることで症状を回避するが、根本解決ではない
