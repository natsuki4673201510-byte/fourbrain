"""ドメイン操作（テーマ・商品・原稿・SNS・承認・ダッシュボード）。"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata

from . import budget, config, jobs
from . import settings as st
from .db import row, rows, tx

# ---------------------------------------------------------------- 共通

def audit(conn, actor: str, action: str, detail: dict | str | None = None) -> None:
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    conn.execute("INSERT INTO audit_log(actor, action, detail) VALUES (?,?,?)", (actor, action, detail))


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"[^\w\s-]", "", t)
    return re.sub(r"[\s_-]+", "-", t).strip("-")[:80] or "theme"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- テーマ

THEME_FIELDS = ["name", "target_buyer", "pain_point", "demand_evidence", "similar_products", "unmet_needs",
                "differentiation", "price_usd", "production_cost_jpy", "recurring_demand", "score_demand",
                "score_differentiation", "score_motivation", "score_recurring", "score_ease", "score_rationale",
                "data_origin", "research_run_id"]
SCORE_MAX = {"score_demand": 30, "score_differentiation": 25, "score_motivation": 20,
             "score_recurring": 15, "score_ease": 10}


def upsert_theme(conn, data: dict, evidence: list[dict] | None = None,
                 competitors: list[dict] | None = None) -> tuple[int, bool]:
    """slug で重複を判定。既存なら評価を更新（created=False）。"""
    if not data.get("name"):
        raise ValueError("テーマ名は必須です")
    for k, mx in SCORE_MAX.items():
        v = data.get(k)
        if v is not None and not (0 <= float(v) <= mx):
            raise ValueError(f"{k} は 0〜{mx} の範囲です")
    slug = data.get("slug") or slugify(data["name"])
    vals = {k: data.get(k) for k in THEME_FIELDS if k in data}
    with tx(conn):
        existing = row(conn, "SELECT id FROM themes WHERE slug=?", (slug,))
        if existing:
            tid = existing["id"]
            if vals:
                sets = ", ".join(f"{k}=?" for k in vals)
                conn.execute(f"UPDATE themes SET {sets}, updated_at=datetime('now') WHERE id=?",
                             (*vals.values(), tid))
            created = False
        else:
            cols = ["slug", *vals]
            tid = conn.execute(f"INSERT INTO themes({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                               (slug, *vals.values())).lastrowid
            created = True
        for ev in evidence or []:
            if not ev.get("url") or not ev.get("retrieved_at"):
                raise ValueError("根拠には url と retrieved_at（取得日）が必須です")
            conn.execute("INSERT OR IGNORE INTO evidence(theme_id,url,title,source_type,metric_name,metric_value,"
                         "excerpt,retrieved_at) VALUES (?,?,?,?,?,?,?,?)",
                         (tid, ev["url"], ev.get("title"), ev.get("source_type"), ev.get("metric_name"),
                          ev.get("metric_value"), ev.get("excerpt"), ev["retrieved_at"]))
        for c in competitors or []:
            conn.execute("INSERT OR IGNORE INTO competitors(theme_id,name,url,platform,price,currency,sales_signal,"
                         "weaknesses,retrieved_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (tid, c["name"], c.get("url"), c.get("platform"), c.get("price"), c.get("currency"),
                          c.get("sales_signal"), c.get("weaknesses"), c.get("retrieved_at")))
    return tid, created


def list_themes(conn) -> list[dict]:
    ts = rows(conn, "SELECT t.*, (SELECT count(*) FROM evidence e WHERE e.theme_id=t.id) AS evidence_count,"
                    " (SELECT count(*) FROM competitors c WHERE c.theme_id=t.id) AS competitor_count,"
                    " (SELECT code FROM products p WHERE p.theme_id=t.id) AS product_code"
                    " FROM themes t ORDER BY score_total DESC, id")
    return ts


def theme_detail(conn, tid: int) -> dict:
    t = row(conn, "SELECT * FROM themes WHERE id=?", (tid,))
    if not t:
        raise LookupError("theme not found")
    t["evidence"] = rows(conn, "SELECT * FROM evidence WHERE theme_id=? ORDER BY retrieved_at DESC", (tid,))
    t["competitors"] = rows(conn, "SELECT * FROM competitors WHERE theme_id=? ORDER BY price", (tid,))
    return t


def set_theme_status(conn, tid: int, status: str, actor="human") -> dict:
    if status not in ("discovered", "shortlisted", "approved", "rejected", "archived"):
        raise ValueError("invalid status")
    t = row(conn, "SELECT * FROM themes WHERE id=?", (tid,))
    if not t:
        raise LookupError("theme not found")
    out: dict = {"theme_id": tid, "status": status}
    if status == "approved":
        out.update(approve_theme(conn, t, actor))
    else:
        conn.execute("UPDATE themes SET status=?, updated_at=datetime('now') WHERE id=?", (status, tid))
    audit(conn, actor, "theme.status", {"theme_id": tid, "status": status})
    return out


def approve_theme(conn, t: dict, actor: str) -> dict:
    """テーマ承認 → 商品を作成し、制作ジョブを投入（同テーマ2回目は既存商品を返す）。"""
    existing = row(conn, "SELECT * FROM products WHERE theme_id=?", (t["id"],))
    if existing:
        return {"product_id": existing["id"], "product_code": existing["code"], "created": False}
    limit = int(st.get(conn, "max_products_in_production") or 0)
    active = conn.execute("SELECT count(*) FROM products WHERE status IN ('planning','producing')").fetchone()[0]
    if limit and active >= limit:
        raise ValueError(f"制作中の商品が上限({limit})に達しています。先に既存商品を進めるか上限を変更してください")
    with tx(conn):
        conn.execute("UPDATE themes SET status='approved', updated_at=datetime('now') WHERE id=?", (t["id"],))
        n = conn.execute("SELECT coalesce(max(id),0)+1 FROM products").fetchone()[0]
        code = f"P{n:04d}"
        pid = conn.execute("INSERT INTO products(code, theme_id, title, price_usd) VALUES (?,?,?,?)",
                           (code, t["id"], t["name"], t.get("price_usd"))).lastrowid
        conn.execute("INSERT INTO product_status_history(product_id,to_status,note) VALUES (?,?,?)",
                     (pid, "planning", "テーマ承認により作成"))
    job_id, _ = jobs.enqueue(conn, "produce_content", {"product_id": pid}, key=f"produce_content:product:{pid}")
    return {"product_id": pid, "product_code": code, "created": True, "job_id": job_id}


# ---------------------------------------------------------------- 商品

TRANSITIONS = {
    "planning": {"producing", "stopped"},
    "producing": {"awaiting_approval", "planning", "stopped"},
    "awaiting_approval": {"producing", "on_sale", "stopped"},
    "on_sale": {"paused", "stopped"},
    "paused": {"on_sale", "stopped"},
    "stopped": {"planning"},
}
NEEDS_APPROVAL = {"on_sale"}  # 外部公開は承認必須


def list_products(conn) -> list[dict]:
    return rows(conn, """
      SELECT p.*, t.score_total,
        (SELECT max(version) FROM content_versions c WHERE c.product_id=p.id AND lang='ja' AND kind='manuscript') AS ja_version,
        (SELECT max(version) FROM content_versions c WHERE c.product_id=p.id AND lang='en' AND kind='manuscript') AS en_version,
        (SELECT max(version) FROM content_versions c WHERE c.product_id=p.id AND kind='pdf') AS pdf_version,
        (SELECT count(*) FROM qa_checks q WHERE q.product_id=p.id AND result='fail') AS qa_fail,
        (SELECT count(*) FROM sns_posts s WHERE s.product_id=p.id AND status<>'rejected') AS post_count
      FROM products p LEFT JOIN themes t ON t.id=p.theme_id ORDER BY p.id""")


def get_product(conn, pid: int) -> dict:
    p = row(conn, "SELECT * FROM products WHERE id=?", (pid,))
    if not p:
        raise LookupError("product not found")
    return p


def transition(conn, pid: int, to: str, note: str = "", actor="human", approved: bool = False) -> dict:
    p = get_product(conn, pid)
    if to not in TRANSITIONS.get(p["status"], set()):
        raise ValueError(f"{p['status']} → {to} には変更できません")
    if to in NEEDS_APPROVAL and not approved:
        aid = request_approval(conn, "publish_product", "product", pid,
                               f"{p['code']}「{p['title']}」を販売開始（外部公開）", {"to": to})
        return {"status": p["status"], "approval_id": aid, "pending": True}
    with tx(conn):
        conn.execute("UPDATE products SET status=?, updated_at=datetime('now'),"
                     " launched_at=CASE WHEN ?='on_sale' AND launched_at IS NULL THEN datetime('now') ELSE launched_at END"
                     " WHERE id=?", (to, to, pid))
        conn.execute("INSERT INTO product_status_history(product_id,from_status,to_status,note) VALUES (?,?,?,?)",
                     (pid, p["status"], to, note))
    audit(conn, actor, "product.transition", {"product_id": pid, "from": p["status"], "to": to})
    return {"status": to, "pending": False}


def update_product(conn, pid: int, data: dict) -> dict:
    allowed = {"title", "subtitle", "price_usd", "platform", "product_url", "production_minutes", "structure"}
    vals = {k: v for k, v in data.items() if k in allowed}
    if vals:
        sets = ", ".join(f"{k}=?" for k in vals)
        conn.execute(f"UPDATE products SET {sets}, updated_at=datetime('now') WHERE id=?", (*vals.values(), pid))
    return get_product(conn, pid)


# ---------------------------------------------------------------- 原稿

def save_content(conn, pid: int, lang: str, text: str, kind: str = "manuscript", author: str = "human") -> dict:
    """新しいバージョンとして保存（上書きしない）。同一内容なら既存バージョンを返す。"""
    if lang not in ("ja", "en") or kind not in ("manuscript", "sales_page"):
        raise ValueError("lang/kind が不正です")
    p = get_product(conn, pid)
    h = sha(text)
    ex = row(conn, "SELECT * FROM content_versions WHERE product_id=? AND lang=? AND kind=? AND content_hash=?",
             (pid, lang, kind, h))
    if ex:
        return {**ex, "duplicate": True}
    with tx(conn):
        v = conn.execute("SELECT coalesce(max(version),0)+1 FROM content_versions WHERE product_id=? AND lang=?"
                         " AND kind=?", (pid, lang, kind)).fetchone()[0]
        rel = f"products/{p['code']}/{lang}/{kind}-v{v}.md"
        f = config.data_dir() / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        vid = conn.execute("INSERT INTO content_versions(product_id,lang,kind,version,path,content_hash,char_count,"
                           "author) VALUES (?,?,?,?,?,?,?,?)",
                           (pid, lang, kind, v, rel, h, len(text), author)).lastrowid
    return {**row(conn, "SELECT * FROM content_versions WHERE id=?", (vid,)), "duplicate": False}


def content_bundle(conn, pid: int) -> dict:
    p = get_product(conn, pid)
    out = {"product": p, "versions": rows(conn, "SELECT * FROM content_versions WHERE product_id=?"
                                                " ORDER BY kind, lang, version DESC", (pid,)),
           "qa": rows(conn, "SELECT * FROM qa_checks WHERE product_id=? ORDER BY checked_at DESC", (pid,))}
    for lang in ("ja", "en"):
        v = row(conn, "SELECT path FROM content_versions WHERE product_id=? AND lang=? AND kind='manuscript'"
                      " ORDER BY version DESC LIMIT 1", (pid, lang))
        out[f"latest_{lang}"] = (config.data_dir() / v["path"]).read_text(encoding="utf-8") if v else ""
    return out


# ---------------------------------------------------------------- SNS

POST_TYPES = ("empathy", "insight", "experience", "contrarian", "other")


def normalize_post(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def create_post(conn, data: dict, actor="human") -> int:
    for k in ("post_type", "hook", "body"):
        if not data.get(k):
            raise ValueError(f"{k} は必須です")
    if data["post_type"] not in POST_TYPES:
        raise ValueError("post_type が不正です")
    if data["post_type"] == "experience" and not data.get("source_note"):
        raise ValueError("体験談・検証型は実在する根拠(source_note)が必須です。無い場合は別形式にしてください")
    pid = data.get("product_id")
    if pid:
        mx = int(st.get(conn, "max_posts_per_product") or 0)
        n = conn.execute("SELECT count(*) FROM sns_posts WHERE product_id=? AND status<>'rejected'",
                         (pid,)).fetchone()[0]
        if mx and n >= mx:
            raise ValueError(f"この商品の投稿案は上限({mx})に達しています")
    h = sha(normalize_post(data["hook"] + " " + data["body"]))
    if row(conn, "SELECT id FROM sns_posts WHERE content_hash=?", (h,)):
        raise ValueError("同じ内容の投稿が既に存在します（重複防止）")
    cur = conn.execute("INSERT INTO sns_posts(product_id,post_type,audience,hook,body,cta,scheduled_at,source_note,"
                       "content_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                       (pid, data["post_type"], data.get("audience"), data["hook"], data["body"], data.get("cta"),
                        data.get("scheduled_at"), data.get("source_note"), h))
    audit(conn, actor, "post.create", {"post_id": cur.lastrowid})
    return cur.lastrowid


def list_posts(conn) -> list[dict]:
    return rows(conn, "SELECT s.*, p.code AS product_code FROM sns_posts s LEFT JOIN products p ON p.id=s.product_id"
                      " ORDER BY CASE s.status WHEN 'draft' THEN 0 WHEN 'approved' THEN 1 WHEN 'scheduled' THEN 2"
                      " ELSE 3 END, coalesce(s.scheduled_at, s.created_at)")


def set_post_status(conn, post_id: int, action: str, scheduled_at: str | None = None, actor="human") -> dict:
    p = row(conn, "SELECT * FROM sns_posts WHERE id=?", (post_id,))
    if not p:
        raise LookupError("post not found")
    rules = {"approve": ({"draft", "rejected"}, "approved"),
             "reject": ({"draft", "approved", "scheduled"}, "rejected"),
             "schedule": ({"approved", "scheduled"}, "scheduled"),
             "unschedule": ({"scheduled"}, "approved"),
             "reopen": ({"rejected", "approved"}, "draft")}
    if action not in rules:
        raise ValueError("invalid action")
    src, dst = rules[action]
    if p["status"] not in src:
        raise ValueError(f"{p['status']} の投稿には {action} できません")
    if action == "schedule" and not scheduled_at:
        raise ValueError("配信予定日時を指定してください")
    conn.execute("UPDATE sns_posts SET status=?, scheduled_at=coalesce(?, scheduled_at), updated_at=datetime('now')"
                 " WHERE id=?", (dst, scheduled_at, post_id))
    audit(conn, actor, f"post.{action}", {"post_id": post_id})
    return row(conn, "SELECT * FROM sns_posts WHERE id=?", (post_id,))


# ---------------------------------------------------------------- 承認

def request_approval(conn, action, target_type, target_id, summary, payload=None) -> int:
    ex = row(conn, "SELECT id FROM approvals WHERE action=? AND target_type=? AND target_id=? AND status='pending'",
             (action, target_type, target_id))
    if ex:
        return ex["id"]
    return conn.execute("INSERT INTO approvals(action,target_type,target_id,summary,payload) VALUES (?,?,?,?,?)",
                        (action, target_type, target_id, summary,
                         json.dumps(payload or {}, ensure_ascii=False))).lastrowid


def decide_approval(conn, aid: int, approve: bool, note: str = "", actor="human") -> dict:
    a = row(conn, "SELECT * FROM approvals WHERE id=?", (aid,))
    if not a or a["status"] != "pending":
        raise ValueError("保留中の承認ではありません")
    conn.execute("UPDATE approvals SET status=?, decided_at=datetime('now'), note=? WHERE id=?",
                 ("approved" if approve else "rejected", note, aid))
    audit(conn, actor, "approval.decide", {"approval_id": aid, "approve": approve})
    result = {"approval_id": aid, "approved": approve}
    if approve and a["action"] == "publish_product":
        # Phase 5 でプラットフォームへの公開ジョブに置き換える。現段階はステータス変更のみ
        result["product"] = transition(conn, a["target_id"], json.loads(a["payload"])["to"],
                                       note=f"承認#{aid}", actor=actor, approved=True)
        conn.execute("UPDATE approvals SET status='executed' WHERE id=?", (aid,))
    return result


# ---------------------------------------------------------------- ダッシュボード

def product_kpis(conn) -> list[dict]:
    """商品別KPI。データが無い指標は None（0で埋めない）。"""
    out = []
    for p in rows(conn, "SELECT id, code, title, status, price_usd, production_minutes, production_cost_jpy"
                        " FROM products ORDER BY id"):
        m = {r["metric"]: r["v"] for r in conn.execute(
            "SELECT metric, sum(value) v FROM metrics_daily WHERE product_id=? GROUP BY metric", (p["id"],))}
        s = row(conn, "SELECT count(*) n, sum(amount_jpy) rev, sum(refunded_jpy) ref, sum(fee_jpy) fee,"
                      " max(data_origin='dummy') dummy FROM sales WHERE product_id=?", (p["id"],))
        c = conn.execute("SELECT sum(amount_jpy) FROM costs WHERE product_id=? AND category='external'",
                         (p["id"],)).fetchone()[0]
        posts = row(conn, "SELECT sum(impressions) imp, sum(link_clicks) clk FROM sns_posts WHERE product_id=?",
                    (p["id"],))
        purchases = s["n"] if s["n"] else None
        pv = m.get("page_views")
        rev = s["rev"]
        cost = (c or 0) + (p["production_cost_jpy"] or 0)
        gp = None if rev is None else rev - (s["ref"] or 0) - (s["fee"] or 0) - cost
        out.append({**p,
                    "page_views": pv,
                    "sns_impressions": posts["imp"] if posts["imp"] is not None else m.get("sns_impressions"),
                    "sns_link_clicks": posts["clk"] if posts["clk"] is not None else m.get("sns_link_clicks"),
                    "purchases": purchases,
                    "conversion": (purchases / pv) if (purchases and pv) else None,
                    "revenue_jpy": rev, "refunds_jpy": s["ref"], "fees_jpy": s["fee"],
                    "ops_cost_jpy": cost or None, "gross_profit_jpy": gp,
                    "feedback_count": conn.execute("SELECT count(*) FROM feedback WHERE product_id=?",
                                                   (p["id"],)).fetchone()[0],
                    "has_dummy": bool(s["dummy"])})
    return out


def dashboard(conn) -> dict:
    count = lambda sql: {r[0]: r[1] for r in conn.execute(sql)}  # noqa: E731
    month = budget.month_key()
    sales = row(conn, "SELECT count(*) n, sum(amount_jpy) rev, sum(refunded_jpy) ref, sum(fee_jpy) fee"
                      " FROM sales WHERE substr(occurred_at,1,7)=?", (month,))
    ext = budget.spent(conn)
    has_sales = bool(sales["n"])
    return {
        "month": month,
        "has_sales_data": has_sales,
        "revenue_jpy": sales["rev"] if has_sales else None,
        "refunds_jpy": sales["ref"] if has_sales else None,
        "fees_jpy": sales["fee"] if has_sales else None,
        "orders": sales["n"] if has_sales else None,
        "external_cost_jpy": ext,
        "gross_profit_jpy": (sales["rev"] - (sales["ref"] or 0) - (sales["fee"] or 0) - ext) if has_sales else None,
        "target_monthly_revenue_jpy": 1_000_000,
        "products_by_status": count("SELECT status, count(*) FROM products GROUP BY status"),
        "themes_by_status": count("SELECT status, count(*) FROM themes GROUP BY status"),
        "posts_by_status": count("SELECT status, count(*) FROM sns_posts GROUP BY status"),
        "jobs_by_status": count("SELECT status, count(*) FROM jobs GROUP BY status"),
        "pending_approvals": conn.execute("SELECT count(*) FROM approvals WHERE status='pending'").fetchone()[0],
        "failed_jobs_24h": conn.execute("SELECT count(*) FROM jobs WHERE status='failed'"
                                        " AND finished_at > datetime('now','-1 day')").fetchone()[0],
        "budget": budget.status(conn),
        "products": product_kpis(conn),
    }
