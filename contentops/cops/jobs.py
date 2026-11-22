"""ジョブキュー。

保証すること:
- 同一処理の重複実行防止: idempotency_key の UNIQUE 制約 + 'queued'→'running' のアトミックな取得
- 無制限リトライ防止: max_attempts（既定2回）と指数バックオフ、NonRetryable は即失敗
- 途中再開: ハンドラは ctx.save_checkpoint() で進捗を保存し、再実行時に ctx.checkpoint から再開
- 費用上限: 実行前に見積額で budget.check()。超過時は 'blocked' (budget) にして実行しない
- 1日の実行数上限: settings.max_jobs_per_day
- 処理履歴: job_logs に開始・終了・例外（トレースバック）を記録
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import budget
from . import settings as st

# 既知のジョブ種別（未実装のものはハンドラ登録まで 'blocked: no_handler' で待機）
JOB_TYPES: dict[str, str] = {
    "healthcheck": "動作確認",
    "backup": "DB・原稿のバックアップ",
    "anomaly_check": "異常検知（予算・失敗ジョブ・停滞ジョブ）",
    "market_research": "市場調査（Phase 2）",
    "competitor_analysis": "競合分析（Phase 2）",
    "theme_scoring": "テーマ評価（Phase 2）",
    "produce_content": "原稿制作 日本語→英語（Phase 3）",
    "quality_check": "品質検証（Phase 3）",
    "render_pdf": "PDF制作（Phase 3）",
    "generate_sns_posts": "X投稿案の制作（Phase 4）",
    "publish_sns_post": "承認済み投稿の配信（Phase 4・要承認）",
    "sync_sales": "売上データ取得（Phase 5）",
    "weekly_review": "週次分析・改善提案（Phase 6）",
    "suggest_related": "関連商品提案（Phase 6）",
}

STALE_MINUTES = 90


class NonRetryable(Exception):
    """再試行しても結果が変わらない失敗（入力不正・認証エラー・規約違反リスク等）"""


@dataclass
class Handler:
    fn: Callable
    estimate_jpy: Callable[[dict], float] = lambda payload: 0.0


HANDLERS: dict[str, Handler] = {}


def handler(job_type: str, estimate_jpy: Callable[[dict], float] | None = None):
    if job_type not in JOB_TYPES:
        raise ValueError(f"unknown job type {job_type}")

    def deco(fn):
        HANDLERS[job_type] = Handler(fn, estimate_jpy or (lambda p: 0.0))
        return fn
    return deco


@dataclass
class Ctx:
    conn: sqlite3.Connection
    job: dict
    payload: dict
    checkpoint: dict = field(default_factory=dict)

    def log(self, msg: str, level: str = "info") -> None:
        log(self.conn, self.job["id"], msg, level)

    def save_checkpoint(self, data: dict) -> None:
        self.checkpoint = data
        self.conn.execute("UPDATE jobs SET checkpoint=?, updated_at=datetime('now') WHERE id=?",
                          (json.dumps(data, ensure_ascii=False), self.job["id"]))


def log(conn, job_id, msg, level="info"):
    conn.execute("INSERT INTO job_logs(job_id, level, message) VALUES (?,?,?)", (job_id, level, msg[:8000]))


def default_key(job_type: str, payload: dict) -> str:
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return f"{job_type}:{h}"


def enqueue(conn: sqlite3.Connection, job_type: str, payload: dict | None = None, *,
            key: str | None = None, max_attempts: int = 2, run_at: str | None = None) -> tuple[int, bool]:
    """(job_id, created)。同じキーのジョブが既にあれば作らずに既存IDを返す。"""
    if job_type not in JOB_TYPES:
        raise ValueError(f"未知のジョブ種別: {job_type}")
    payload = payload or {}
    key = key or default_key(job_type, payload)
    max_attempts = max(1, min(int(max_attempts), 5))  # 上限5回
    cur = conn.execute(
        "INSERT OR IGNORE INTO jobs(type, idempotency_key, payload, max_attempts, next_run_at)"
        " VALUES (?,?,?,?,coalesce(?, datetime('now')))",
        (job_type, key, json.dumps(payload, ensure_ascii=False), max_attempts, run_at),
    )
    if cur.rowcount:
        return cur.lastrowid, True
    return conn.execute("SELECT id FROM jobs WHERE idempotency_key=?", (key,)).fetchone()[0], False


def _recover(conn: sqlite3.Connection) -> None:
    # 異常終了で running のまま残ったジョブを回収
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    for j in conn.execute("SELECT id, attempts, max_attempts FROM jobs WHERE status='running' AND started_at < ?",
                          (cutoff,)).fetchall():
        new = "queued" if j["attempts"] < j["max_attempts"] else "failed"
        conn.execute("UPDATE jobs SET status=?, last_error=coalesce(last_error,'')||' [stale: 再開対象]',"
                     " updated_at=datetime('now') WHERE id=?", (new, j["id"]))
        log(conn, j["id"], f"停滞ジョブを回収 → {new}", "warn")
    # 予算・ハンドラ不足でブロック中のものは毎回再評価
    conn.execute("UPDATE jobs SET status='queued', blocked_reason=NULL WHERE status='blocked'"
                 " AND blocked_reason IN ('budget','no_handler','daily_limit')")


def started_today(conn) -> int:
    return conn.execute("SELECT count(*) FROM jobs WHERE date(started_at)=date('now')").fetchone()[0]


def run_once(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """実行可能なジョブを最大 limit 件処理して結果を返す。"""
    _recover(conn)
    done = []
    max_daily = int(st.get(conn, "max_jobs_per_day") or 0)
    while len(done) < limit:
        # 各分岐で必ず status か next_run_at が変わるため、同じジョブを再取得することはない
        j = conn.execute("SELECT * FROM jobs WHERE status='queued' AND next_run_at <= datetime('now')"
                         " ORDER BY next_run_at, id LIMIT 1").fetchone()
        if not j:
            break
        j = dict(j)
        h = HANDLERS.get(j["type"])
        if not h:
            conn.execute("UPDATE jobs SET status='blocked', blocked_reason='no_handler' WHERE id=?", (j["id"],))
            done.append({"id": j["id"], "status": "blocked", "reason": "no_handler"})
            continue
        if max_daily and started_today(conn) >= max_daily:
            conn.execute("UPDATE jobs SET status='blocked', blocked_reason='daily_limit' WHERE id=?", (j["id"],))
            log(conn, j["id"], f"1日の実行上限({max_daily})に達したため保留", "warn")
            done.append({"id": j["id"], "status": "blocked", "reason": "daily_limit"})
            break
        payload = json.loads(j["payload"] or "{}")
        est = float(h.estimate_jpy(payload) or 0)
        try:
            budget.check(conn, est)
        except budget.BudgetExceeded as e:
            conn.execute("UPDATE jobs SET status='blocked', blocked_reason='budget', last_error=? WHERE id=?",
                         (str(e), j["id"]))
            log(conn, j["id"], str(e), "warn")
            done.append({"id": j["id"], "status": "blocked", "reason": "budget"})
            continue
        claimed = conn.execute(
            "UPDATE jobs SET status='running', attempts=attempts+1, started_at=datetime('now'),"
            " estimated_cost_jpy=?, updated_at=datetime('now') WHERE id=? AND status='queued'",
            (est, j["id"])).rowcount
        if not claimed:  # 他プロセスが取得済み
            continue
        j["attempts"] += 1
        ctx = Ctx(conn, j, payload, json.loads(j["checkpoint"] or "{}"))
        log(conn, j["id"], f"開始 type={j['type']} attempt={j['attempts']}/{j['max_attempts']} 見積={est:.0f}円")
        try:
            result = h.fn(ctx)
            conn.execute("UPDATE jobs SET status='succeeded', result=?, finished_at=datetime('now'),"
                         " last_error=NULL, updated_at=datetime('now') WHERE id=?",
                         (json.dumps(result, ensure_ascii=False, default=str), j["id"]))
            log(conn, j["id"], "完了")
            done.append({"id": j["id"], "status": "succeeded", "result": result})
        except Exception as e:  # noqa: BLE001 - すべて記録してから判定
            tb = traceback.format_exc()
            retry = not isinstance(e, NonRetryable) and j["attempts"] < j["max_attempts"]
            if retry:
                delay = 5 * 2 ** (j["attempts"] - 1)
                conn.execute("UPDATE jobs SET status='queued', last_error=?, updated_at=datetime('now'),"
                             " next_run_at=datetime('now', ?) WHERE id=?",
                             (f"{type(e).__name__}: {e}", f"+{delay} minutes", j["id"]))
            else:
                conn.execute("UPDATE jobs SET status='failed', last_error=?, finished_at=datetime('now'),"
                             " updated_at=datetime('now') WHERE id=?", (f"{type(e).__name__}: {e}", j["id"]))
            log(conn, j["id"], tb, "error")
            done.append({"id": j["id"], "status": "queued(retry)" if retry else "failed", "error": str(e)})
    return done


def retry(conn, job_id: int) -> None:
    """失敗ジョブを人間の判断で1回だけ再実行（attempts の上限を1増やす）。"""
    n = conn.execute("UPDATE jobs SET status='queued', max_attempts=attempts+1, next_run_at=datetime('now'),"
                     " updated_at=datetime('now') WHERE id=? AND status IN ('failed','cancelled')", (job_id,)).rowcount
    if not n:
        raise ValueError("失敗またはキャンセル済みのジョブのみ再実行できます")
    log(conn, job_id, "手動で再実行を指示", "info")


def cancel(conn, job_id: int) -> None:
    n = conn.execute("UPDATE jobs SET status='cancelled', updated_at=datetime('now')"
                     " WHERE id=? AND status IN ('queued','blocked')", (job_id,)).rowcount
    if not n:
        raise ValueError("待機中のジョブのみキャンセルできます")
    log(conn, job_id, "キャンセル", "info")
