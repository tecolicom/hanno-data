#!/usr/bin/env python3
"""cal-tourism-news-fetch の機械検証 5 項目のユニットテスト。
実データで確認した失敗モードを回帰ケースとして持つ。
実行: python3 calendar/tests/test_news_verify.py
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "cal-tourism-news-fetch")
loader = importlib.machinery.SourceFileLoader("cal_tourism_news_fetch", SCRIPT)
spec = importlib.util.spec_from_loader("cal_tourism_news_fetch", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def _ex(event_date, date_evidence, status="normal", end=None):
    return {"summary": "s", "event_date": event_date, "event_end_date": end,
            "date_evidence": date_evidence, "status": status}


def test_accepts_valid_case():
    """実データ: はんのう昭和盆踊り。2026-08-08 は土曜。"""
    body = "8月8日(土) はんのう昭和盆踊りへ♪ 日時:2026年8月8日(土) 午後6時〜"
    got = mod.verify_event_date(_ex("2026-08-08", "日時:2026年8月8日(土)"),
                                body, date(2026, 8, 7))
    assert got is None, got


def test_rejects_hallucinated_evidence():
    """検証 1: date_evidence が本文に無い。"""
    body = "夏祭りを開催します。"
    got = mod.verify_event_date(_ex("2026-08-08", "日時:2026年8月8日(土)"),
                                body, date(2026, 8, 7))
    assert got is not None and "evidence" in got, got


def test_rejects_evidence_not_matching_date():
    """検証 2: 根拠と結論の月日が食い違う。"""
    body = "日時:2026年8月8日(土) 午後6時〜"
    got = mod.verify_event_date(_ex("2026-09-15", "日時:2026年8月8日(土)"),
                                body, date(2026, 8, 7))
    assert got is not None and "mismatch" in got, got


def test_rejects_weekday_mismatch():
    """検証 3: 2025-08-08 は金曜なので (土) と食い違う。"""
    body = "日時:8月8日(土) 午後6時〜"
    got = mod.verify_event_date(_ex("2025-08-08", "日時:8月8日(土)"),
                                body, date(2025, 8, 7))
    assert got is not None and "weekday" in got, got


def test_rejects_date_far_from_publish():
    """検証 4: 実データの養成講座が 2025 年へ滑落した事故の回帰。

    2025-05-31 は土曜なので検証 3 (曜日) は通ってしまう。範囲チェックが
    無いと「検証済み」として過去年が確定する。これが調査時に起きた事故。
    """
    body = "スケジュール ◆ 5月31日(土) 9:00〜14:10"
    got = mod.verify_event_date(_ex("2025-05-31", "5月31日(土)"),
                                body, date(2026, 5, 1))
    assert got is not None and "out-of-range" in got, got


def test_rejects_update_stamp():
    """検証 5: 実データのキッチンカー記事。「6/16更新」は開催日ではない。"""
    body = "▽6月の出店カレンダー 6/16更新 ※クリックで大きく見られます。"
    got = mod.verify_event_date(_ex("2026-06-16", "6/16更新"),
                                body, date(2026, 6, 1))
    assert got is not None and "update-stamp" in got, got


def test_accepts_evidence_without_weekday():
    """曜日表記が無ければ検証 3 はスキップする。"""
    body = "期間:2026年3月28日から4月5日まで"
    got = mod.verify_event_date(_ex("2026-03-28", "2026年3月28日"),
                                body, date(2026, 2, 25))
    assert got is None, got


def test_accepts_circled_weekday_evidence():
    """実データ: 「6/27㈯」。正規化後に曜日一致を見る。2026-06-27 は土曜。"""
    body = mod.html_to_text("<p>飯能河原6/27㈯・28㈰の営業について</p>")
    got = mod.verify_event_date(_ex("2026-06-27", "6/27(土)"),
                                body, date(2026, 6, 26))
    assert got is None, got


def test_accepts_far_future_date_within_range():
    """実データ: 7/23 公開の「飯能まつり協賛のお願い」に 11/7 の開催日がある。
    記事の主目的が募集でも開催日は採る。2026-11-07 は土曜。"""
    body = "令和8年の飯能まつりは、11月7日(土)、8日(日)に開催を予定しています。"
    got = mod.verify_event_date(_ex("2026-11-07", "11月7日(土)"),
                                body, date(2026, 7, 23))
    assert got is None, got


def test_accepts_evidence_with_retyped_quotes():
    """実データ: 令和8年飯能夏祭り。

    本文は「7月18日(土)“宵宮”」(U+201C/U+201D) だが LLM は `"宵宮"` と
    打ち直して返した。照合時に引用符を畳まないと実在する開催日を取りこぼす。
    2026-07-18 は土曜。
    """
    body = "今年の飯能夏祭りは、7月18日(土)“宵宮”、19日(日)“本祭り”です。"
    got = mod.verify_event_date(_ex("2026-07-18", '7月18日(土)"宵宮"'),
                                body, date(2026, 7, 14))
    assert got is None, got


def test_quote_folding_does_not_weaken_hallucination_check():
    """引用符を畳んでも、本文に無い日付は依然として弾く。"""
    body = "今年の飯能夏祭りは、7月18日(土)“宵宮”です。"
    got = mod.verify_event_date(_ex("2026-09-05", '9月5日(土)"別の祭り"'),
                                body, date(2026, 7, 14))
    assert got is not None and "evidence-not-found" in got, got


def test_accepts_evidence_taken_from_title():
    """実データ: 「飯能駅観光案内所…6月3日(水)台風接近に伴う臨時休業のお知らせ」。

    日付がタイトルにしか無い記事がある。LLM にはタイトル込みで見せているので、
    照合側も同じ文字列を対象にしないと実在する日付を取りこぼす。
    2026-06-03 は水曜。
    """
    match_text = mod.llm_user_message(
        "飯能駅観光案内所「ぷらっと飯能」6月3日(水)台風接近に伴う臨時休業のお知らせ",
        "本日は臨時休業いたします。ご迷惑をおかけします。", "2026-06-02")
    got = mod.verify_event_date(_ex("2026-06-03", "6月3日(水)"),
                                match_text, date(2026, 6, 2))
    assert got is None, got


def test_rejects_reiwa_conversion_error():
    """実データ: 「【休館のお知らせ】おみやげショップ夢馬」。

    本文は「令和8年4月1日より休館」(= 2026-04-01) だが LLM は 2027-04-01 を
    返した。曜日表記が無いので検証 3 では拾えず、公開日 2026-03-10 からの
    範囲チェックもすり抜けて誤った日付が通っていた。機械換算で潰す。
    """
    body = "諸般の事情により令和8年4月1日より休館といたします。"
    got = mod.verify_event_date(_ex("2027-04-01", "令和8年4月1日"),
                                body, date(2026, 3, 10))
    assert got is not None and "reiwa-mismatch" in got, got


def test_accepts_correct_reiwa_conversion():
    body = "諸般の事情により令和8年4月1日より休館といたします。"
    got = mod.verify_event_date(_ex("2026-04-01", "令和8年4月1日"),
                                body, date(2026, 3, 10))
    assert got is None, got


def test_rejects_malformed_date():
    got = mod.verify_event_date(_ex("2026-13-45", "でたらめ"),
                                "でたらめ", date(2026, 8, 7))
    assert got is not None, got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all news-verify tests passed")
