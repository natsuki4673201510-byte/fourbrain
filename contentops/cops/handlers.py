"""ジョブハンドラ（Phase 1 分）。Phase 2 以降のハンドラはここに追加していく。"""
from __future__ import annotations

from . import budget, db
from . import settings as st
from .jobs import Ctx, handler


@handler("healthcheck")
def healthcheck(ctx: Ctx) -> dict:
    n = ctx.conn.execute("SELECT count(*) FROM themes").fetchone()[0]
    return {"ok": True, "themes": n}


@handler("backup")
def backup(ctx: Ctx) -> dict:
    path = db.backup(ctx.conn, keep=int(st.get(ctx.conn, "backup_keep") or 14))
    ctx.log(f"バックアップ作成: {path.name}")
    return {"file": path.name}


@handler("anomaly_check")
def anomaly_check(ctx: Ctx) -> dict:
    c = ctx.conn
    issues = []
    b = budget.status(c)
    if b["level"] != "ok":
        issues.append({"kind": "budget", "level": b["level"],
                       "message": f"外部費用 {b['spent_jpy']:.0f}/{b['cap_jpy']:.0f}円 ({(b['ratio'] or 0)*100:.0f}%)"})
    failed = c.execute("SELECT count(*) FROM jobs WHERE status='failed' AND finished_at > datetime('now','-1 day')"
                       ).fetchone()[0]
    if failed:
        issues.append({"kind": "failed_jobs", "level": "warn", "message": f"過去24時間の失敗ジョブ {failed}件"})
    blocked = c.execute("SELECT blocked_reason, count(*) FROM jobs WHERE status='blocked' GROUP BY 1").fetchall()
    for r in blocked:
        issues.append({"kind": "blocked_jobs", "level": "info", "message": f"保留ジョブ({r[0]}) {r[1]}件"})
    refunds = c.execute("SELECT coalesce(sum(refunded_jpy),0), coalesce(sum(amount_jpy),0) FROM sales"
                        " WHERE occurred_at > datetime('now','-7 day')").fetchone()
    if refunds[1] and refunds[0] / refunds[1] > 0.1:
        issues.append({"kind": "refund_rate", "level": "warn",
                       "message": f"直近7日の返金率 {refunds[0]/refunds[1]*100:.0f}%"})
    for i in issues:
        ctx.log(i["message"], "warn" if i["level"] != "info" else "info")
    return {"issues": issues}
