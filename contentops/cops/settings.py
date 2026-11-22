from __future__ import annotations

import json
import sqlite3

from . import config

# 管理画面から変更できるキー（それ以外は拒否）
EDITABLE = set(config.DEFAULT_SETTINGS) - {"is_demo_db"}


def get(conn: sqlite3.Connection, key: str, default=None):
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else config.DEFAULT_SETTINGS.get(key, default)


def all_settings(conn: sqlite3.Connection) -> dict:
    out = dict(config.DEFAULT_SETTINGS)
    for r in conn.execute("SELECT key, value FROM settings"):
        out[r["key"]] = json.loads(r["value"])
    return out


def update(conn: sqlite3.Connection, values: dict) -> dict:
    bad = [k for k in values if k not in EDITABLE]
    if bad:
        raise ValueError(f"変更できない設定キー: {', '.join(bad)}")
    for k, v in values.items():
        default = config.DEFAULT_SETTINGS[k]
        if isinstance(default, bool) and not isinstance(v, bool):
            raise ValueError(f"{k} は true/false で指定してください")
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                raise ValueError(f"{k} は0以上の数値で指定してください")
        conn.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES (?,?,datetime('now'))"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (k, json.dumps(v)),
        )
    return all_settings(conn)
