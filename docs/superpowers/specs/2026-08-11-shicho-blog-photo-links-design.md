# 市長ブログの写真をリンクとして開けるようにする 設計

作成日: 2026-08-11

## 背景

市長ブログ「市政一直線」の記事には写真が入っていることが多いが、
`cal-shicho-blog-fetch` は本文抽出時に `<figure>` / `<img>` を明示的に捨てている
(`extract_body`)。結果、カレンダー側では写真の存在すら分からない。

写真を見せる経路を作る。

### 実データ調査 (2026-08-11 時点)

直近 8 記事を実測:

| 項目 | 実測値 |
|---|---|
| 本文中の写真枚数 | 8 件中 7 件が 1 枚、1 件が 0 枚 |
| マークアップ | `<figure class="img-item"><img alt="..." src="//www.city.hanno.lg.jp/material/images/group/79/....jpg">` |
| src の形式 | プロトコル相対 (`//www.city.hanno.lg.jp/...`) |
| alt | 記事タイトルとほぼ同一 (冗長) |

写真は `free-layout-area` 内の `<figure>` にしか現れない。ヘッダ/フッタの装飾画像は
この範囲外なので、本文抽出と同じ範囲を対象にすれば混入しない。

### 表示側の事実

- app (`city-tecoli/src/lib/client/hanno/event-modal.ts:44`) は description 内の
  `https?://...` を HTML escape 後に `<a>` へ置換する。
- Google Calendar も description 内の URL を自動リンク化する。

**したがって description に画像 URL を平文で 1 行足すだけで、両方でクリックして開ける。**
app 側 (別リポジトリ) の改修は不要。

## 決定

### 1. 抽出範囲と正規化

`extract_images(html)` を追加する。`extract_body` と同じ
`<div class="free-layout-area">` 〜 `<div class="toiawase">` の範囲から
`<figure>` 内の `<img src>` を順に集める。

- プロトコル相対 URL に `https:` を補完する
- 既存の `safe_url` と同じ host allowlist (`URL_HOST_ALLOWLIST`) で絞る
  (path prefix は記事 path 用なので画像には適用しない)
- 上限 5 枚。超過分は捨てる
- `alt` は使わない (記事タイトルと重複するため)

`extract_body` の `<figure>` 除去は現状のまま残す (本文テキストに写真は不要)。

### 2. description の組み立て

本文と末尾の「市長ブログ「市政一直線」: <url>」行の**間**に挿入する。

- 1 枚: `写真: <url>`
- 複数枚: `写真1: <url>` / `写真2: <url>` … を各行に

```
📝 市長ブログ更新 (公開日: 2026-07-28)

7月28日（火曜日）、本市は日本コカ・コーラ株式会社…

写真: https://www.city.hanno.lg.jp/material/images/group/79/0807….jpg

市長ブログ「市政一直線」: https://www.city.hanno.lg.jp/…/14127.html
```

### 3. `content_hash` には画像 URL を含めない

含めると、既存記事に写真行を足した時点で hash が変わり、incremental mode が
「🔄 内容更新」として**別 uid の重複エントリを生成**してしまう。含めなければ
既存 YAML を uid 据え置きで上書きでき、カレンダー側も重複しない。

代償は「本文そのままで写真だけ差し替え」を検知できないことだが、実害は無い。
写真を差し替える運用では **URL を変えずにファイル実体を置き換える**のが普通で、
URL を hash に含めたところでどのみち検知できない。

### 4. 英訳側での URL 保護

`split_description` (`calendar/bin/_lib.py:391`) は**末尾 1 行の「ラベル: URL」しか
剥がさない**。このままだと写真 URL が LLM に渡り、翻訳中に URL が改変・脱落しうる。

末尾側の連続する「ラベル: URL」行**群**を剥がすよう拡張し、英語側では
`Photo: <url>` として機械的に復元する (LLM は URL に一切触れない)。

- 既存の source URL 行 (`Source (Japanese): <url>`) の扱いは変えない
- 写真行は `Source (Japanese):` の**上**に置く (JP 側と同じ並び)

### 5. 適用範囲

**新規記事のみ**を基本とする。既存 YAML は 304 (conditional GET) で再 parse されない
ので、放置すれば差分も再翻訳コストも発生しない。

ただし動作確認として、**直近 5 件**の既存記事には実際に反映する。決定 3 により
uid・ファイル名・`content_hash` は不変で、description だけが変わる。この 5 件は
英訳も入れ直す。

## 影響範囲

| ファイル | 変更 |
|---|---|
| `calendar/bin/cal-shicho-blog-fetch` | `extract_images` 追加、`build_description` / `build_yaml_doc` に写真行 |
| `calendar/bin/_lib.py` | `split_description` を「末尾の URL 行群」対応に拡張 |
| `calendar/bin/cal-translate-en` | 写真行を `Photo:` として復元 |
| `calendar/tests/` | 上記のユニットテスト (ネットワーク非依存) |

`cal-oshirase-fetch` など他クローラも `split_description` を共有するが、現状それらの
description には末尾 URL 行が 1 本しか無いので、拡張後も挙動は変わらない
(回帰テストで確認する)。

## やらないこと

- app 側での画像サムネイル表示 (別リポジトリの改修が必要。今回は URL リンクで足りる)
- 過去記事 100 件強の全件 backfill (再クロール + 全件再翻訳のコストに見合わない)
- 画像の再ホスト / キャッシュ (市のサーバから直リンクする)
