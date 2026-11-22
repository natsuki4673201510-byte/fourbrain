"""月間費用上限の管理。

- 'external'（API・クラウド等の追加費用）だけが上限の対象。
- 'claude_plan'（Claude本体契約）と 'platform_fee'（販売手数料）は別枠で集計のみ。
- 実行中ジョブの見積額も「予約済み」として加算し、並行実行で上限を超えないようにする。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from . import settings as st


class BudgetExceeded(Exception):
    pass


def month_key(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m")


def spent(conn: sqlite3.Connection, month: str | None = None, category: str = "external") -> float:
    month = month or month_key()
    r = conn.execute(
        "SELECT coalesce(sum(amount_jpy),0) FROM costs WHERE category=? AND substr(occurred_at,1,7)=?",
        (category, month),
    ).fetchone()
    return float(r[0])


def reserved(conn: sqlite3.Connection) -> float:
    r = conn.execute("SELECT coalesce(sum(estimated_cost_jpy),0) FROM jobs WHERE status='running'").fetchone()
    return float(r[0])


def status(conn: sqlite3.Connection) -> dict:
    cap = float(st.get(conn, "monthly_budget_jpy") or 0)
    s = spent(conn)
    res = reserved(conn)
    warn = float(st.get(conn, "budget_warn_ratio") or 0.8)
    used = s + res
    return {
        "month": month_key(),
        "cap_jpy": cap,
        "spent_jpy": round(s, 1),
        "reserved_jpy": round(res, 1),
        "remaining_jpy": round(cap - used, 1),
        "ratio": round(used / cap, 3) if cap else None,
        "level": "over" if cap and used >= cap else ("warn" if cap and used >= cap * warn else "ok"),
        "claude_plan_jpy": st.get(conn, "claude_plan_monthly_jpy"),
        "platform_fees_jpy": round(spent(conn, category="platform_fee"), 1),
    }


def check(conn: sqlite3.Connection, estimate_jpy: float) -> None:
    """見積額を足して上限を超えるなら BudgetExceeded。見積0のジョブは常に通す。"""
    if estimate_jpy <= 0:
        return
    b = status(conn)
    if b["cap_jpy"] <= 0 or b["remaining_jpy"] < estimate_jpy:
        raise BudgetExceeded(
            f"月間上限 {b['cap_jpy']:.0f}円 に対し 使用済{b['spent_jpy']:.0f}円 + 予約{b['reserved_jpy']:.0f}円、"
            f"見積{estimate_jpy:.0f}円は実行できません"
        )


def record(conn: sqlite3.Connection, service: str, amount_jpy: float, *, category: str = "external",
           is_estimate: bool = False, description: str = "", job_id: int | None = None,
           product_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO costs(service, category, amount_jpy, is_estimate, description, job_id, product_id)"
        " VALUES (?,?,?,?,?,?,?)",
        (service, category, amount_jpy, int(is_estimate), description, job_id, product_id),
    )
    return cur.lastrowid
