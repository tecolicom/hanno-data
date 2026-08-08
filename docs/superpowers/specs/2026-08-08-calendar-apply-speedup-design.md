# apply-all の高速化と events.list ページング対応

作成日: 2026-08-08

## 背景 / 問題

日次 CI (`cal-daily.yml`) の所要時間の約半分が Calendar への apply に費やされている。

前回 run (2026-08-07、合計 6分25秒) のステップ別実測:

| ステップ | 所要 |
|---|---|
| Apply events to Calendar (JP) | **89s** |
| Apply EN events to Calendar | **101s** |
| Crawl shicho-blog | 48s |
| Crawl hanno-tourism | 42s |
| Crawl oshirase | 40s |
| Translate to English | 31s |
| Install Python + PDF deps | 16s |
| その他 (snapshot / commit / 通知) | 各 1〜3s |

本日 run (2026-08-08) でも JP 63s + EN 72s = 135s。

### 原因 1: イベント 1 件ごとに API 照会している

`cmd_apply` は反映要否の判定に `find_event_by_uid()` を使い、YAML 1 件につき
`events.list` を 1 回呼ぶ (`cal-myhanno:683`)。437 件 × JP/EN の 2 言語で
**約 874 回**の API 往復になる。実際に変更されるのは通常 0〜数件で、残りが
`in-sync` と判定されるまでに同じ照会が要る。

### 原因 2: 1 回ごとに外部プロセスを起動している

`gws()` は `subprocess.run(["gws", ...])` で CLI を叩く (`cal-myhanno:142-149`)。
ネットワーク往復に加えて 874 回分のプロセス起動コストが乗る。

### 併発する潜在バグ: ページング未処理

`events.list` を呼ぶ 4 箇所すべてが `maxResults: 500` 固定で `nextPageToken` を
一切見ていない (`cal-myhanno:521, 810, 978, 1024`)。

現在のイベント数はカレンダー別に最大 247 件 (`gikai`) だが、お知らせクローラが
毎日イベントを増やすため、いずれ 500 を超えて snapshot / diff / wipe が静かに
切り捨てを起こす。

**これは高速化の前提条件でもある。** 一括取得したリストが切り捨てられると、
存在するイベントが索引に載らず「無い」と判定されて再 import される。
per-event 照会をやめる以上、ページングは先に直す必要がある。

## 設計

### 1. `list_all_events()` — ページング対応の共通取得

```python
def list_all_events(calendar_id: str) -> list[dict]:
    """指定カレンダーの全イベントを nextPageToken を辿って取得する。

    既存の 4 箇所は maxResults: 500 固定でページングを見ておらず、
    501 件目以降を静かに取りこぼしていた。
    """
```

- `maxResults` は Google Calendar API の上限である 2500 を使う
  (公式ドキュメントで確認: 既定 250、上限 2500)。現在の最大カレンダーは 247 件なので
  当面は 1 ページで収まり、API 往復は 1 回。
- `nextPageToken` が返る限り `pageToken` を付けて再取得し、`items` を連結する。
- 固定パラメータは `singleEvents: False`, `showDeleted: False`
  (既存 4 箇所と同一。4 箇所は `calendarId` だけが違うので追加引数は不要)。

**`gws --page-all` は使わない。** `gws` には自動ページング機能があるが:

- 出力が NDJSON (1 ページ 1 行) になり、`json.loads(stdout)` 前提の既存 `gws()`
  ヘルパでは扱えず、別系統のパーサが要る
- `--page-limit` の既定が 10 で、**到達時に静かに切り捨てる** — 今直そうとしている
  バグと同じ形の依存を増やすことになる
- NDJSON の正確な形と page-limit 到達時の挙動は未検証

手動ループなら依存するのは「`gws` が API のレスポンス本文をそのまま JSON で返す」
という 1 点だけで、これは既存コードが `res.get("items")` で動いている事実から確認済み。
同じ本文にある `nextPageToken` も取れる。

置き換える呼び出し元:

| 位置 | 関数 |
|---|---|
| `cal-myhanno:518` | `cmd_fetch` |
| `cal-myhanno:809` | `cmd_diff` |
| `cal-myhanno:975` | `cmd_snapshot` |
| `cal-myhanno:1021` | `cmd_wipe` |

いずれも `res = gws(...)` → `items = res.get("items", [])` の 2 行を
`items = list_all_events(cal_id_val)` の 1 行に差し替えるだけ。

### 2. `EventIndex` — カレンダー別 uid → event 索引

```python
class EventIndex:
    """calendar_id ごとに全イベントを 1 回だけ取得し、iCalUID で引ける索引。

    apply-all が 1 件ずつ events.list を呼ぶのを避けるための読み取りキャッシュ。
    カレンダー単位の遅延取得で、触らないカレンダーは fetch しない。
    """

    def get(self, calendar_id: str, uid: str) -> dict | None
```

- 初回に該当 `calendar_id` を見たときだけ `list_all_events()` を呼び、
  `{iCalUID: event}` の dict を作って保持する。
- `iCalUID` を持たないイベントは索引に入れない (既存 `cmd_diff` と同じ扱い)。
- `lang=default` の `apply-all` は `default` と `gikai` に振り分くので
  **一括取得は 2 回**。874 回 → 2 回になる。

書き込み後に索引を更新しない。1 回の `apply-all` で同じ uid は 1 度しか
処理されず、言語ごとに別プロセスで走るため、更新の必要がない。

### 3. `cmd_apply` は索引を任意で受け取る

`cmd_apply` は `getattr(args, "index", None)` を見る:

- 索引があれば `index.get(target_cal_id, uid)` で引く
- 無ければ従来どおり `find_event_by_uid(uid, target_cal_id)`

`cmd_apply_all` が `EventIndex` を 1 個作り、各 `cmd_apply` 呼び出しの
`argparse.Namespace` に `index=` として渡す。単体の `apply <file>` は
1 件だけなので現状の挙動を維持する。

### 4. 書き込み直前の再確認

索引は実行開始時のスナップショットなので、apply 中 (約 60 秒) に人が Calendar を
手編集すると見落とす窓ができる。現行の per-event 照会にはこの窓がほぼ無いため、
安全性を落とさないよう書き込み経路にだけ再確認を入れる。

**update 経路** — 索引引きの結果 `COMPARE_FIELDS` に差分があると判定したら、
`events.update` を呼ぶ直前に `find_event_by_uid()` でその 1 件だけ取り直す:

- 取り直した結果が in-sync なら書かずに `{"action": "in-sync"}` を返す
- そうでなければ**取り直した方**に `new_body` をマージして update する
  (索引の古い値をマージ元にしない。`READ_ONLY_FIELDS` の除外は現行どおり)
- 取り直して None (= 消えていた) なら import 経路に落とす

**import 経路** — 索引に無い場合も `events.import` の直前に
`find_event_by_uid()` で 1 件確認し、見つかれば update 経路に回す。

書き込みは通常 1 日 0〜数件なので、追加の API 往復はほぼゼロ。

**`--dry-run` では再確認しない。** 書かないので不要で、計測結果もぶれない。

### 5. テスト

`cal-myhanno` には現在テストが 1 本も無い。`calendar/tests/test_calendar_index.py`
を新設し、`gws` を差し替えてネットワーク非依存で回す。

`list_all_events`:
- `nextPageToken` を辿って全ページを連結する
- 1 ページで終わる (token 無し)
- 空リスト
- **501 件以上を切り捨てない** (現行バグの回帰テスト)

`EventIndex`:
- 同一 `calendar_id` への 2 回目以降は API を呼ばない (呼び出し回数を数える)
- 別 `calendar_id` は別途 1 回だけ呼ぶ
- 未知 uid は `None`
- `iCalUID` の無いイベントは索引に入らない

再確認の効き目 (索引構築後に Calendar 側が変わったことにするフェイクを使う):
- 索引では差分ありだが再取得すると in-sync → **書かない**
- 再取得しても差分あり → **取り直した方**をマージ元にして update する
- 索引にあったが再取得すると消えている → import に落ちる

### 6. 計測

実装前後で `apply-all --dry-run` を実測して比較し、結果を記録する。
API 往復が 874 → 2 になるので apply は数秒台に落ちる見込みだが、数字は実測で確認する。

**前提: ローカルの `gws` 認証が切れている** (2026-08-08 時点、`invalid_grant:
reauth related error (invalid_rapt)`)。CI はサービスアカウントを使うので影響しないが、
ローカルでの実測と実 API に対する検証には再認証が要る。実測の前に再認証しておくこと。
再認証ができない場合、実測は CI の run ログ (ステップ別所要時間) で代替する。

## やらないこと (YAGNI)

- **`gws` CLI の Python 直叩き置き換え** — 書き込みは 1 日数件なので
  プロセス起動コストの削減効果がなく、変更規模に見合わない。
- **クローラ側の高速化** (`Crawl` 各ステップ計 130 秒) — 相手が市の公式サイトで、
  逐次・低速に取る設計は意図的。
- **書き込み後の索引更新** — 1 run で同じ uid は 1 度しか処理されない。
- **`cmd_apply` 単体経路の変更** — 1 件だけなので現行の per-event 照会で十分。
