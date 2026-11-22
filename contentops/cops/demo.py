"""デモ用ダミーデータ。必ず demo.sqlite にのみ書き込み、全行 data_origin='dummy' とする。
テーマ名・数値はすべて架空であり、市場調査結果ではない。"""
from __future__ import annotations

from . import config, db, services as sv


def seed():
    path = config.db_path(demo=True)
    if path == config.db_path(demo=False):
        raise RuntimeError("デモDBと本番DBが同一パスです")
    for p in (path, path.with_suffix(".sqlite-wal"), path.with_suffix(".sqlite-shm")):
        p.unlink(missing_ok=True)
    c = db.connect(path)
    db.init(c, is_demo=True)
    for i, (name, scores) in enumerate([
        ("[DEMO] Sample theme A", (20, 15, 14, 10, 8)),
        ("[DEMO] Sample theme B", (15, 12, 10, 8, 6)),
        ("[DEMO] Sample theme C", (10, 8, 9, 5, 7)),
    ]):
        sv.upsert_theme(c, {"name": name, "target_buyer": "(dummy)", "pain_point": "(dummy)", "price_usd": 9 + i * 5,
                            "score_demand": scores[0], "score_differentiation": scores[1],
                            "score_motivation": scores[2], "score_recurring": scores[3], "score_ease": scores[4],
                            "data_origin": "dummy"},
                        evidence=[{"url": f"https://example.com/demo-{i}", "retrieved_at": "2026-01-01",
                                   "title": "dummy evidence"}])
    r = sv.set_theme_status(c, 1, "approved", actor="demo")
    pid = r["product_id"]
    sv.save_content(c, pid, "ja", "# デモ原稿\n\nこれはダミーの原稿です。", author="ai")
    sv.save_content(c, pid, "en", "# Demo manuscript\n\nThis is dummy text.", author="ai")
    sv.create_post(c, {"product_id": pid, "post_type": "empathy", "audience": "(dummy)",
                       "hook": "[DEMO] hook", "body": "Dummy post body.", "cta": "Link in bio"}, actor="demo")
    c.execute("INSERT INTO sales(platform,order_id,product_id,amount,currency,amount_jpy,fee_jpy,occurred_at,"
              "data_origin) VALUES ('demo','D-1',?,9,'USD',1350,180,datetime('now'),'dummy')", (pid,))
    c.execute("INSERT INTO metrics_daily(product_id,date,metric,value,source,data_origin)"
              " VALUES (?,date('now'),'page_views',40,'demo','dummy')", (pid,))
    c.close()
    return path
