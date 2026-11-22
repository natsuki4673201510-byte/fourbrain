import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

TMP = tempfile.mkdtemp()
os.environ["COPS_DATA_DIR"] = TMP

from cops import budget, db, jobs, services as sv  # noqa: E402
from cops import settings as st  # noqa: E402
from cops import handlers  # noqa: E402,F401


def fresh():
    p = Path(TMP) / f"t{os.urandom(4).hex()}.sqlite"
    c = db.connect(p)
    db.init(c)
    return c


def theme(c, name="Budget meal planning for students", **kw):
    return sv.upsert_theme(c, {"name": name, "score_demand": 20, "score_ease": 5, **kw},
                           evidence=[{"url": "https://example.com/a", "retrieved_at": "2026-11-01"}])


class ThemeTests(unittest.TestCase):
    def test_duplicate_theme_updates_instead_of_inserting(self):
        c = fresh()
        a, created1 = theme(c)
        b, created2 = theme(c, score_demand=25)
        self.assertEqual(a, b)
        self.assertTrue(created1)
        self.assertFalse(created2)
        t = sv.theme_detail(c, a)
        self.assertEqual(t["score_total"], 30)
        self.assertEqual(len(t["evidence"]), 1)

    def test_score_bounds_and_evidence_date_required(self):
        c = fresh()
        with self.assertRaises(ValueError):
            sv.upsert_theme(c, {"name": "x", "score_demand": 31})
        with self.assertRaises(ValueError):
            sv.upsert_theme(c, {"name": "y"}, evidence=[{"url": "https://e.com"}])

    def test_approve_creates_one_product_and_one_job(self):
        c = fresh()
        tid, _ = theme(c)
        r1 = sv.set_theme_status(c, tid, "approved")
        r2 = sv.set_theme_status(c, tid, "approved")
        self.assertTrue(r1["created"])
        self.assertFalse(r2["created"])
        self.assertEqual(c.execute("SELECT count(*) FROM products").fetchone()[0], 1)
        self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE type='produce_content'").fetchone()[0], 1)

    def test_production_limit(self):
        c = fresh()
        st.update(c, {"max_products_in_production": 1})
        sv.set_theme_status(c, theme(c, "a")[0], "approved")
        with self.assertRaises(ValueError):
            sv.set_theme_status(c, theme(c, "b")[0], "approved")


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.c = fresh()
        self.pid = sv.set_theme_status(self.c, theme(self.c)[0], "approved")["product_id"]

    def test_publish_requires_approval(self):
        c, pid = self.c, self.pid
        sv.transition(c, pid, "producing")
        sv.transition(c, pid, "awaiting_approval")
        r = sv.transition(c, pid, "on_sale")
        self.assertTrue(r["pending"])
        self.assertEqual(sv.get_product(c, pid)["status"], "awaiting_approval")
        # 同じ依頼は重複しない
        self.assertEqual(sv.transition(c, pid, "on_sale")["approval_id"], r["approval_id"])
        sv.decide_approval(c, r["approval_id"], True)
        self.assertEqual(sv.get_product(c, pid)["status"], "on_sale")

    def test_invalid_transition(self):
        with self.assertRaises(ValueError):
            sv.transition(self.c, self.pid, "on_sale")

    def test_content_versions_dedupe(self):
        a = sv.save_content(self.c, self.pid, "ja", "本文1")
        b = sv.save_content(self.c, self.pid, "ja", "本文1")
        d = sv.save_content(self.c, self.pid, "ja", "本文2")
        self.assertTrue(b["duplicate"])
        self.assertEqual((a["version"], d["version"]), (1, 2))
        self.assertEqual(sv.content_bundle(self.c, self.pid)["latest_ja"], "本文2")


class PostTests(unittest.TestCase):
    def test_duplicate_and_experience_rules(self):
        c = fresh()
        sv.create_post(c, {"post_type": "insight", "hook": "Most budgets fail", "body": "Here's why."})
        with self.assertRaises(ValueError):  # 句読点・大小文字違いでも重複扱い
            sv.create_post(c, {"post_type": "insight", "hook": "most budgets FAIL!", "body": "Here's why"})
        with self.assertRaises(ValueError):
            sv.create_post(c, {"post_type": "experience", "hook": "I tried", "body": "it worked"})

    def test_only_approved_can_be_scheduled(self):
        c = fresh()
        pid = sv.create_post(c, {"post_type": "empathy", "hook": "h", "body": "b"})
        with self.assertRaises(ValueError):
            sv.set_post_status(c, pid, "schedule", "2026-12-01 09:00")
        sv.set_post_status(c, pid, "approve")
        self.assertEqual(sv.set_post_status(c, pid, "schedule", "2026-12-01 09:00")["status"], "scheduled")


class JobTests(unittest.TestCase):
    def test_idempotent_enqueue(self):
        c = fresh()
        a = jobs.enqueue(c, "healthcheck", {"x": 1})
        b = jobs.enqueue(c, "healthcheck", {"x": 1})
        self.assertEqual(a[0], b[0])
        self.assertFalse(b[1])
        with self.assertRaises(ValueError):
            jobs.enqueue(c, "unknown_type")

    def test_retry_is_capped(self):
        c = fresh()
        calls = []

        @jobs.handler("competitor_analysis")
        def boom(ctx):
            calls.append(1)
            raise RuntimeError("upstream 500")
        try:
            jid, _ = jobs.enqueue(c, "competitor_analysis", {}, max_attempts=2)
            jobs.run_once(c)
            c.execute("UPDATE jobs SET next_run_at=datetime('now') WHERE id=?", (jid,))
            jobs.run_once(c)
            c.execute("UPDATE jobs SET next_run_at=datetime('now') WHERE id=?", (jid,))
            jobs.run_once(c)
            j = db.row(c, "SELECT * FROM jobs WHERE id=?", (jid,))
            self.assertEqual(j["status"], "failed")
            self.assertEqual(len(calls), 2)
            self.assertTrue(db.rows(c, "SELECT * FROM job_logs WHERE job_id=? AND level='error'", (jid,)))
        finally:
            jobs.HANDLERS.pop("competitor_analysis")

    def test_checkpoint_resume(self):
        c = fresh()
        seen = []

        @jobs.handler("theme_scoring")
        def step(ctx):
            seen.append(dict(ctx.checkpoint))
            if not ctx.checkpoint:
                ctx.save_checkpoint({"done": 15})
                raise RuntimeError("interrupted")
            return {"resumed_from": ctx.checkpoint["done"]}
        try:
            jid, _ = jobs.enqueue(c, "theme_scoring", {})
            jobs.run_once(c)
            c.execute("UPDATE jobs SET next_run_at=datetime('now') WHERE id=?", (jid,))
            r = jobs.run_once(c)
            self.assertEqual(r[0]["result"], {"resumed_from": 15})
        finally:
            jobs.HANDLERS.pop("theme_scoring")

    def test_unimplemented_job_is_blocked_not_failed(self):
        c = fresh()
        jid, _ = jobs.enqueue(c, "render_pdf", {"p": 1})
        jobs.run_once(c)
        j = db.row(c, "SELECT * FROM jobs WHERE id=?", (jid,))
        self.assertEqual((j["status"], j["blocked_reason"], j["attempts"]), ("blocked", "no_handler", 0))

    def test_budget_blocks_job(self):
        c = fresh()
        st.update(c, {"monthly_budget_jpy": 100})
        budget.record(c, "anthropic_api", 90)

        @jobs.handler("suggest_related", estimate_jpy=lambda p: 20)
        def costly(ctx):
            return {}
        try:
            jid, _ = jobs.enqueue(c, "suggest_related", {})
            jobs.run_once(c)
            j = db.row(c, "SELECT * FROM jobs WHERE id=?", (jid,))
            self.assertEqual((j["status"], j["blocked_reason"]), ("blocked", "budget"))
            # Claude契約費は上限計算の対象外
            budget.record(c, "claude", 3000, category="claude_plan")
            self.assertEqual(budget.status(c)["spent_jpy"], 90)
        finally:
            jobs.HANDLERS.pop("suggest_related")

    def test_daily_limit(self):
        c = fresh()
        st.update(c, {"max_jobs_per_day": 1})
        jobs.enqueue(c, "healthcheck", {"n": 1})
        jobs.enqueue(c, "healthcheck", {"n": 2})
        r = jobs.run_once(c)
        self.assertEqual([x["status"] for x in r], ["succeeded", "blocked"])

    def test_anomaly_and_backup(self):
        c = fresh()
        jobs.enqueue(c, "anomaly_check", {})
        jobs.enqueue(c, "backup", {})
        r = jobs.run_once(c)
        self.assertTrue(all(x["status"] == "succeeded" for x in r))
        self.assertTrue(list((Path(TMP) / "backups").glob("*.zip")))


class DashboardTests(unittest.TestCase):
    def test_missing_metrics_are_none_not_zero(self):
        c = fresh()
        sv.set_theme_status(c, theme(c)[0], "approved")
        d = sv.dashboard(c)
        self.assertIsNone(d["revenue_jpy"])
        p = d["products"][0]
        self.assertIsNone(p["page_views"])
        self.assertIsNone(p["conversion"])

    def test_settings_validation(self):
        c = fresh()
        with self.assertRaises(ValueError):
            st.update(c, {"monthly_budget_jpy": -1})
        with self.assertRaises(ValueError):
            st.update(c, {"is_demo_db": True})


class DemoIsolationTests(unittest.TestCase):
    def test_demo_seed_does_not_touch_production(self):
        from cops import config, demo
        prod = db.connect(config.db_path())
        db.init(prod)
        before = prod.execute("SELECT count(*) FROM themes").fetchone()[0]
        demo.seed()
        self.assertEqual(prod.execute("SELECT count(*) FROM themes").fetchone()[0], before)
        d = db.connect(config.db_path(demo=True))
        self.assertTrue(db.is_demo(d))
        self.assertFalse(db.is_demo(prod))
        self.assertEqual(d.execute("SELECT count(*) FROM themes WHERE data_origin<>'dummy'").fetchone()[0], 0)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cops import server
        p = Path(TMP) / "srv.sqlite"
        c = db.connect(p)
        db.init(c)
        c.close()
        server.App.db_file = p
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.App)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def req(self, path, body=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        r = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                   headers=h, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_csrf_header_required(self):
        code, _ = self.req("/api/themes", {"name": "x"})
        self.assertEqual(code, 403)
        code, r = self.req("/api/themes", {"name": "Server theme"}, {"X-COPS": "1"})
        self.assertEqual(code, 200)
        self.assertTrue(r["created"])

    def test_pages_and_secrets_not_leaked(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-SECRET"
        code, m = self.req("/api/meta")
        self.assertEqual(code, 200)
        self.assertNotIn("sk-test-SECRET", json.dumps(m))
        self.assertTrue(m["secrets"]["ANTHROPIC_API_KEY"])
        for p in ("/api/dashboard", "/api/themes", "/api/products", "/api/posts", "/api/settings",
                  "/api/jobs", "/api/costs", "/api/recommendations", "/api/approvals", "/api/audit"):
            self.assertEqual(self.req(p)[0], 200, p)
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn(b"ContentOps", r.read())

    def test_path_traversal_blocked(self):
        import http.client
        for path in ("/files/../srv.sqlite", "/files/products/../../srv.sqlite", "/../cops/config.py"):
            h = http.client.HTTPConnection(*self.httpd.server_address)
            h.request("GET", path)
            resp = h.getresponse()
            body = resp.read()
            self.assertNotIn(b"SQLite format", body, path)
            self.assertNotIn(b"SECRET_KEYS", body, path)
            h.close()

    def test_foreign_host_rejected(self):
        code, _ = self.req("/api/meta", headers={"Host": "evil.example.com"})
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()
