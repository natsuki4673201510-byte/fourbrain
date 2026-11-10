#!/usr/bin/env python3
"""ふわっち道場ランキング 上位N名のプロフィールからSNSリンクを集める。

使い方:
  python3 scripts/dojo_sns.py                # 昨日(JST)の確定済み6級ランキング 上位30名
  python3 scripts/dojo_sns.py 20261109       # 日付を指定
  python3 scripts/dojo_sns.py 20261109 6 30  # 日付 / 級 / 人数

出力: Markdown の表（Claude Docs のタブにそのまま貼れる形）と、
      同じ内容の JSON を out/dojo_<級>_<日付>.json に保存。
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://api.whowatch.tv"
JST = dt.timezone(dt.timedelta(hours=9))

# プロフィール文にSNSを示すキーワード（行ごとに判定）
SNS_WORDS = re.compile(
    r"(?i)(twitter|ツイッター|(^|[^a-z])x[\s:：（(＠@]|instagram|insta|インスタ|tiktok|ティックトック|"
    r"youtube|ユーチューブ|youtu\.be|ツイキャス|twitcasting|17live|イチナナ|pococha|ポコチャ|"
    r"line|ライン|threads|スレッズ|note\.com|lit\.link|linktr\.ee|showroom|mixch|ミクチャ|iriam|"
    r"reality|bigo|tiktok|ふわっち以外|sns)"
)
URL_RE = re.compile(r"https?://[^\s　）)」』】<>\"']+")
HANDLE_RE = re.compile(r"[@＠][A-Za-z0-9_.]{2,30}")


def get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def extract(desc):
    links, lines = [], []
    for u in URL_RE.findall(desc or ""):
        if "whowatch.tv" in u:  # ふわっち内リンク（アイテム購入など）は除外
            continue
        if u not in links:
            links.append(u)
    for line in (desc or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if SNS_WORDS.search(s) or (HANDLE_RE.search(s) and not URL_RE.search(s)):
            urls = URL_RE.findall(s)
            only_whowatch = urls and all("whowatch.tv" in u for u in urls)
            if s not in lines and not only_whowatch:
                lines.append(s)
    return links, lines


def cell(s):
    return (s or "").replace("|", "｜").replace("\n", " ")


def main():
    yday = (dt.datetime.now(JST) - dt.timedelta(days=1)).strftime("%Y%m%d")
    date = sys.argv[1] if len(sys.argv) > 1 else yday
    grade = sys.argv[2] if len(sys.argv) > 2 else "6"
    top = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    data = get(f"/rankings/whowatch_dojo_{grade}/{date}?detail=true")[0]
    rows = []
    for r in data["rankings"][:top]:
        u = r["user"]
        path = u["user_path"]
        prof_url = "https://whowatch.tv/profile/" + path
        try:
            p = get(f"/users/{urllib.parse.quote(path)}/profile")
        except Exception as e:  # noqa: BLE001
            p = {"error_message": str(e)}
        desc = p.get("description", "")
        links, lines = extract(desc)
        # X(Twitter)で登録したアカウントは user_path が "t:<XのID>" になる
        if path.startswith("t:"):
            xurl = "https://x.com/" + path[2:]
            if xurl not in links:
                links.insert(0, xurl)
        rows.append({
            "rank": r["rank"],
            "name": p.get("name") or u.get("name"),
            "user_path": path,
            "profile_url": prof_url,
            "point": r.get("point"),
            "sns_links": links,
            "sns_mentions": lines,
            "note": p.get("error_message", ""),
        })

    os.makedirs("out", exist_ok=True)
    meta = {"date": date, "grade": grade, "title": data.get("title"), "is_fixed": data.get("is_fixed")}
    with open(f"out/dojo_{grade}_{date}.json", "w") as f:
        json.dump({"meta": meta, "rows": rows}, f, ensure_ascii=False, indent=1)

    d = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    print(f"# ふわっち道場 {grade}級 上位{top}名 SNS一覧（{d}）\n")
    print(f"ランキング状態: {data.get('title')} ・ 出典: "
          f"[ふわっち道場ランキング](https://whowatch.tv/events/whowatch_dojo/{date}?tab=RANKING&rankingType=whowatch_dojo_{grade}&eventType=ranking-event)\n")
    print("| 順位 | 名前 | ポイント | プロフィール | SNSリンク | プロフ内のSNS記載 |")
    print("| --- | --- | --- | --- | --- | --- |")
    for x in rows:
        links = " ".join(f"[{cell(l)}]({l})" for l in x["sns_links"]) or "なし"
        ment = " / ".join(cell(m) for m in x["sns_mentions"]) or ("退会済み" if x["note"] else "なし")
        print(f"| {x['rank']} | {cell(x['name'])} | {x['point']:,} | [プロフ]({x['profile_url']}) | {links} | {ment} |")


if __name__ == "__main__":
    main()
