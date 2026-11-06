#! /usr/bin/env python3
# ↑シェバンこのファイルをちょくせつ実行するときにどのインタプリタでするか

"""Garmin Personal API fetcher — runs entirely on your Mac.

- Reads your API key from the GARMIN_API_KEY environment variable or from
  ~/.garmin-personal-api-key (one line). The key never leaves your Mac and
  must never be pasted into chat.
- Mints a fresh 24h access token in memory (never saved to disk), fetches
  HRV / daily summaries / sleep summaries, and saves the raw JSON next to
  this script under out/.
- Prints a one-line summary per day. Send the out/*.json files (data only)
  to Muse for integration.
"""

import json
import os
import sys
import urllib.error  # HTTPエラーを表す型
import urllib.request # URLにアクセスする道具
from datetime import date, timedelta

BASE = "https://personal.connectapi.garmin.com"

def get_api_key():
    key = os.environ.get("GARMIN_API_KEY", "").strip()
    if key:
        return key
    path = os.path.expanduser("~/.garmin-personal-api-key")
    if os.path.exists(path):
        return open(path).read().strip()
    sys.exit(
        "APIキーが見つかりません。環境変数GARMIN_API_KEY または~/.garmin-personal-api-keyに１行で保存してください"

    )

def mint_token(api_key):
    #urllib.request.Request(...)で[HTTPリクエスト]
    req = urllib.request.Request(
        BASE + "/personalapitoken-service/personal-api/personal-api-key/token",
        method="POST",
        data=b"",
    )
    req.add_header("Authorization", f"ApiKey {api_key}")
    req.add_header("Accept", "*/*")
    with urllib.request.urlopen(req, timeout=60) as resp:
        # resp.read() はバイト列で届くので .decode("utf-8") で文字列に戻す。
        return resp.read().decode("utf-8").strip()



def get_json(token, path):
    req = urllib.request.Request(BASE + path, method="GET")
    req.add_header("Authorization", f"Bearer {token}") #Bearer = トークンの提示形式
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else None)

    except urllib.error.HTTPError as e:
        return e.code, None

def chunks(start, end, size=31):
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=size-1), end)
        yield cur, nxt #(開始日、終了日)のくみを一つ渡して一時停止
        cur = nxt + timedelta(days=1) #次の区間の開始日へ進める


def main():
    # sys.argvはコマンドライン引数のリスト。[0]はスクリプト名。[1]が引数の最初
    days = int(sys.argv[1]) if len(sys.argv)>1 else 7
    today = date.today()
    start = today - timedelta(days=days-1)
    yesterday = today - timedelta(days=1)

    token = mint_token(get_api_key())

    status, hrv = get_json(token, f"/hrv-service/hrv/daily/{start}/{today}")
    if status != 200:
        sys.exit(f"HRV取得に失敗(HTTP {status})")

    daily = {"data": []} #辞書{key: 値}
    day = start
    while day <= yesterday:
        status, part = get_json(
            token,
            f"/usersummary-service/v2/dailysummaries?startDate={day}&endDate={day}",
        )
        if status != 200:
            sys.exit(f"日時サマリー取得に失敗しました (HTTP {status})")
        if part and part.get("data"):
            daily["data"].extend(part["data"])
        day += timedelta(days=1)

    sleep = []
    for s0, s1 in chunks(start, today):
        status, part = get_json(
            token,
            f"/sleep-service/sleep/dailySleepSummariesByDate?startDate={s0}&endDate={s1}",
        )
        if status != 200:
            sys.exit(f"睡眠取得に失敗しました(HTTP {status})")
        if part:
            sleep.extend(part)

    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out") #このファイルにあるフォルダ
    os.makedirs(outdir, exist_ok=True) # フォルダ作成、既にあればエラーにしない
    outfile = os.path.join(outdir, f"garmin-personal-{start}-{today}.json")
    with open(outfile, "w", encoding='utf-8') as f:
        json.dump(
            {'hrv':hrv, "daily_summaries":daily, "sleep":sleep},
            f,
            ensure_ascii=False,
            indent=1,
        )

    hrv_by_date = {h["calendarDate"]: h for h in (hrv or {}).get("hrvSummaries", [])}
    sleep_by_date = {s["calendarDate"]: s for s in sleep}
    daily_by_date = {r["calendarDate"]: r for r in (daily or {}).get("data", [])}
    print(f"saved: {outfile}")
    for d in sorted(set(hrv_by_date) | set(sleep_by_date) | set(daily_by_date)):
        h = hrv_by_date.get(d, {})  # 無い日は空辞書 → 以後の .get は全部 None になり落ちない
        s = sleep_by_date.get(d, {})
        row = daily_by_date.get(d, {})
        # .get の多段つなぎ: sleepScores → overall → value を安全にたどる。
        # 途中でキーが無い/None でも ( ... or {}) が空辞書に置き換えてくれる。
        score = ((s.get("sleepScores") or {}).get("overall") or {}).get("value")
        bb = row.get("bodyBattery") or {}
        # 複数行に分けた f文字列は自動でつながる。{ } の中は式なので
        # (row.get('heartRate') or {}).get('restingValue') のような取り出しも書ける。
        print(
            f"{d} HRV {h.get('lastNightAvg')} (週平均{h.get('weeklyAvg')}, {h.get('status')})"
            f" / 睡眠スコア {score}"
            f" / 安静時心拍 {(row.get('heartRate') or {}).get('restingValue')}"
            f" / ストレス {(row.get('stress') or {}).get('avgLevel')}"
            f" / BodyBattery +{bb.get('chargedValue')}/-{bb.get('drainedValue')}"
            f" / SpO2 {(row.get('pulseOx') or {}).get('avgValue')}"
            f" / 呼吸数 {(row.get('respiration') or {}).get('avgValue')}"
        )


# 「このファイルを直接実行したときだけ main() を呼ぶ」という定番の決まり文句。
if __name__ == "__main__":
    main()
