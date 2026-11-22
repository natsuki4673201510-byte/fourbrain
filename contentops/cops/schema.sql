-- ContentOps schema (SQLite)
-- 方針:
--  * data_origin で「実データ(real)」「AI推測(ai_estimate)」「手入力(manual)」「ダミー(dummy)」を必ず区別する
--  * 取得できない指標は NULL（0 で埋めない）
--  * 重複防止は UNIQUE 制約（slug / content_hash / idempotency_key / order_id）で DB レベルで保証する

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,              -- JSON
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===== 市場調査 =====
CREATE TABLE IF NOT EXISTS research_runs (
  id           INTEGER PRIMARY KEY,
  started_at   TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at  TEXT,
  status       TEXT NOT NULL DEFAULT 'running',  -- running/succeeded/failed
  scope        TEXT,                              -- 調査範囲メモ
  job_id       INTEGER REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS themes (
  id                    INTEGER PRIMARY KEY,
  slug                  TEXT NOT NULL UNIQUE,     -- 重複テーマ防止キー
  name                  TEXT NOT NULL,
  target_buyer          TEXT,
  pain_point            TEXT,
  demand_evidence       TEXT,                     -- 根拠の要約（URLは evidence テーブル）
  similar_products      TEXT,
  unmet_needs           TEXT,
  differentiation       TEXT,
  price_usd             REAL,
  production_cost_jpy   REAL,
  recurring_demand      TEXT,
  score_demand          REAL CHECK (score_demand BETWEEN 0 AND 30),
  score_differentiation REAL CHECK (score_differentiation BETWEEN 0 AND 25),
  score_motivation      REAL CHECK (score_motivation BETWEEN 0 AND 20),
  score_recurring       REAL CHECK (score_recurring BETWEEN 0 AND 15),
  score_ease            REAL CHECK (score_ease BETWEEN 0 AND 10),
  score_total           REAL GENERATED ALWAYS AS (
                          coalesce(score_demand,0)+coalesce(score_differentiation,0)+
                          coalesce(score_motivation,0)+coalesce(score_recurring,0)+
                          coalesce(score_ease,0)) STORED,
  score_rationale       TEXT,
  status                TEXT NOT NULL DEFAULT 'discovered'
                        CHECK (status IN ('discovered','shortlisted','approved','rejected','archived')),
  data_origin           TEXT NOT NULL DEFAULT 'ai_estimate'
                        CHECK (data_origin IN ('real','ai_estimate','manual','dummy')),
  research_run_id       INTEGER REFERENCES research_runs(id),
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 根拠URLと取得日（テーマ・競合の主張はここに紐づける）
CREATE TABLE IF NOT EXISTS evidence (
  id           INTEGER PRIMARY KEY,
  theme_id     INTEGER NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
  url          TEXT NOT NULL,
  title        TEXT,
  source_type  TEXT,           -- google/reddit/marketplace/forum/other
  metric_name  TEXT,           -- 代替指標名（例: reddit_upvotes, search_results_count）
  metric_value REAL,           -- 取得できた値のみ。推測値は入れない
  excerpt      TEXT,
  retrieved_at TEXT NOT NULL,  -- 取得日 (YYYY-MM-DD)
  UNIQUE (theme_id, url)
);

CREATE TABLE IF NOT EXISTS competitors (
  id           INTEGER PRIMARY KEY,
  theme_id     INTEGER NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  url          TEXT,
  platform     TEXT,
  price        REAL,
  currency     TEXT,
  sales_signal TEXT,           -- 公開されている場合のみ（例: "1.2k ratings"）。推測禁止
  weaknesses   TEXT,
  retrieved_at TEXT,
  UNIQUE (theme_id, url)
);

-- ===== 商品 =====
CREATE TABLE IF NOT EXISTS products (
  id                  INTEGER PRIMARY KEY,
  code                TEXT NOT NULL UNIQUE,     -- 商品ID (例: P0001)
  theme_id            INTEGER UNIQUE REFERENCES themes(id),  -- 1テーマ=1商品（重複生成防止）
  title               TEXT NOT NULL,
  subtitle            TEXT,
  status              TEXT NOT NULL DEFAULT 'planning'
                      CHECK (status IN ('planning','producing','awaiting_approval','on_sale','paused','stopped')),
  structure           TEXT,                     -- テーマに応じて選んだ構成（JSON）
  price_usd           REAL,
  platform            TEXT,
  platform_product_id TEXT,
  product_url         TEXT,
  production_minutes  REAL,                     -- 人間の作業時間（制作時間）
  production_cost_jpy REAL,                     -- API等の制作コスト（costs から集計も可）
  launched_at         TEXT,
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS product_status_history (
  id         INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  from_status TEXT,
  to_status  TEXT NOT NULL,
  note       TEXT,
  changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 原稿・PDFのバージョン（上書きせず追記）
CREATE TABLE IF NOT EXISTS content_versions (
  id           INTEGER PRIMARY KEY,
  product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  lang         TEXT NOT NULL CHECK (lang IN ('ja','en')),
  kind         TEXT NOT NULL CHECK (kind IN ('manuscript','pdf','sales_page')),
  version      INTEGER NOT NULL,
  path         TEXT NOT NULL,                 -- data_dir からの相対パス
  content_hash TEXT NOT NULL,
  char_count   INTEGER,
  author       TEXT NOT NULL DEFAULT 'ai',    -- ai/human
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (product_id, lang, kind, version),
  UNIQUE (product_id, lang, kind, content_hash)  -- 同一内容の重複保存を防止
);

CREATE TABLE IF NOT EXISTS qa_checks (
  id          INTEGER PRIMARY KEY,
  product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  version_id  INTEGER REFERENCES content_versions(id),
  check_name  TEXT NOT NULL,   -- accuracy/sources/english/culture/differentiation/redundancy/examples/copyright/description_match
  result      TEXT NOT NULL CHECK (result IN ('pass','warn','fail','skipped')),
  notes       TEXT,
  checked_by  TEXT NOT NULL DEFAULT 'ai',
  checked_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===== SNS =====
CREATE TABLE IF NOT EXISTS sns_posts (
  id             INTEGER PRIMARY KEY,
  product_id     INTEGER REFERENCES products(id) ON DELETE SET NULL,
  channel        TEXT NOT NULL DEFAULT 'x',
  post_type      TEXT NOT NULL CHECK (post_type IN ('empathy','insight','experience','contrarian','other')),
  audience       TEXT,           -- 訴求対象
  hook           TEXT NOT NULL,  -- 冒頭フック
  body           TEXT NOT NULL,
  cta            TEXT,           -- 購入導線
  scheduled_at   TEXT,
  status         TEXT NOT NULL DEFAULT 'draft'
                 CHECK (status IN ('draft','approved','scheduled','posted','rejected','failed')),
  source_note    TEXT,           -- 体験談・検証型の場合、実在する根拠（必須）
  content_hash   TEXT NOT NULL UNIQUE,  -- 正規化本文のハッシュ（重複投稿防止）
  external_id    TEXT,
  posted_at      TEXT,
  impressions    INTEGER,
  link_clicks    INTEGER,
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK (post_type <> 'experience' OR (source_note IS NOT NULL AND length(source_note) > 0))
);

-- ===== 販売・指標 =====
CREATE TABLE IF NOT EXISTS bundles (
  id         INTEGER PRIMARY KEY,
  code       TEXT NOT NULL UNIQUE,
  title      TEXT NOT NULL,
  price_usd  REAL,
  status     TEXT NOT NULL DEFAULT 'planning'
             CHECK (status IN ('planning','awaiting_approval','on_sale','stopped')),
  rationale  TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS bundle_items (
  bundle_id  INTEGER NOT NULL REFERENCES bundles(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id),
  PRIMARY KEY (bundle_id, product_id)
);

CREATE TABLE IF NOT EXISTS sales (
  id            INTEGER PRIMARY KEY,
  platform      TEXT NOT NULL,
  order_id      TEXT NOT NULL,
  product_id    INTEGER REFERENCES products(id),
  bundle_id     INTEGER REFERENCES bundles(id),
  amount        REAL NOT NULL,
  currency      TEXT NOT NULL,
  amount_jpy    REAL,
  fee_jpy       REAL,
  refunded_jpy  REAL NOT NULL DEFAULT 0,
  occurred_at   TEXT NOT NULL,
  data_origin   TEXT NOT NULL DEFAULT 'real' CHECK (data_origin IN ('real','manual','dummy')),
  UNIQUE (platform, order_id)
);

-- 日次指標（取得できたものだけ行を作る。無い指標は行が無い＝欠損）
CREATE TABLE IF NOT EXISTS metrics_daily (
  id          INTEGER PRIMARY KEY,
  product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  date        TEXT NOT NULL,
  metric      TEXT NOT NULL,   -- page_views/sns_impressions/sns_link_clicks/...
  value       REAL NOT NULL,
  source      TEXT NOT NULL,   -- platform名 / x_api / manual
  data_origin TEXT NOT NULL DEFAULT 'real' CHECK (data_origin IN ('real','manual','dummy')),
  UNIQUE (product_id, date, metric, source)
);

CREATE TABLE IF NOT EXISTS feedback (
  id          INTEGER PRIMARY KEY,
  product_id  INTEGER REFERENCES products(id) ON DELETE CASCADE,
  source      TEXT,
  body        TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT (datetime('now')),
  data_origin TEXT NOT NULL DEFAULT 'real' CHECK (data_origin IN ('real','manual','dummy'))
);

-- ===== 改善提案 =====
CREATE TABLE IF NOT EXISTS recommendations (
  id          INTEGER PRIMARY KEY,
  week        TEXT NOT NULL,     -- ISO週 (2026-W47)
  product_id  INTEGER REFERENCES products(id) ON DELETE CASCADE,
  decision    TEXT NOT NULL CHECK (decision IN ('continue','improve_page','price_test','make_related','stop','collect_data','other')),
  rationale   TEXT NOT NULL,
  next_action TEXT,
  data_origin TEXT NOT NULL DEFAULT 'ai_estimate',
  status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','accepted','dismissed','done')),
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (week, product_id, decision)
);

-- ===== 費用管理 =====
CREATE TABLE IF NOT EXISTS costs (
  id          INTEGER PRIMARY KEY,
  occurred_at TEXT NOT NULL DEFAULT (datetime('now')),
  service     TEXT NOT NULL,     -- anthropic_api / x_api / hosting / domain ...
  category    TEXT NOT NULL DEFAULT 'external' CHECK (category IN ('external','claude_plan','platform_fee')),
  amount_jpy  REAL NOT NULL,
  is_estimate INTEGER NOT NULL DEFAULT 0,
  description TEXT,
  job_id      INTEGER REFERENCES jobs(id),
  product_id  INTEGER REFERENCES products(id)
);

-- ===== ジョブ（重複防止・再開・リトライ上限） =====
CREATE TABLE IF NOT EXISTS jobs (
  id                 INTEGER PRIMARY KEY,
  type               TEXT NOT NULL,
  idempotency_key    TEXT NOT NULL UNIQUE,
  payload            TEXT NOT NULL DEFAULT '{}',
  status             TEXT NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued','running','succeeded','failed','cancelled','blocked')),
  attempts           INTEGER NOT NULL DEFAULT 0,
  max_attempts       INTEGER NOT NULL DEFAULT 2,
  next_run_at        TEXT NOT NULL DEFAULT (datetime('now')),
  checkpoint         TEXT,          -- 途中再開用 JSON
  result             TEXT,
  last_error         TEXT,
  blocked_reason     TEXT,          -- budget / approval / no_handler
  estimated_cost_jpy REAL NOT NULL DEFAULT 0,
  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  started_at         TEXT,
  finished_at        TEXT,
  updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, next_run_at);

CREATE TABLE IF NOT EXISTS job_logs (
  id      INTEGER PRIMARY KEY,
  job_id  INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
  ts      TEXT NOT NULL DEFAULT (datetime('now')),
  level   TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL
);

-- ===== 承認（外部公開・課金・投稿・破壊的変更） =====
CREATE TABLE IF NOT EXISTS approvals (
  id           INTEGER PRIMARY KEY,
  action       TEXT NOT NULL,    -- publish_product / post_sns / spend_over_budget / delete_data ...
  target_type  TEXT NOT NULL,
  target_id    INTEGER NOT NULL,
  summary      TEXT NOT NULL,
  payload      TEXT NOT NULL DEFAULT '{}',
  status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','executed')),
  requested_at TEXT NOT NULL DEFAULT (datetime('now')),
  decided_at   TEXT,
  note         TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_approvals_pending
  ON approvals(action, target_type, target_id) WHERE status = 'pending';

-- 監査ログ（誰がいつ何をしたか）
CREATE TABLE IF NOT EXISTS audit_log (
  id     INTEGER PRIMARY KEY,
  ts     TEXT NOT NULL DEFAULT (datetime('now')),
  actor  TEXT NOT NULL,          -- human / system / agent:<name>
  action TEXT NOT NULL,
  detail TEXT
);
