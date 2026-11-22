"""ContentOps CLI

  python3 -m cops init                 本番DBを初期化
  python3 -m cops serve [--demo]       管理画面を起動
  python3 -m cops run-jobs [--limit N] 待機中ジョブを実行
  python3 -m cops enqueue TYPE [--payload JSON] [--key KEY]
  python3 -m cops daily | weekly       定期処理のジョブを投入（同日・同週は重複しない）して実行
  python3 -m cops backup               バックアップ作成
  python3 -m cops status               予算・ジョブの状況
  python3 -m cops seed-demo            ダミーデータ入りのデモDBを作成（本番DBには書かない）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import budget, config, db, jobs
from . import handlers  # noqa: F401


def _conn(demo: bool):
    c = db.connect(demo=demo)
    db.init(c, is_demo=demo)
    return c


def main(argv=None) -> int:
    config.load_dotenv()
    ap = argparse.ArgumentParser(prog="cops")
    ap.add_argument("--demo", action="store_true", help="デモDB（ダミーデータ）を対象にする")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sp = sub.add_parser("serve"); sp.add_argument("--port", type=int, default=config.port())
    rj = sub.add_parser("run-jobs"); rj.add_argument("--limit", type=int, default=10)
    eq = sub.add_parser("enqueue"); eq.add_argument("type"); eq.add_argument("--payload", default="{}")
    eq.add_argument("--key")
    sub.add_parser("daily"); sub.add_parser("weekly"); sub.add_parser("backup"); sub.add_parser("status")
    sub.add_parser("seed-demo")
    a = ap.parse_args(argv)

    if a.cmd == "seed-demo":
        from . import demo
        path = demo.seed()
        print(f"デモDBを作成しました: {path}\n起動: python3 -m cops --demo serve")
        return 0

    c = _conn(a.demo)
    if a.cmd == "init":
        print(f"初期化完了: {config.db_path(a.demo)}")
    elif a.cmd == "serve":
        from . import server
        server.serve(config.db_path(a.demo), a.port)
    elif a.cmd == "run-jobs":
        for r in jobs.run_once(c, a.limit):
            print(json.dumps(r, ensure_ascii=False, default=str))
    elif a.cmd == "enqueue":
        jid, created = jobs.enqueue(c, a.type, json.loads(a.payload), key=a.key)
        print(f"job #{jid} {'作成' if created else '既存（重複のため作成せず）'}")
    elif a.cmd in ("daily", "weekly"):
        today = date.today()
        tag = today.isoformat() if a.cmd == "daily" else f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"
        # 実装済みのジョブのみ投入。Phase 2以降のハンドラが入ったらここに追加される
        plan = {"daily": ["anomaly_check", "backup", "sync_sales"],
                "weekly": ["theme_scoring", "generate_sns_posts", "weekly_review"]}[a.cmd]
        for t in plan:
            if t not in jobs.HANDLERS:
                print(f"skip {t}: 未実装")
                continue
            jid, created = jobs.enqueue(c, t, {"period": tag}, key=f"{t}:{tag}")
            print(f"{t}: job #{jid} {'作成' if created else '既存'}")
        for r in jobs.run_once(c):
            print(json.dumps(r, ensure_ascii=False, default=str))
    elif a.cmd == "backup":
        print(db.backup(c))
    elif a.cmd == "status":
        print(json.dumps({"budget": budget.status(c),
                          "jobs": {r[0]: r[1] for r in c.execute("SELECT status,count(*) FROM jobs GROUP BY 1")}},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
