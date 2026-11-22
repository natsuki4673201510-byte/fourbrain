# ContentOps — 海外デジタルコンテンツ販売 自動化システム

英語圏向け有料デジタルコンテンツの「市場調査 → 商品企画 → 制作 → 販売準備 → SNS集客 → 分析・改善」をローカル中心に自動化するシステムです。
設計・費用見積もりは [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) を参照してください。

> 月100万円は事業目標であり、本システムは達成を保証しません。売上データが無い段階では仮の実績を作らず、検証に必要なデータと次の実験を提示します。

## 必要なもの
- macOS（Linux でも可）
- Python 3.9 以上（`python3 --version` で確認。追加パッケージ不要）
- Phase 2 以降: [Claude Code](https://code.claude.com) CLI（`claude` コマンド）

## セットアップ
```bash
cd contentops
cp .env.example .env      # 必要になったら値を入れる（git 管理外）
chmod 600 .env
python3 -m cops init      # 本番DBを作成（data/contentops.sqlite）
python3 -m cops serve     # http://127.0.0.1:8765 を開く
```

### 画面を試すだけの場合（ダミーデータ）
```bash
python3 -m cops seed-demo
python3 -m cops --demo serve
```
デモDB（`data/demo.sqlite`）は本番DBとは別ファイルです。画面上部に「デモDB表示中」と表示されます。

## 管理画面
| 画面 | できること |
|---|---|
| ダッシュボード | 今月の売上・粗利益・注文数・費用上限の消化率、承認待ち操作の承認/却下、商品別KPI（未取得の指標は「未取得」と表示） |
| 市場調査 | テーマ一覧（100点スコアと内訳・根拠URL・競合）、候補/承認/却下、手動追加、「市場調査を開始」 |
| 商品管理 | 企画中 → 制作中 → 承認待ち → 販売中 のかんばん。**販売中への変更は承認が必要** |
| コンテンツ編集 | 日本語/英語原稿の編集（保存ごとに新バージョン）、PDF、品質検証結果、履歴 |
| SNS管理 | X投稿案の追加・承認・却下・予約。承認済みのみ配信対象 |
| 改善提案 | 週次の判断（継続/ページ改善/価格テスト/関連商品/停止）と根拠 |
| システム設定 | 費用上限・生成量上限・実行頻度、認証情報の設定状況、ジョブ実行・ログ、費用記録、操作履歴 |

## 日常の運用
| やること | 方法 |
|---|---|
| テーマを承認して制作開始 | 市場調査 →「承認→制作」。商品が作成され制作ジョブが投入される |
| 販売開始 | 商品管理 →「→販売中」→ ダッシュボードの承認待ちで「承認」 |
| 待機中のジョブを実行 | 設定 →「待機中ジョブを実行」または `python3 -m cops run-jobs` |
| 毎日/毎週の処理 | `python3 -m cops daily` / `python3 -m cops weekly`（同じ日・週に何度実行しても重複しない） |
| 状況確認 | `python3 -m cops status` |
| バックアップ | `python3 -m cops backup`（`data/backups/` に zip。既定14世代保持） |
| 費用の記録 | 設定 → 費用記録。外部費用のみ月間上限の対象。Claude契約費は別枠 |

### 復元
```bash
# サーバーを停止してから
cd contentops/data
unzip backups/contentops-YYYYMMDD-HHMMSS.zip -d restore
cp restore/contentops.sqlite contentops.sqlite && cp -R restore/products .
```

## 安全のための仕組み
- 認証情報は `.env` または環境変数のみ。画面には「設定済み/未設定」だけを表示
- 管理画面は `127.0.0.1` のみで待ち受け、外部からアクセス不可（Hostヘッダ検査・CSRF対策ヘッダ）
- 外部公開・課金・投稿・破壊的変更は承認が必要。すべて `audit_log` に記録
- ジョブは同一キーで重複投入されない／リトライは既定2回まで／月間費用上限・1日の実行上限を超えると「保留」
- エラー時はトレースバックを `job_logs` に保存し、checkpoint から再開
- データ区分（実データ / AI推測 / 手入力 / ダミー）を全テーブルで保持

## テスト
```bash
cd contentops
python3 -m unittest discover -s tests -v
```

## ディレクトリ
```
contentops/
  cops/          Python パッケージ（schema.sql, db, jobs, budget, services, server, handlers, CLI）
  web/           管理画面（HTML/CSS/JS、ライブラリ不使用）
  prompts/       エージェント用プロンプト（Phase 2〜）
  tests/         自動テスト
  docs/          設計・費用
  data/          DB・原稿・PDF・バックアップ（git 管理外）
```

## 開発状況
- [x] Phase 1: ローカル環境・DB・管理画面・ジョブ/予算/承認基盤
- [ ] Phase 2: 市場調査・競合分析・テーマ評価
- [ ] Phase 3: 英語商品制作・品質検証・PDF
- [ ] Phase 4: SNS投稿制作・承認・予約配信
- [ ] Phase 5: 販売プラットフォーム連携・売上分析
- [ ] Phase 6: 定期実行・改善提案・関連商品展開
