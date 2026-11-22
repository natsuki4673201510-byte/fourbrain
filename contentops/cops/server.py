"""管理画面用のローカルHTTPサーバー（標準ライブラリのみ）。

セキュリティ:
- 127.0.0.1 にのみバインド（LAN・外部からアクセス不可）
- Host ヘッダを検査（DNS リバインディング対策）
- 更新系リクエストはカスタムヘッダ X-COPS 必須（他サイトからのCSRF対策）
- 秘密情報の値は返さない（設定済みかどうかのみ）
"""
from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import budget, config, db, jobs, services as sv
from . import settings as st
from . import handlers  # noqa: F401  ハンドラ登録

WEB = config.ROOT / "web"
ROUTES: list[tuple[str, re.Pattern, callable]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return deco


# ------------------------------------------------------------------ API

@route("GET", "/api/meta")
def meta(c, q, b):
    return {"is_demo": db.is_demo(c), "db_path": str(App.db_file), "secrets": config.secret_status(),
            "job_types": jobs.JOB_TYPES, "implemented_jobs": sorted(jobs.HANDLERS)}


@route("GET", "/api/dashboard")
def dashboard(c, q, b):
    return sv.dashboard(c)


@route("GET", "/api/themes")
def themes(c, q, b):
    return sv.list_themes(c)


@route("POST", "/api/themes")
def theme_create(c, q, b):
    data = {**b, "data_origin": b.get("data_origin") or "manual"}
    tid, created = sv.upsert_theme(c, data, b.get("evidence"), b.get("competitors"))
    return {"id": tid, "created": created}


@route("GET", r"/api/themes/(\d+)")
def theme_get(c, q, b, tid):
    return sv.theme_detail(c, int(tid))


@route("POST", r"/api/themes/(\d+)/status")
def theme_status(c, q, b, tid):
    return sv.set_theme_status(c, int(tid), b["status"])


@route("GET", "/api/products")
def products(c, q, b):
    return sv.list_products(c)


@route("POST", r"/api/products/(\d+)")
def product_update(c, q, b, pid):
    return sv.update_product(c, int(pid), b)


@route("POST", r"/api/products/(\d+)/transition")
def product_transition(c, q, b, pid):
    return sv.transition(c, int(pid), b["to"], b.get("note", ""))


@route("GET", r"/api/products/(\d+)/content")
def content(c, q, b, pid):
    return sv.content_bundle(c, int(pid))


@route("POST", r"/api/products/(\d+)/content/(ja|en)")
def content_save(c, q, b, pid, lang):
    return sv.save_content(c, int(pid), lang, b["text"], author="human")


@route("GET", "/api/posts")
def posts(c, q, b):
    return sv.list_posts(c)


@route("POST", "/api/posts")
def post_create(c, q, b):
    return {"id": sv.create_post(c, b)}


@route("POST", r"/api/posts/(\d+)/(approve|reject|schedule|unschedule|reopen)")
def post_action(c, q, b, post_id, action):
    return sv.set_post_status(c, int(post_id), action, b.get("scheduled_at"))


@route("GET", "/api/recommendations")
def recs(c, q, b):
    return db.rows(c, "SELECT r.*, p.code product_code FROM recommendations r LEFT JOIN products p"
                      " ON p.id=r.product_id ORDER BY week DESC, id")


@route("GET", "/api/approvals")
def approvals(c, q, b):
    return db.rows(c, "SELECT * FROM approvals ORDER BY status='pending' DESC, id DESC LIMIT 200")


@route("POST", r"/api/approvals/(\d+)")
def approval_decide(c, q, b, aid):
    return sv.decide_approval(c, int(aid), bool(b.get("approve")), b.get("note", ""))


@route("GET", "/api/settings")
def settings_get(c, q, b):
    return {"settings": st.all_settings(c), "secrets": config.secret_status(), "budget": budget.status(c)}


@route("POST", "/api/settings")
def settings_put(c, q, b):
    out = st.update(c, b)
    sv.audit(c, "human", "settings.update", b)
    return out


@route("GET", "/api/costs")
def costs(c, q, b):
    return db.rows(c, "SELECT * FROM costs ORDER BY occurred_at DESC LIMIT 200")


@route("POST", "/api/costs")
def cost_add(c, q, b):
    amount = float(b["amount_jpy"])
    if amount < 0:
        raise ValueError("金額は0以上")
    return {"id": budget.record(c, b["service"], amount, category=b.get("category", "external"),
                                description=b.get("description", ""))}


@route("GET", "/api/jobs")
def jobs_list(c, q, b):
    return db.rows(c, "SELECT id,type,idempotency_key,status,attempts,max_attempts,blocked_reason,last_error,"
                      "estimated_cost_jpy,created_at,started_at,finished_at,next_run_at FROM jobs"
                      " ORDER BY id DESC LIMIT 200")


@route("POST", "/api/jobs")
def jobs_create(c, q, b):
    jid, created = jobs.enqueue(c, b["type"], b.get("payload") or {}, key=b.get("key"))
    return {"id": jid, "created": created}


@route("POST", "/api/jobs/run")
def jobs_run(c, q, b):
    return jobs.run_once(c, limit=int(b.get("limit", 5)))


@route("POST", r"/api/jobs/(\d+)/(retry|cancel)")
def job_action(c, q, b, jid, action):
    getattr(jobs, action)(c, int(jid))
    return {"ok": True}


@route("GET", r"/api/jobs/(\d+)/logs")
def job_logs(c, q, b, jid):
    return db.rows(c, "SELECT * FROM job_logs WHERE job_id=? ORDER BY id", (int(jid),))


@route("GET", "/api/audit")
def audit(c, q, b):
    return db.rows(c, "SELECT * FROM audit_log ORDER BY id DESC LIMIT 200")


@route("POST", "/api/backup")
def backup(c, q, b):
    p = db.backup(c, keep=int(st.get(c, "backup_keep") or 14))
    return {"file": p.name}


# ------------------------------------------------------------------ HTTP

class App(BaseHTTPRequestHandler):
    db_file: Path = config.db_path()
    server_version = "ContentOps/0.1"

    def log_message(self, fmt, *args):  # 静かにする（エラーはjob_logs/標準エラーへ）
        pass

    def _send(self, status: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method: str):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self._static(url.path) if method == "GET" else self._json(405, {"error": "method"})
        if method != "GET" and self.headers.get("X-COPS") != "1":
            return self._json(403, {"error": "missing X-COPS header"})
        body = {}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            if n > 5_000_000:
                return self._json(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "invalid json"})
        for m, pat, fn in ROUTES:
            mt = pat.match(url.path)
            if m == method and mt:
                conn = db.connect(self.db_file)
                try:
                    return self._json(200, fn(conn, parse_qs(url.query), body, *mt.groups()))
                except (ValueError, KeyError) as e:
                    return self._json(400, {"error": str(e)})
                except LookupError as e:
                    return self._json(404, {"error": str(e)})
                except sqlite3.IntegrityError as e:
                    return self._json(409, {"error": f"整合性エラー（重複など）: {e}"})
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    return self._json(500, {"error": f"{type(e).__name__}: {e}"})
                finally:
                    conn.close()
        self._json(404, {"error": "not found"})

    def _static(self, path: str):
        if path.startswith("/files/"):
            base = (config.data_dir() / "products").resolve()
            f = (config.data_dir() / path[len("/files/"):]).resolve()
            if base not in f.parents or not f.is_file():
                return self._json(404, {"error": "not found"})
        else:
            f = (WEB / (path.lstrip("/") or "index.html")).resolve()
            if WEB.resolve() not in f.parents or not f.is_file():
                f = WEB / "index.html"
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype)


def serve(db_file: Path, port: int) -> None:
    App.db_file = db_file
    httpd = ThreadingHTTPServer(("127.0.0.1", port), App)
    print(f"ContentOps 管理画面: http://127.0.0.1:{port}  (DB: {db_file})  Ctrl+C で停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
