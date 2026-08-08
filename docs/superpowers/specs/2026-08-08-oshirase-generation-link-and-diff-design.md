# お知らせ記事の世代リンクと差分要約

作成日: 2026-08-08

## 背景 / 問題

`cal-oshirase-fetch` の incremental モードは、同じ市サイトのページ (`page_id`) の本文が
書き換わるたびに **別の YAML を新規作成**する。UID は `oshirase-<page_id>-<hash6>@…`、
既存 YAML は削除せず残る。

例: 「市有地の売却（一般競争入札）について」(`page_id` = 7334)

| | 5 月版 | 8 月版 |
|---|---|---|
| ファイル | `events/2026/05-01_oshirase-7334.yaml` | `events/2026/08-08_oshirase-7334-497925.yaml` |
| uid | `oshirase-7334@…` | `oshirase-7334-497925@…` |
| content_hash | `sha256-20afe127ea8e65a5` | `sha256-497925995081bafc` |

現状の不都合:

1. **git のログでは繋がらない** — 別ファイルの追加なので `git log --follow` が辿れない。
   同一記事であることは `source.id` / `source.url` の一致でしか分からず、
   YAML 自身は前世代を指していない。
2. **利用者が更新前の内容にたどり着けない** — `description` 冒頭に
   `🔄 内容更新 (公開日: …)` とは出るが、「何が変わったか」も「前回いつ出たか」も分からない。

### 制約 (調査で判明した事実)

- アプリ (city.tecoli.com) は hanno-data の YAML を直接読まず、**Google Calendar の公開 ICS**
  を取得してパースする (`src/pages/api/cal-events.json.ts`)。
- 表示は `filterUpcoming` で **前日 〜 90 日先**の窓 (`src/lib/shop-events.ts:215`)。
- `/cal/[id]/` はカレンダー単位のページで、**個別イベントのページは存在しない**
  (= 過去イベントに張れる URL が無い)。

したがって利用者向けに見せる手段は、**新しいイベントの `description` 内にテキストで書く**
ことに限られる (city-tecoli 側を改修しない限り)。

### 差分の材料

元記事の本文 (`body`) はリポジトリに保存していない (`content_hash` のみ)。
一方、**旧 YAML の `description` (= 前回の LLM 要約) は残っている**ので、
これを新本文と突き合わせれば body を保存せずに差分が作れる。

トレードオフ: 旧要約は情報が落ちているため、「元記事にはあったが旧要約に載らなかった項目」が
新規追加と誤検出されうる。prompt でこれを抑制する (後述)。

## 設計

### 1. YAML の世代リンク

更新イベント (同 `page_id` の既存 YAML がある場合) にのみ `source.supersedes` を追加する。

```yaml
source:
  type: city-hanno-oshirase
  id: "7334"
  url: "https://www.city.hanno.lg.jp/soshikikarasagasu/sogoseisakubu/shisankeieika/7334.html"
  fetched_at: "2026-08-07T18:47:29.141815Z"
  content_hash: "sha256-497925995081bafc"
  summary_method: "llm-haiku-4-5"
  publish_date: "2026-08-07"
  supersedes: "oshirase-7334@hanno.city.tecoli.com"
```

- **直前 1 世代のみ**を持つ。チェーンを辿れば全世代に到達する
  (`page_id` 13388 は現状 6 世代)。
- 新規掲載 (`🆕`) の YAML には付けない。
- `content_hash` の材料には**含めない**。既存 YAML の hash を動かさない
  (= カレンダー氾濫を起こさない) ため。既存の
  「`content_hash` は (title, date, body) のみ」という契約を維持する。

### 2. 前世代の特定

`cal-oshirase-fetch:_existing_content_hashes()` を `_existing_generations()` に置き換える。

- 返り値: `dict[page_id, list[(dtstart, uid, path)]]`。各 list は `dtstart` 降順、
  同日は path 名の降順で安定ソート。
- 先頭要素が直前世代。
- 既存の `(page_id, content_hash)` skip 判定と `existing_page_ids` は、この索引から導出する
  (content_hash も索引に持たせる)。

### 3. 旧要約の取り出し

`_lib` に 2 つ追加する。

- `read_yaml_block(path, key) -> str | None`
  block scalar (`key: |-` 形式) の中身をインデント除去して返す。既存の
  `read_yaml_scalar()` は 1 行スカラ専用で `description` を読めないため。
- `strip_description_wrapper(text) -> tuple[str, str | None]`
  `description` から以下を剥がし、`(要約本体, 元記事URL)` を返す:
  - 冒頭の status 行 (`🆕` / `🔄` / `📝` で始まる行とその直後の空行)
  - `AI_DISCLAIMER_JP` (`AI による要約 (正確な情報は元記事をご確認ください)`) の行
  - 末尾の `飯能市公式サイト 新着情報: <URL>` 行

`cal-translate-en` の `_strip_wrapper()` 相当処理をこの共通関数に寄せ、重複実装を消す。

### 4. 差分要約の生成

`cal-oshirase-fetch` に追加:

```python
def diff_with_llm(title: str, prev_summary: str, new_body: str) -> str | None
```

- モデルは要約と同じ Claude Haiku 4.5 (`summarize_with_llm` と同じ呼び出し基盤)。
- 返り値は「主な変更:」に続く本文 (prefix は呼び出し側で付ける)、または `None`。

prompt 方針:

- 出力は 1〜2 文、**120 字以内**。
- 入力の旧テキストは**要約であって全文ではない**。
  **言い回しの違い・詳しさの違いを変更として報告しない。**
  旧要約に無い項目を「新設」「追加」と断定しない。
- 日付・金額・件数・申込方法・手続きの変更を優先して拾う。
- 実質的な変更が見当たらなければ**空文字**を返す。
- Markdown 記法は使わない (出力先が plain text の Google Calendar のため)。
  既存の `strip_markdown()` を post-process に通す。

呼ばない / 省略する条件:

- `_llm_available()` が False (CI の golden テスト環境) — 呼ばない。
- 前世代が存在しない (新規掲載) — 呼ばない。
- 前世代の `summary_method` が `url-only` (本文が無く要約が URL だけ) — 呼ばない。
- LLM が失敗、または空を返した — 差分行を省く。

### 5. status_header の組み立て

更新イベントの `description` 冒頭:

```
🔄 内容更新 (公開日: 2026-08-07 / 前回掲載: 2026-05-01)
主な変更: 物件 A・B・C の個別入札を新設。入札日を 6/19 から 9/11 に再設定。

AI による要約 (正確な情報は元記事をご確認ください)

市有地の一般競争入札を実施します。
…

飯能市公式サイト 新着情報: https://…
```

- 「前回掲載: YYYY-MM-DD」は前世代の `dtstart`。
- 差分行が得られなかった場合は 1 行目だけになる。
- 新規掲載 (`🆕 新着掲載 (公開日: …)`) の書式は変更しない。
- `status_header` は従来どおり `content_hash` に含めない
  (`_materialize_description` の既存契約)。

### 6. 英訳 (既存不具合の修正を含む)

`cal-translate-en` は `description` 全体を訳すので、差分行は自動的に英語になる。
`translation_hash` は (元 summary, 元 description, format_version, lang) ベースなので、
差分行が付いた YAML は再翻訳対象になる。

**既存不具合**: `AI による要約` 行を剥がす正規表現が `^` 固定 (`cal-translate-en:143`) のため、
status 行がある YAML では剥がれず、英訳側で disclaimer が二重化している。
現に `08-08_oshirase-7334-497925.yaml` の `translations.en.description` は:

```
Automated translation (refer to source for accuracy)

🔄 Content updated (published: August 7, 2026)

AI summary (please check the original article for accurate information)   ← 二重
```

差分行を足すとこれが常態化するため、`strip_description_wrapper()` への統合と合わせて
「先頭数行の中から該当行を除去」に直す。

**`TRANSLATION_FORMAT_VERSION` は bump しない。** bump すると全 YAML (150 件超) が
再翻訳対象になりコストが大きい割に、直るのは disclaimer の重複という軽微な表示だけ。
修正は以後 `description` が変わって再翻訳される YAML から順に効く。
遡及対象の 2 件は `description` が変わるので `translation_hash` も変わり、その場で直る。
既存の翻訳済み YAML に残る重複 disclaimer はそのまま放置する。

### 7. 遡及適用

`cal-oshirase-fetch --backfill-diff [--since YYYY-MM-DD]` を追加する。

- 対象: `events/` 内で `description` が `🔄 内容更新` で始まり、`dtstart >= since` の YAML。
- `--since` 既定値は**前日** (`today_jst - 1 day`) = アプリ可視窓の下限。
- 各対象について: 記事を再 fetch → 直前世代の要約と比較して差分行を生成 →
  `description` の status 行を差し替え、`source.supersedes` を追加。
- `content_hash` / `uid` / `dtstart` は変更しない。ファイル名も変わらない。
- `--dry-run` 対応。

**今日 (2026-08-08) 時点の対象は 2 件**:
`08-07_oshirase-14121-ec86a7.yaml` と `08-08_oshirase-7334-497925.yaml`。
アプリの表示窓が「前日〜90 日先」で、お知らせイベントの `dtstart` は取得日のため、
掲載翌日には窓から外れる。1 回だけ手で走らせる想定で、効果の本体はこれからの更新分。

`cal-daily.yml` には組み込まない (日次で走らせる必要のない一回性の操作)。

### 8. 反映経路の確認

`cal-myhanno apply` は `COMPARE_FIELDS` + `normalize_for_diff` で既存イベントと比較し、
差分があれば `events.update` を呼ぶ (`cal-myhanno:702`)。`COMPARE_FIELDS` に
`description` が含まれる (`cal-myhanno:762`) ため、`description` が変われば
drift として検出され Calendar に反映される。追加の変更は不要。

## テスト

- **既存 golden はバイト一致のまま維持**される。`calendar/tests/` は `_llm_available()` を
  False 固定にしているので差分行は生成されない。
- 新規 golden を 1 件追加: 同一 `page_id` の既存 YAML がある状態で fetch し、
  `source.supersedes` が付き `🔄 内容更新 (公開日: … / 前回掲載: …)` の書式になることを
  バイト一致で固定する (LLM 非依存なので差分行なしの形)。
- `strip_description_wrapper()` の単体テスト: status 行あり / なし、disclaimer あり / なし、
  末尾 URL あり / なしの組み合わせ。
- `_existing_generations()` の単体テスト: 複数世代の `dtstart` 降順ソート、同日タイブレーク。

## やらないこと (YAGNI)

- **記事本文 (`body`) の保存** — 旧要約で足りる方針。リポジトリに本文テキストを蓄積しない。
- **世代一覧ページ / 一覧 CLI** — `grep 'id: "7334"' calendar/events/` と
  `supersedes` チェーンで足りる。
- **city-tecoli 側の改修** (個別イベントページ、過去イベント表示) — 本設計の範囲外。
- **`shicho-blog` への適用** — 同 page の更新検知の実績がまだ無い。
  ロジックは `_lib` に置くので後から入れられる。
- **元記事本文レベルの正確な diff** — 旧要約ベースである以上、近似にとどまる。
