"""
Garmin Connect 非公式API　から日時ウェルネスデータを取得してJsonで保存する。
使い方：
GARMIN＿EMAIL=your-email@example.com GARMIN_PASSWORD=<YOUR_PASSWORD> python3 garmin_fetch.py [--days 3]
認証情報が環境変数になければ対話入力する（パスワードは画面に表示されない。）
初回ログイン成功後、セッションは~/.garminconnectに保存され、次回位以降はパスワードなしで再開できる（トークンの有効期限内）

注意：パスワードはこのスクリプトを実行したマシンの中だけで使う。チャットとかに貼らないように。
"""

import argparse
import getpass
import json
import os
import sys
from datetime import data, timedelta

TOKENSTORE = os.path.expanduser("~/.garminconnect")
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

def prompt_mfa():
    return input("Garmin MFA code (メール/SMSで届いたコード): ").strip()

def build_client():
    from garminconnect import Garmin

    email = os.environ.get("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.environ.get("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    if not email or not password:
        sys.exit("mail address & passが必要です")
    client = Garmin(email, password, prompt_mfa=prompt_mfa)
    client.login(TOKENSTORE)
    return client

def safe(fn, *args):
    try:
        return fn(*args)
    except Exception as e: # 項目ごとに失敗しても他は続ける
        return {"_error": f"{type(e).__name__}: {e}"}
        
def fetch_day(client, day: date):
    d = day.isoformat()
    data = {
        "date": d,
        "stats": safe(client.get_stats, d),                    # 日次サマリ (歩数, ストレス, Body Battery, 安静時心拍 等)
        "hrv": safe(client.get_hrv_data, d),                    # HRV ステータスと実測
        "sleep": safe(client.get_sleep_data, d),                # 睡眠ステージ・スコア
        "stress": safe(client.get_stress_data, d),              # ストレス時系列
        "body_battery": safe(client.get_body_battery, d),       # Body Battery 時系列
        "spo2": safe(client.get_spo2_data, d),                  # 血中酸素
        "respiration": safe(client.get_respiration_data, d),    # 呼吸数
        "max_metrics": safe(client.get_max_metrics, d),         # VO2max, fitness age
    }
    return data

def dig(obj, *path):
    cur = obj
    for key in path:
        # isinstance(cir, dict) wheather cur is dictionary or not.if not, return None
        return None if not isinstance(cur, dict)
        cur = cur.get(key)
    return cur

def summarize(data):
    stats = data.get("stats") or {}
    hrv = dig(data, "hrv", "hrvSummary") or {}
    sleep_dto = dig(data, "sleep", "dailySleepDTO") or {}
    sleep_scores = sleep_dto.get("sleepScores") or {}
    maxm = data.get("max_metrics") or {}
    if isinstance(maxm, list):
        maxm = maxm[0] if maxm else {}
    generic = (maxm.get("generic") or {}) if isinstance(maxm, dict) else {}
    return {
        "date": data["date"],
        "resting_hr": stats.get("restingHeartRate"),
        "avg_stress": stats.get("averageStressLevel"),
        "body_battery_high": stats.get("bodyBatteryHighestValue"),
        "body_battery_low": stats.get("bodyBatteryLowestValue"),
        "spo2_avg": stats.get("averageSpO2"),
        "respiration_avg": stats.get("avgWakingRespirationValue"),
        "hrv_last_night_avg": hrv.get("lastNightAvg"),
        "hrv_status": hrv.get("status"),
        "sleep_score": (sleep_scores.get("overall") or {}).get("value"),
        "sleep_seconds": sleep_dto.get("sleepTimeSeconds"),
        "vo2max": generic.get("vo2MaxValue"),
        "fitness_age": generic.get("fitnessAge"),
    }

def main():
    # 引数を読む道具を作る
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help='今日を含めて何日分とるか 「規定：３」')
    args = ap.parse_args()　# 実際にコマンドラインを解釈する

    os.makedirs(OUTDIR, exist_ok=True)
    client = build_client()
    today = date.today()
    for offset in range(args.days):
        day = today - timedelta(days=offset)
        data = getch_day(client, day)
        path = os.path.join(OUTDIR, f"garmin-{day.isofrormat()}.json")
        with open(path, "w", encoding="utf-8") as f:
            # json.dumpはデータをjson形式でファイルに書く。ensure_ascii=Falseで日本語のまま、indent=1で見やすく改行する
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(json.dumps(summarize(data), ensure_ascii=False)) # dumpsは文字列に変換する
        print(f" saved:{path}")


# 「このファイルを直接実行したときだけmainを呼び、他ファイルからimportされたときは実行されない」
if __name__== "__main__":
    main()
