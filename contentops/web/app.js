"use strict";
// ContentOps 管理画面（依存ライブラリなし）。AI生成テキストを表示するため、すべて esc() でエスケープする。

const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NA = '<span class="na">未取得</span>';
const yen = (v) => (v == null ? NA : "¥" + Math.round(v).toLocaleString());
const num = (v) => (v == null ? NA : Number(v).toLocaleString());
const pct = (v) => (v == null ? NA : (v * 100).toFixed(1) + "%");

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-COPS": "1" }, body: JSON.stringify(body) };
  const r = await fetch("/api" + path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "HTTP " + r.status);
  return data;
}
function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = err ? "err" : ""; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3500);
}
async function act(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(typeof okMsg === "function" ? okMsg(r) : okMsg); render(); return r; }
  catch (e) { toast(e.message, true); }
}
const badge = (s) => {
  const cls = { approved: "ok", on_sale: "ok", succeeded: "ok", posted: "ok", pass: "ok", executed: "ok",
    awaiting_approval: "warn", pending: "warn", blocked: "warn", warn: "warn", scheduled: "warn", draft: "muted",
    failed: "bad", rejected: "bad", stopped: "bad", fail: "bad", cancelled: "muted", archived: "muted" }[s] || "";
  return `<span class="badge ${cls}">${esc(LABEL[s] || s)}</span>`;
};
const LABEL = { discovered: "発見", shortlisted: "候補", approved: "承認済", rejected: "却下", archived: "保管",
  planning: "企画中", producing: "制作中", awaiting_approval: "承認待ち", on_sale: "販売中", paused: "一時停止", stopped: "停止",
  draft: "下書き", scheduled: "配信予定", posted: "投稿済", failed: "失敗", queued: "待機", running: "実行中",
  succeeded: "成功", cancelled: "取消", blocked: "保留", pending: "保留中", executed: "実行済",
  empathy: "共感型", insight: "気づき型", experience: "体験談・検証型", contrarian: "逆説型", other: "その他",
  real: "実データ", ai_estimate: "AI推測", manual: "手入力", dummy: "ダミー" };

let META = {};
const views = {};

// ------------------------------------------------------------ ダッシュボード
views.dashboard = async () => {
  const d = await api("/dashboard");
  const ap = await api("/approvals");
  const b = d.budget;
  const ps = d.products_by_status;
  const bw = Math.min(100, (b.ratio || 0) * 100);
  return `
  <h1>ダッシュボード</h1><p class="sub">${esc(d.month)} ・ 売上データ: ${d.has_sales_data ? "あり" : "未取得（販売開始前または未連携）"}</p>
  <div class="grid">
    ${kpi("今月の売上", yen(d.revenue_jpy), d.has_sales_data ? `目標 ¥1,000,000 の ${(d.revenue_jpy / 1e4).toFixed(1)}%` : "実データのみ表示")}
    ${kpi("今月の粗利益", yen(d.gross_profit_jpy), "売上−返金−手数料−外部費用")}
    ${kpi("注文数", num(d.orders), "")}
    ${kpi("販売中の商品", num(ps.on_sale || 0), `全${Object.values(ps).reduce((a, v) => a + v, 0)}本 / 初期目標20本`)}
    ${kpi("承認待ち", num(d.pending_approvals), "外部公開・課金等")}
    ${kpi("失敗ジョブ(24h)", num(d.failed_jobs_24h), "")}
    <div class="card kpi"><div class="label">外部費用（月間上限）</div>
      <div class="value">${yen(b.spent_jpy + b.reserved_jpy)} <span class="note">/ ${yen(b.cap_jpy)}</span></div>
      <div class="bar ${b.level}"><div style="width:${bw}%"></div></div>
      <div class="note">Claude契約費は別枠${b.claude_plan_jpy != null ? "（" + yen(b.claude_plan_jpy) + "/月）" : ""}</div></div>
  </div>
  ${approvalsTable(ap.filter((a) => a.status === "pending"))}
  <h2>商品別KPI</h2>
  ${d.products.length ? `<div class="scroll"><table><tr><th>商品</th><th>状態</th><th class="num">閲覧</th><th class="num">SNS表示</th>
    <th class="num">クリック</th><th class="num">購入</th><th class="num">購入率</th><th class="num">売上</th><th class="num">返金</th>
    <th class="num">手数料</th><th class="num">運用費</th><th class="num">粗利益</th><th class="num">制作時間</th></tr>
    ${d.products.map((p) => `<tr><td>${esc(p.code)} ${esc(p.title)} ${p.has_dummy ? badge("dummy") : ""}</td><td>${badge(p.status)}</td>
      <td class="num">${num(p.page_views)}</td><td class="num">${num(p.sns_impressions)}</td><td class="num">${num(p.sns_link_clicks)}</td>
      <td class="num">${num(p.purchases)}</td><td class="num">${pct(p.conversion)}</td><td class="num">${yen(p.revenue_jpy)}</td>
      <td class="num">${yen(p.refunds_jpy)}</td><td class="num">${yen(p.fees_jpy)}</td><td class="num">${yen(p.ops_cost_jpy)}</td>
      <td class="num">${yen(p.gross_profit_jpy)}</td><td class="num">${p.production_minutes == null ? NA : p.production_minutes + "分"}</td></tr>`).join("")}
    </table></div>` : `<div class="empty">商品はまだありません。市場調査でテーマを承認すると商品が作成されます。</div>`}`;
};
const kpi = (label, value, note) => `<div class="card kpi"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></div>`;
function approvalsTable(list) {
  if (!list.length) return `<h2>承認待ち</h2><div class="empty">承認待ちの操作はありません</div>`;
  return `<h2>承認待ち</h2><table><tr><th>#</th><th>操作</th><th>内容</th><th>依頼日時</th><th></th></tr>
    ${list.map((a) => `<tr><td>${a.id}</td><td>${esc(a.action)}</td><td>${esc(a.summary)}</td><td>${esc(a.requested_at)}</td>
    <td class="actions"><button class="primary" data-approve="${a.id}">承認</button><button class="danger" data-reject="${a.id}">却下</button></td></tr>`).join("")}</table>`;
}
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-approve],[data-reject]");
  if (!t) return;
  const id = t.dataset.approve || t.dataset.reject;
  const approve = !!t.dataset.approve;
  if (approve && !confirm("この操作を承認しますか？（外部公開などが実行されます）")) return;
  act(() => api(`/approvals/${id}`, { approve }), approve ? "承認しました" : "却下しました");
});

// ------------------------------------------------------------ 市場調査
views.research = async () => {
  const ts = await api("/themes");
  const st = (s) => ts.filter((t) => t.status === s).length;
  return `
  <h1>市場調査</h1><p class="sub">テーマ ${ts.length}件（候補 ${st("shortlisted")} / 承認 ${st("approved")}）。スコア = 需要30 + 差別化25 + 購入動機20 + 継続需要15 + 制作容易さ10</p>
  <div class="actions"><button class="primary" id="start-research">市場調査を開始</button>
    ${META.implemented_jobs?.includes("market_research") ? "" : '<span class="badge warn">調査エージェントは Phase 2 で実装予定（ジョブは保留されます）</span>'}</div>
  <h2>テーマ一覧</h2>
  ${ts.length ? `<div class="scroll"><table><tr><th class="num">スコア</th><th>テーマ</th><th>想定購入者 / 悩み</th><th class="num">価格</th>
    <th>内訳</th><th>根拠</th><th>区分</th><th>状態</th><th></th></tr>
    ${ts.map((t) => `<tr><td class="num"><b>${t.score_total.toFixed(0)}</b></td>
      <td>${esc(t.name)}${t.product_code ? `<br><span class="badge">${esc(t.product_code)}</span>` : ""}</td>
      <td>${esc(t.target_buyer)}<br><span class="na">${esc(t.pain_point)}</span></td>
      <td class="num">${t.price_usd == null ? NA : "$" + t.price_usd}</td>
      <td style="font-size:12px">需${t.score_demand ?? "-"} 差${t.score_differentiation ?? "-"} 動${t.score_motivation ?? "-"} 継${t.score_recurring ?? "-"} 易${t.score_ease ?? "-"}</td>
      <td>URL ${t.evidence_count} / 競合 ${t.competitor_count} <br><a href="#/research/${t.id}">詳細</a></td>
      <td>${badge(t.data_origin)}</td><td>${badge(t.status)}</td>
      <td class="actions">${t.status !== "approved" ? `<button data-theme="${t.id}" data-st="shortlisted">候補</button>
        <button class="primary" data-theme="${t.id}" data-st="approved">承認→制作</button>
        <button class="danger" data-theme="${t.id}" data-st="rejected">却下</button>` : ""}</td></tr>`).join("")}</table></div>`
    : `<div class="empty">テーマはまだありません。「市場調査を開始」または下のフォームから手動で追加できます。</div>`}
  <details style="margin-top:16px"><summary>テーマを手動で追加</summary>
    <div class="card"><form id="theme-form">
      <div class="row"><div><label>テーマ名*</label><input name="name" required></div><div><label>想定購入者</label><input name="target_buyer"></div>
      <div><label>想定価格 (USD)</label><input name="price_usd" type="number" step="0.01"></div></div>
      <label>具体的な悩み</label><input name="pain_point">
      <label>検索需要の根拠（要約）</label><input name="demand_evidence">
      <div class="row"><div><label>根拠URL</label><input name="ev_url" type="url"></div><div><label>取得日</label><input name="ev_date" type="date"></div></div>
      <div class="row">${[["score_demand", 30], ["score_differentiation", 25], ["score_motivation", 20], ["score_recurring", 15], ["score_ease", 10]]
        .map(([k, m]) => `<div><label>${k.replace("score_", "")} (0-${m})</label><input name="${k}" type="number" min="0" max="${m}" step="0.5"></div>`).join("")}</div>
      <p><button class="primary">追加</button></p></form></div></details>`;
};
views.research_detail = async (id) => {
  const t = await api(`/themes/${id}`);
  const f = (k, l) => `<tr><th style="width:180px">${l}</th><td>${esc(t[k]) || NA}</td></tr>`;
  return `<p><a href="#/research">← 市場調査</a></p><h1>${esc(t.name)}</h1>
  <p class="sub">${badge(t.status)} ${badge(t.data_origin)} スコア ${t.score_total.toFixed(0)} / 100</p>
  <table>${f("target_buyer", "想定購入者")}${f("pain_point", "具体的な悩み")}${f("demand_evidence", "検索需要の根拠")}${f("similar_products", "類似商品")}
    ${f("unmet_needs", "未解決の課題")}${f("differentiation", "差別化案")}${f("price_usd", "想定価格(USD)")}${f("production_cost_jpy", "制作コスト(円)")}
    ${f("recurring_demand", "継続需要")}${f("score_rationale", "採点理由")}</table>
  <h2>根拠URL</h2>${t.evidence.length ? `<table><tr><th>タイトル</th><th>種別</th><th>代替指標</th><th>取得日</th></tr>
    ${t.evidence.map((e) => `<tr><td><a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title || e.url)}</a><br><span class="na">${esc(e.excerpt)}</span></td>
    <td>${esc(e.source_type)}</td><td>${e.metric_name ? esc(e.metric_name) + ": " + num(e.metric_value) : NA}</td><td>${esc(e.retrieved_at)}</td></tr>`).join("")}</table>` : '<div class="empty">根拠なし</div>'}
  <h2>競合商品</h2>${t.competitors.length ? `<table><tr><th>商品</th><th>販売先</th><th class="num">価格</th><th>公開されている販売シグナル</th><th>弱点</th></tr>
    ${t.competitors.map((c) => `<tr><td><a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.name)}</a></td><td>${esc(c.platform)}</td>
    <td class="num">${c.price == null ? NA : esc(c.price) + " " + esc(c.currency)}</td><td>${esc(c.sales_signal) || NA}</td><td>${esc(c.weaknesses)}</td></tr>`).join("")}</table>` : '<div class="empty">競合データなし</div>'}`;
};
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-theme]");
  if (t) {
    if (t.dataset.st === "approved" && !confirm("このテーマを承認し、商品制作を開始しますか？")) return;
    act(() => api(`/themes/${t.dataset.theme}/status`, { status: t.dataset.st }),
      (r) => (r.product_code ? `商品 ${r.product_code} を作成しました` : "更新しました"));
  }
  if (e.target.id === "start-research") {
    act(() => api("/jobs", { type: "market_research", payload: {}, key: "market_research:" + new Date().toISOString().slice(0, 10) }),
      (r) => (r.created ? `調査ジョブ #${r.id} を投入しました` : `本日の調査ジョブ #${r.id} は投入済みです`));
  }
});
document.addEventListener("submit", (e) => {
  if (e.target.id !== "theme-form") return;
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  const body = {};
  for (const [k, v] of Object.entries(f)) if (v !== "" && !k.startsWith("ev_")) body[k] = k.startsWith("score_") || k === "price_usd" ? Number(v) : v;
  if (f.ev_url) body.evidence = [{ url: f.ev_url, retrieved_at: f.ev_date || new Date().toISOString().slice(0, 10), source_type: "manual" }];
  act(() => api("/themes", body), (r) => (r.created ? "追加しました" : "同名テーマが存在するため更新しました"));
});

// ------------------------------------------------------------ 商品管理
const COLS = ["planning", "producing", "awaiting_approval", "on_sale", "paused", "stopped"];
const NEXT = { planning: ["producing", "stopped"], producing: ["awaiting_approval", "planning"], awaiting_approval: ["on_sale", "producing"],
  on_sale: ["paused", "stopped"], paused: ["on_sale", "stopped"], stopped: ["planning"] };
views.products = async () => {
  const ps = await api("/products");
  return `<h1>商品管理</h1><p class="sub">「販売中」への変更は承認が必要です（外部公開）</p>
  ${ps.length ? `<div class="kanban">${COLS.map((c) => `<div class="col"><h3>${LABEL[c]} (${ps.filter((p) => p.status === c).length})</h3>
    ${ps.filter((p) => p.status === c).map((p) => `<div class="card"><b>${esc(p.code)}</b> ${esc(p.title)}
      <div class="na" style="font-size:12px">JA v${p.ja_version ?? "-"} / EN v${p.en_version ?? "-"} / PDF v${p.pdf_version ?? "-"}
      ・QA不合格 ${p.qa_fail} ・投稿 ${p.post_count}</div>
      <div class="actions" style="margin-top:6px"><a class="btn" href="#/content/${p.id}">編集</a>
      ${NEXT[p.status].map((n) => `<button data-prod="${p.id}" data-to="${n}">→${LABEL[n]}</button>`).join("")}</div></div>`).join("")}</div>`).join("")}</div>`
    : `<div class="empty">商品はまだありません。<a href="#/research">市場調査</a>でテーマを承認してください。</div>`}`;
};
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-prod]");
  if (!t) return;
  act(() => api(`/products/${t.dataset.prod}/transition`, { to: t.dataset.to }),
    (r) => (r.pending ? `承認依頼 #${r.approval_id} を作成しました（ダッシュボードで承認）` : "更新しました"));
});

// ------------------------------------------------------------ コンテンツ編集
views.content = async (id) => {
  const ps = await api("/products");
  if (!ps.length) return `<h1>コンテンツ編集</h1><div class="empty">商品がありません</div>`;
  id = id || ps[0].id;
  const c = await api(`/products/${id}/content`);
  const pdfs = c.versions.filter((v) => v.kind === "pdf");
  return `<h1>コンテンツ編集</h1>
  <div class="row" style="max-width:480px"><div><label>商品</label><select id="content-pick">
    ${ps.map((p) => `<option value="${p.id}" ${p.id == id ? "selected" : ""}>${esc(p.code)} ${esc(p.title)}</option>`).join("")}</select></div></div>
  <p class="sub">${badge(c.product.status)} 保存すると新しいバージョンとして記録されます（過去版は上書きされません）</p>
  <div class="split">
    ${["ja", "en"].map((l) => `<div class="card"><b>${l === "ja" ? "日本語原稿" : "英語原稿"}</b>
      <span class="na">（${c["latest_" + l].length.toLocaleString()}字）</span>
      <textarea id="ed-${l}">${esc(c["latest_" + l])}</textarea>
      <p><button class="primary" data-save="${l}" data-pid="${id}">保存（新バージョン）</button></p></div>`).join("")}
  </div>
  <h2>PDF</h2>${pdfs.length ? pdfs.map((v) => `<a class="btn" target="_blank" href="/files/${esc(v.path)}">${esc(v.lang)} v${v.version}</a>`).join(" ")
    : '<div class="empty">PDFはまだありません（Phase 3で自動生成）</div>'}
  <h2>品質検証</h2>${c.qa.length ? `<table><tr><th>項目</th><th>結果</th><th>メモ</th><th>検証者</th><th>日時</th></tr>
    ${c.qa.map((q) => `<tr><td>${esc(q.check_name)}</td><td>${badge(q.result)}</td><td>${esc(q.notes)}</td><td>${esc(q.checked_by)}</td><td>${esc(q.checked_at)}</td></tr>`).join("")}</table>`
    : '<div class="empty">品質検証の記録はまだありません</div>'}
  <h2>バージョン履歴</h2><table><tr><th>種類</th><th>言語</th><th>版</th><th class="num">文字数</th><th>作成者</th><th>日時</th></tr>
    ${c.versions.map((v) => `<tr><td>${esc(v.kind)}</td><td>${esc(v.lang)}</td><td>v${v.version}</td><td class="num">${num(v.char_count)}</td><td>${esc(v.author)}</td><td>${esc(v.created_at)}</td></tr>`).join("")}</table>`;
};
document.addEventListener("change", (e) => { if (e.target.id === "content-pick") location.hash = "#/content/" + e.target.value; });
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-save]");
  if (!t) return;
  const text = $("#ed-" + t.dataset.save).value;
  act(() => api(`/products/${t.dataset.pid}/content/${t.dataset.save}`, { text }), (r) => (r.duplicate ? "変更がないため保存しませんでした" : `v${r.version} を保存しました`));
});

// ------------------------------------------------------------ SNS管理
views.sns = async () => {
  const [posts, ps, set] = await Promise.all([api("/posts"), api("/products"), api("/settings")]);
  const auto = set.settings.sns_auto_publish;
  return `<h1>SNS管理（X）</h1><p class="sub">承認済みの投稿のみ公開対象になります。自動配信: ${auto ? "ON" : "OFF（初期設定）"}・公式APIのみ使用</p>
  <details><summary>投稿案を手動で追加</summary><div class="card"><form id="post-form">
    <div class="row"><div><label>商品</label><select name="product_id"><option value="">(なし)</option>${ps.map((p) => `<option value="${p.id}">${esc(p.code)} ${esc(p.title)}</option>`).join("")}</select></div>
    <div><label>型</label><select name="post_type">${["empathy", "insight", "experience", "contrarian", "other"].map((t) => `<option value="${t}">${LABEL[t]}</option>`).join("")}</select></div>
    <div><label>訴求対象</label><input name="audience"></div><div><label>投稿予定日時</label><input name="scheduled_at" type="datetime-local"></div></div>
    <label>冒頭フック*</label><input name="hook" required><label>本文*</label><textarea name="body" style="min-height:100px" required></textarea>
    <div class="row"><div><label>購入導線</label><input name="cta"></div><div><label>根拠（体験談・検証型は必須：実在する情報のみ）</label><input name="source_note"></div></div>
    <p><button class="primary">追加</button></p></form></div></details>
  <h2>投稿一覧</h2>${posts.length ? `<div class="scroll"><table><tr><th>状態</th><th>商品</th><th>型</th><th>訴求対象</th><th>投稿内容</th><th>予定</th><th class="num">表示</th><th class="num">クリック</th><th></th></tr>
    ${posts.map((p) => `<tr><td>${badge(p.status)}</td><td>${esc(p.product_code)}</td><td>${esc(LABEL[p.post_type])}</td><td>${esc(p.audience)}</td>
    <td><b>${esc(p.hook)}</b><br>${esc(p.body)}<br><span class="na">${esc(p.cta)}</span>${p.source_note ? `<br><span class="badge muted">根拠: ${esc(p.source_note)}</span>` : ""}</td>
    <td>${esc(p.scheduled_at) || '<span class="na">未設定</span>'}</td><td class="num">${num(p.impressions)}</td><td class="num">${num(p.link_clicks)}</td>
    <td class="actions">${postActions(p)}</td></tr>`).join("")}</table></div>` : '<div class="empty">投稿案はまだありません（Phase 4で商品ごとに10本を自動生成）</div>'}`;
};
function postActions(p) {
  const b = (a, l, cls = "") => `<button class="${cls}" data-post="${p.id}" data-act="${a}">${l}</button>`;
  return { draft: b("approve", "承認", "primary") + b("reject", "却下", "danger"),
    approved: b("schedule", "予約") + b("reopen", "下書きへ") + b("reject", "却下", "danger"),
    scheduled: b("unschedule", "予約解除") + b("reject", "却下", "danger"),
    rejected: b("reopen", "下書きへ") }[p.status] || "";
}
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-post]");
  if (!t) return;
  let body = {};
  if (t.dataset.act === "schedule") {
    const v = prompt("配信予定日時 (YYYY-MM-DD HH:MM)");
    if (!v) return;
    body.scheduled_at = v;
  }
  act(() => api(`/posts/${t.dataset.post}/${t.dataset.act}`, body), "更新しました");
});
document.addEventListener("submit", (e) => {
  if (e.target.id !== "post-form") return;
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  const body = {};
  for (const [k, v] of Object.entries(f)) if (v !== "") body[k] = k === "product_id" ? Number(v) : k === "scheduled_at" ? v.replace("T", " ") : v;
  act(() => api("/posts", body), "追加しました");
});

// ------------------------------------------------------------ 改善提案
views.improve = async () => {
  const [recs, d] = await Promise.all([api("/recommendations"), api("/dashboard")]);
  const DEC = { continue: "継続販売", improve_page: "販売ページ改善", price_test: "価格テスト", make_related: "関連商品制作", stop: "販売停止", collect_data: "データ収集", other: "その他" };
  return `<h1>改善提案</h1><p class="sub">毎週の分析結果。実データが無い段階では仮の実績を作らず、必要なデータ量と次の実験を提示します。</p>
  ${!d.has_sales_data ? `<div class="card"><b>現在の状態：売上データなし</b><ul>
    <li>判断に必要な最小データ（目安）: 商品ページ閲覧 各商品 200〜300回、または購入 5件以上。これ未満の購入率は誤差が大きく判断に使いません。</li>
    <li>次の実験: 上位テーマ1〜2本を販売開始 → X投稿10本を2週間で配信 → 閲覧数・クリック数・購入を記録。</li>
    <li>価格テストは閲覧が十分（目安: 各価格300回以上）になってから実施します。</li></ul></div>` : ""}
  <h2>提案一覧</h2>${recs.length ? `<table><tr><th>週</th><th>商品</th><th>判断</th><th>根拠</th><th>次のアクション</th><th>区分</th><th>状態</th></tr>
    ${recs.map((r) => `<tr><td>${esc(r.week)}</td><td>${esc(r.product_code)}</td><td>${esc(DEC[r.decision] || r.decision)}</td><td>${esc(r.rationale)}</td>
    <td>${esc(r.next_action)}</td><td>${badge(r.data_origin)}</td><td>${badge(r.status)}</td></tr>`).join("")}</table>` : '<div class="empty">提案はまだありません（Phase 6で週次自動生成）</div>'}`;
};

// ------------------------------------------------------------ システム設定
views.settings = async () => {
  const [s, jobs, costs, audit] = await Promise.all([api("/settings"), api("/jobs"), api("/costs"), api("/audit")]);
  const v = s.settings;
  const field = (k, label, type = "number") => type === "bool"
    ? `<div><label>${label}</label><select name="${k}" data-type="bool"><option value="true" ${v[k] ? "selected" : ""}>ON</option><option value="false" ${!v[k] ? "selected" : ""}>OFF</option></select></div>`
    : `<div><label>${label}</label><input name="${k}" type="${type}" value="${esc(v[k] ?? "")}" ${type === "number" ? 'data-type="number" step="any" min="0"' : ""}></div>`;
  return `<h1>システム設定</h1>
  <h2>費用上限</h2><div class="card"><form id="settings-form">
    <div class="row">${field("monthly_budget_jpy", "外部サービス月間上限 (円)")}${field("budget_warn_ratio", "警告しきい値 (0-1)")}
    ${field("claude_plan_monthly_jpy", "Claude契約費 (円/月・別枠記録)")}${field("usd_jpy_rate", "USD/JPY 換算")}</div>
    <h2>生成量の上限</h2><div class="row">${field("max_jobs_per_day", "1日のジョブ上限")}${field("max_products_in_production", "同時制作数の上限")}
    ${field("max_posts_per_product", "商品あたり投稿案上限")}${field("max_themes_per_research_run", "1回の調査テーマ数上限")}</div>
    <h2>実行頻度・エンジン</h2><div class="row">${field("schedule_daily_enabled", "毎日の自動実行", "bool")}${field("schedule_daily_time", "毎日の実行時刻", "text")}
    ${field("schedule_weekly_enabled", "毎週の自動実行", "bool")}${field("schedule_weekly_day", "毎週の曜日", "text")}</div>
    <div class="row">${field("llm_engine", "実行エンジン (claude_code_cli / anthropic_api / manual)", "text")}${field("claude_cli_path", "claude CLI パス", "text")}
    ${field("anthropic_model", "API利用時のモデル", "text")}</div>
    <h2>SNS・販売</h2><div class="row">${field("sns_auto_publish", "承認済み投稿の自動配信", "bool")}${field("sns_max_posts_per_day", "1日の最大投稿数")}
    ${field("sales_platform", "販売プラットフォーム（調査後に決定）", "text")}${field("backup_keep", "バックアップ保持数")}</div>
    <p><button class="primary">設定を保存</button></p></form></div>
  <h2>API・認証情報</h2><p class="sub">値は .env または環境変数で設定します（画面には設定済みかどうかのみ表示）</p>
  <table>${Object.entries(s.secrets).map(([k, ok]) => `<tr><td><code>${esc(k)}</code></td><td>${ok ? badge("succeeded").replace("成功", "設定済み") : '<span class="badge muted">未設定</span>'}</td></tr>`).join("")}</table>
  <h2>ジョブ</h2><div class="actions"><button class="primary" id="run-jobs">待機中ジョブを実行</button><button id="enq-anomaly">異常検知を実行</button><button id="do-backup">今すぐバックアップ</button></div>
  ${jobs.length ? `<div class="scroll" style="margin-top:8px"><table><tr><th>#</th><th>種別</th><th>状態</th><th class="num">試行</th><th>理由・エラー</th><th>作成</th><th></th></tr>
    ${jobs.map((j) => `<tr><td>${j.id}</td><td>${esc(META.job_types?.[j.type] || j.type)}</td><td>${badge(j.status)}</td><td class="num">${j.attempts}/${j.max_attempts}</td>
    <td style="max-width:360px">${esc(j.blocked_reason || "")} ${esc(j.last_error || "")}</td><td>${esc(j.created_at)}</td>
    <td class="actions"><button data-logs="${j.id}">ログ</button>${["failed", "cancelled"].includes(j.status) ? `<button data-job="${j.id}" data-act="retry">再実行</button>` : ""}
    ${["queued", "blocked"].includes(j.status) ? `<button class="danger" data-job="${j.id}" data-act="cancel">取消</button>` : ""}</td></tr>`).join("")}</table></div>`
    : '<div class="empty">ジョブはまだありません</div>'}
  <pre id="log-view" hidden></pre>
  <h2>費用記録</h2><form id="cost-form" class="row"><div><label>サービス</label><input name="service" required></div>
    <div><label>区分</label><select name="category"><option value="external">外部費用（上限対象）</option><option value="claude_plan">Claude契約</option><option value="platform_fee">販売手数料</option></select></div>
    <div><label>金額(円)</label><input name="amount_jpy" type="number" min="0" required></div><div><label>メモ</label><input name="description"></div><div><button class="primary">記録</button></div></form>
  ${costs.length ? `<table style="margin-top:8px"><tr><th>日時</th><th>サービス</th><th>区分</th><th class="num">金額</th><th>メモ</th></tr>
    ${costs.map((c) => `<tr><td>${esc(c.occurred_at)}</td><td>${esc(c.service)}</td><td>${esc(c.category)}</td><td class="num">${yen(c.amount_jpy)}${c.is_estimate ? " (見積)" : ""}</td><td>${esc(c.description)}</td></tr>`).join("")}</table>` : ""}
  <h2>操作履歴</h2>${audit.length ? `<details><summary>直近 ${audit.length} 件</summary><table>${audit.map((a) => `<tr><td>${esc(a.ts)}</td><td>${esc(a.actor)}</td><td>${esc(a.action)}</td><td><code>${esc(a.detail)}</code></td></tr>`).join("")}</table></details>` : '<div class="empty">履歴なし</div>'}
  <p class="sub" style="margin-top:20px">DB: <code>${esc(META.db_path)}</code></p>`;
};
document.addEventListener("submit", (e) => {
  if (e.target.id === "settings-form") {
    e.preventDefault();
    const body = {};
    for (const el of e.target.elements) {
      if (!el.name) continue;
      if (el.dataset.type === "bool") body[el.name] = el.value === "true";
      else if (el.dataset.type === "number") body[el.name] = el.value === "" ? null : Number(el.value);
      else body[el.name] = el.value === "" ? null : el.value;
    }
    for (const k of Object.keys(body)) if (body[k] === null && k !== "claude_plan_monthly_jpy" && k !== "sales_platform") delete body[k];
    if (body.claude_plan_monthly_jpy === null) delete body.claude_plan_monthly_jpy;
    act(() => api("/settings", body), "設定を保存しました");
  }
  if (e.target.id === "cost-form") {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    act(() => api("/costs", { ...f, amount_jpy: Number(f.amount_jpy) }), "記録しました");
  }
});
document.addEventListener("click", async (e) => {
  if (e.target.id === "run-jobs") act(() => api("/jobs/run", { limit: 5 }), (r) => `${r.length}件処理しました`);
  if (e.target.id === "enq-anomaly") act(() => api("/jobs", { type: "anomaly_check", payload: { at: Date.now() } }), "異常検知ジョブを投入しました");
  if (e.target.id === "do-backup") act(() => api("/backup", {}), (r) => `作成: ${r.file}`);
  const j = e.target.closest("[data-job]");
  if (j) act(() => api(`/jobs/${j.dataset.job}/${j.dataset.act}`, {}), "更新しました");
  const l = e.target.closest("[data-logs]");
  if (l) {
    const logs = await api(`/jobs/${l.dataset.logs}/logs`);
    const v = $("#log-view"); v.hidden = false;
    v.textContent = logs.map((x) => `[${x.ts}] ${x.level.toUpperCase()} ${x.message}`).join("\n") || "(ログなし)";
    v.scrollIntoView({ behavior: "smooth" });
  }
});

// ------------------------------------------------------------ ルーター
async function render() {
  const [, page = "dashboard", id] = location.hash.split("/");
  const name = page === "research" && id ? "research_detail" : page;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#/" + page));
  try { $("#view").innerHTML = await (views[name] || views.dashboard)(id); }
  catch (e) { $("#view").innerHTML = `<div class="empty">読み込みに失敗しました: ${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", render);
api("/meta").then((m) => { META = m; $("#demo-banner").hidden = !m.is_demo; render(); }).catch((e) => toast(e.message, true));
