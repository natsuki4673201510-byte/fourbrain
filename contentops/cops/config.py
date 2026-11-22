"""設定・パス・秘密情報の読み込み。

秘密情報は環境変数または contentops/.env からのみ読む（ソースコードに埋め込まない）。
値そのものは管理画面やログに出さず、「設定済みかどうか」だけを返す。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # contentops/

SECRET_KEYS = [
    "ANTHROPIC_API_KEY",
    "X_CLIENT_ID", "X_CLIENT_SECRET", "X_ACCESS_TOKEN", "X_REFRESH_TOKEN",
    "GUMROAD_ACCESS_TOKEN", "LEMONSQUEEZY_API_KEY", "PAYHIP_API_KEY",
]


def load_dotenv(path: Path | None = None) -> None:
    """最小限の .env ローダー（既存の環境変数は上書きしない）。"""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def data_dir() -> Path:
    d = Path(os.environ.get("COPS_DATA_DIR") or ROOT / "data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path(demo: bool = False) -> Path:
    # ダミーデータは別ファイルに隔離し、本番DBに混入させない
    return data_dir() / ("demo.sqlite" if demo else "contentops.sqlite")


def port() -> int:
    return int(os.environ.get("COPS_PORT", "8765"))


def secret_status() -> dict[str, bool]:
    return {k: bool(os.environ.get(k)) for k in SECRET_KEYS}


DEFAULT_SETTINGS: dict[str, object] = {
    # 費用上限（外部サービス・API。Claude本体の契約費は別枠）
    "monthly_budget_jpy": 2000,
    "budget_warn_ratio": 0.8,
    "claude_plan_monthly_jpy": None,      # Claude契約費（記録用・上限計算の対象外）
    "usd_jpy_rate": 150,                  # 換算レート（手動更新）
    # 生成量の上限（無制限な自動生成の防止）
    "max_jobs_per_day": 30,
    "max_products_in_production": 3,
    "max_posts_per_product": 10,
    "max_themes_per_research_run": 30,
    # 定期実行
    "schedule_daily_enabled": False,
    "schedule_weekly_enabled": False,
    "schedule_daily_time": "07:10",
    "schedule_weekly_day": "mon",
    # 実行エンジン
    "llm_engine": "claude_code_cli",      # claude_code_cli / anthropic_api / manual
    "claude_cli_path": "claude",
    "anthropic_model": "claude-sonnet-5-5",
    # SNS
    "sns_auto_publish": False,            # 初期は承認済み投稿のみ・手動公開
    "sns_max_posts_per_day": 3,
    # 販売
    "sales_platform": None,               # 調査後に決定
    # バックアップ
    "backup_keep": 14,
}
