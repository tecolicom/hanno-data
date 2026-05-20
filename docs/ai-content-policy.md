# AI 生成コンテンツの取扱い方針

このリポジトリでは LLM (Claude Haiku 4.5) を 2 用途で使用している:

1. **お知らせ記事の要約** (`calendar/bin/cal-oshirase-fetch`) — 長文の市公式
   お知らせを 200〜400 字に圧縮、日時/場所/対象等の事実を保持
2. **全 event の英訳** (`calendar/bin/cal-translate-en`) — 元の summary/description
   を英語化、`translations.en.*` に in-place 格納

本書はこの 2 用途の表示方針と背景の調査結果を記録するもの。

## 結論 (運用ルール)

### 日本語要約 (summarization)

LLM が要約に関わった description には、**冒頭** に以下の固定文言を入れる:

```
AI による要約 (正確な情報は元記事をご確認ください)
```

技術的な追跡は YAML の `source.summary_method` フィールドで行う:

| method | description の出所 | AI ラベル |
|---|---|---|
| `url-only` | URL のみ (本文取得失敗) | なし |
| `full` | 元記事の本文をそのまま転載 | なし (引用扱い) |
| `llm-haiku-4-5` | Claude Haiku 4.5 による要約 | **あり** |

### 英訳 (translation)

`translations.en.description` の **冒頭** に以下の固定文言を入れる:

```
Automated translation (refer to source for accuracy)
```

末尾に元 (日本語) の URL を `Source (Japanese): <URL>` として保持。
技術的な追跡は YAML の `translations.en.model` + `translation_hash` で行う。

### 共通方針

- 絵文字なし
- モデル名は user-facing 文言には入れない (将来モデルを差し替えた時に陳腐化するため)
- 個別記事の機密性ではなく **生成物の信頼性をユーザに正しく期待させる** ことが目的
- 元 URL は必ず併記 (出典明示)

## 調査結果サマリ (2026-05-19 時点)

### 法的義務

日本において、AI 生成コンテンツの表示を強制する **法的義務はない** (2026年5月時点)。
AI事業者ガイドライン (総務省・経産省) は「ソフトロー」と明記され、義務ではなく
推奨。EU AI Act は域外適用の可能性はあるが、citi.tecoli.com が EU 内ユーザーを
主対象としない限り直接適用はされない。

### 業界推奨 (ソフトロー)

- **AI 事業者ガイドライン (第1.1版, 2025年3月)**:
  > 技術的に可能な場合は、電子透かしやその他の技術等、AI 利用者及び業務外利用者
  > 等が、AI が生成したコンテンツを識別できるよう対応
- **デジタル庁「行政の進化と革新のための生成 AI の調達・利活用に係るガイドライン」
  (DS-920, 2025年5月)**: 生成 AI によるアウトプットであることの表示等を求める
  (ただし行政機関側の指針、第三者再配信者に直接適用されない)
- **G7 広島 AI プロセス国際指針 (2023)**: ユーザーが AI 生成コンテンツを識別できる
  ようにすることを明記

### 民間実例

- **Yahoo!ニュース「AI まとめ」**: 記事見出し脇に「AI まとめ」ラベル付与 +
  「生成 AI により出力される結果について、信頼性、正確性、完全性、有効性等は
  保証していない」と注意書きを併記。**冒頭配置**。

本リポジトリの方針も Yahoo 方式に近い (冒頭・短文・免責付き)。

### 著作権 (再配信の根拠)

飯能市公式サイトには「無断で複製・転用することはできません」と明示されている。
本サービスの運用根拠は **著作権法 32 条「引用」** (出典明記・主従関係) の要件を
満たす形での運用とする。具体的には:

- description は要約 (LLM) または部分引用 (full) のいずれの場合も、
  **元 URL を必ず併記** (出典明示)
- カレンダー内のメインコンテンツは引用元の事実情報であり、本サービスの
  独自付加部分が主、引用が従、という関係は確保されないため、
  **「引用」というより「リンク+部分要約」という現実的な再配信** という整理。
  事業者側に苦情が来た場合は柔軟に削除・修正で対応する運用前提。

なお飯能市役所 (出典) には別途 city-tecoli 全体のコミュニケーションを通じて
本サービスの存在と方針を伝える方向。

## 出典

- [AI 事業者ガイドライン (第1.1版, 総務省)](https://www.soumu.go.jp/main_content/001002576.pdf)
- [デジタル庁 DS-920 生成AI調達・利活用ガイドライン](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/e2a06143-ed29-4f1d-9c31-0f06fca67afc/80419aea/20250527_resources_standard_guidelines_guideline_01.pdf)
- [広島AIプロセス (総務省)](https://www.soumu.go.jp/hiroshimaaiprocess/)
- [著作権法 (e-Gov)](https://laws.e-gov.go.jp/law/345AC0000000048)
- [飯能市ホームページ利用規約](https://www.city.hanno.lg.jp/soshikikarasagasu/kikakusomubu/kohojohoka/1444.html)
- [Yahoo!ニュース 生成AIによる記事要約機能](https://news.yahoo.co.jp/newshack/information/topicsaimatome_20250930.html)
