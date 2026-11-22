"""SQLite 接続・初期化・バックアップ。"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from . import config

SCHEMA_VERSION = 1


def connect(path: Path | str | None = None, demo: bool = False) -> sqlite3.Connection:
    path = Path(path) if path else config.db_path(demo)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)  # autocommit; 明示的にトランザクションを張る
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init(conn: sqlite3.Connection, is_demo: bool = False) -> None:
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    if not conn.execute("SELECT 1 FROM schema_version").fetchone():
        conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    for k, v in config.DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, json.dumps(v)))
    conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('is_demo_db', ?)", (json.dumps(is_demo),))


def is_demo(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM settings WHERE key='is_demo_db'").fetchone()
    return bool(row and json.loads(row["value"]))


def rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


class tx:
    """with tx(conn): ... で BEGIN IMMEDIATE / COMMIT / ROLLBACK"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, *_):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def backup(conn: sqlite3.Connection, keep: int = 14) -> Path:
    """DBのオンラインバックアップ + 原稿ファイルを zip 化。古いものは keep 件を残して削除。"""
    ddir = config.data_dir()
    bdir = ddir / "backups"
    bdir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp_db = bdir / f"db-{stamp}.sqlite"
    dest = sqlite3.connect(tmp_db)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    out = bdir / f"contentops-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_db, "contentops.sqlite")
        content = ddir / "products"
        if content.exists():
            for f in content.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(ddir).as_posix())
    tmp_db.unlink()
    olds = sorted(bdir.glob("contentops-*.zip"))
    for f in olds[:-keep] if keep > 0 else []:
        f.unlink()
    return out
