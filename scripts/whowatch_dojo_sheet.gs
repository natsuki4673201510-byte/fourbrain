/**
 * ふわっち道場 1〜6級ランキング 各級の上位30名のSNSを、Googleスプレッドシートに毎日タブ追加で書き込む。
 *
 * 使い方（最初に1回だけ）:
 *  1. スプレッドシートを開く → 拡張機能 → Apps Script
 *  2. このファイルの中身を全部貼り付けて保存（前のコードは全部消して置き換え）
 *  3. 上の関数選択で「setup」を選んで ▶実行（権限の確認が出たら許可）
 *     → 前日分のタブが1つでき、毎朝10時台の自動実行が登録されます
 *
 * デザイン: TEMPLATE_GID のタブ（ルーキー総合200位 SNS一覧）をそのままコピーし、
 *           見出し行の列名を見て、同じ列に値を入れます（書式・色・列幅はそのまま）。
 *           テンプレートに「級」列が無ければ先頭に、「プロフィールURL」列が無ければ末尾に足します。
 */

const TEMPLATE_GID = 1625839944;            // デザインの元にするタブ
const GRADES = ['1', '2', '3', '4', '5', '6']; // 集める級
const TOP = 30;                              // 各級の上位何名
const API = 'https://api.whowatch.tv';

/** 最初に1回だけ実行：毎朝10時のトリガー登録 ＋ 前日分を作成 */
function setup() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'dailyRun')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('dailyRun')
    .timeBased().everyDays(1).atHour(10).nearMinute(0)
    .inTimezone('Asia/Tokyo')
    .create();
  dailyRun();
}

/** 毎朝の自動実行：前日（確定済）の分を追加 */
function dailyRun() {
  const y = new Date(Date.now() - 24 * 3600 * 1000);
  runForDate(Utilities.formatDate(y, 'Asia/Tokyo', 'yyyyMMdd'));
}

/** 日付を指定して手動で作るとき用（例: runForDate('20261109')） */
function runForDate(date) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const dash = date.slice(0, 4) + '-' + date.slice(4, 6) + '-' + date.slice(6);
  const tabName = '道場1-6級 ' + dash;
  if (ss.getSheetByName(tabName)) return; // 同じ日付のタブがあれば何もしない

  // 1〜6級のランキングとプロフィールを取得
  let rows = [];
  let allFixed = true;
  GRADES.forEach(g => {
    const ranking = fetchJson(API + '/rankings/whowatch_dojo_' + g + '/' + date + '?detail=true')[0];
    if (!ranking.is_fixed) allFixed = false;
    const ranks = ranking.rankings.slice(0, TOP);
    const profiles = UrlFetchApp.fetchAll(ranks.map(r => ({
      url: API + '/users/' + encodeURIComponent(r.user.user_path) + '/profile',
      muteHttpExceptions: true,
      headers: { 'User-Agent': 'Mozilla/5.0' },
    }))).map(res => { try { return JSON.parse(res.getContentText()); } catch (e) { return {}; } });
    rows = rows.concat(ranks.map((r, i) => buildRow(g, r, profiles[i])));
  });
  if (!rows.length) throw new Error(date + ' のランキングが空でした');

  // テンプレートのタブをコピー（同じデザイン）
  const template = ss.getSheets().find(s => s.getSheetId() === TEMPLATE_GID);
  if (!template) throw new Error('テンプレートのタブ(gid=' + TEMPLATE_GID + ')が見つかりません');
  const sh = template.copyTo(ss).setName(tabName);
  ss.setActiveSheet(sh);
  ss.moveActiveSheet(1);

  let lastCol = sh.getLastColumn();
  const head = findHeaderRow(sh, lastCol);

  // 「級」列が無ければ先頭に追加（隣の列の書式をコピー）
  let keys = sh.getRange(head, 1, 1, lastCol).getDisplayValues()[0].map(mapHeader);
  if (keys.indexOf('grade') < 0) {
    sh.insertColumnBefore(1);
    sh.getRange(1, 2, sh.getMaxRows(), 1).copyFormatToRange(sh, 1, 1, 1, sh.getMaxRows());
    sh.getRange(head, 1).setValue('級');
    sh.setColumnWidth(1, 50);
    lastCol++;
  }
  // 「プロフィールURL」列が無ければ末尾に追加
  keys = sh.getRange(head, 1, 1, lastCol).getDisplayValues()[0].map(mapHeader);
  if (keys.indexOf('profile') < 0) {
    sh.insertColumnAfter(lastCol);
    sh.getRange(1, lastCol, sh.getMaxRows(), 1).copyFormatToRange(sh, lastCol + 1, lastCol + 1, 1, sh.getMaxRows());
    sh.getRange(head, lastCol + 1).setValue('プロフィールURL');
    sh.setColumnWidth(lastCol + 1, 260);
    lastCol++;
  }
  keys = sh.getRange(head, 1, 1, lastCol).getDisplayValues()[0].map(mapHeader);

  // タイトル（見出し行より上の「SNS一覧」「ふわっち」を含むセル）を書き換え
  if (head > 1) {
    const vals = sh.getRange(1, 1, head - 1, lastCol).getValues();
    vals.forEach((row, ri) => row.forEach((v, ci) => {
      if (typeof v === 'string' && /SNS一覧|ふわっち|ルーキー/.test(v)) {
        sh.getRange(ri + 1, ci + 1).setValue(
          'ふわっち道場 1〜6級 各上位' + TOP + '名 SNS一覧（' + dash + '）' + (allFixed ? '' : ' ※未確定'));
      }
    }));
  }

  // 元のデータを消して（書式は残す）、行数を合わせる
  const firstData = head + 1;
  const need = head + rows.length;
  if (sh.getMaxRows() < need) sh.insertRowsAfter(sh.getMaxRows(), need - sh.getMaxRows());
  sh.getRange(firstData, 1, sh.getMaxRows() - head, lastCol).clearContent();
  if (sh.getMaxRows() > need) sh.deleteRows(need + 1, sh.getMaxRows() - need);

  // 見出しの列名に合わせて値を入れる（備考などは空欄）
  const out = rows.map(row => keys.map(k => (k && row[k] !== undefined) ? row[k] : ''));
  sh.getRange(firstData, 1, out.length, lastCol).setValues(out);
}

function fetchJson(url) {
  const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (res.getResponseCode() !== 200) throw new Error(url + ' → ' + res.getResponseCode());
  return JSON.parse(res.getContentText());
}

/** 1人分の行データ */
function buildRow(grade, r, p) {
  const path = r.user.user_path;
  const desc = (p && p.description) || '';
  const urls = (desc.match(/https?:\/\/[^\s　）)」』】<>"']+/g) || [])
    .filter(u => u.indexOf('whowatch.tv') < 0);
  const pick = re => urls.filter(u => re.test(u));
  const x = pick(/(twitter\.com|x\.com)\//i);
  if (path.indexOf('t:') === 0) {               // Xで登録したアカウント
    const xu = 'https://x.com/' + path.slice(2);
    if (x.indexOf(xu) < 0) x.unshift(xu);
  }
  const instagram = pick(/instagram\.com/i);
  const tiktok = pick(/tiktok\.com/i);
  const youtube = pick(/(youtube\.com|youtu\.be)/i);
  const otherUrls = urls.filter(u => !/(twitter\.com|x\.com\/|instagram\.com|tiktok\.com|youtube\.com|youtu\.be)/i.test(u));
  return {
    grade: grade + '級',
    rank: r.rank,
    name: (p && p.name) || r.user.name,
    id: path.replace(/^[a-z]+:/i, ''),          // 「w:」「t:」などを消す
    point: r.point,
    profile: 'https://whowatch.tv/profile/' + path,
    x: x.join('\n'),
    instagram: instagram.join('\n'),
    tiktok: tiktok.join('\n'),
    youtube: youtube.join('\n'),
    sns: x.concat(instagram, tiktok, youtube, otherUrls).join('\n'),
    followers: p && p.follower_count,
    // other（備考）は空欄
  };
}

/** 見出し行（「順位」「名前」などがある行）を上から10行で探す */
function findHeaderRow(sh, lastCol) {
  const vals = sh.getRange(1, 1, Math.min(10, sh.getMaxRows()), lastCol).getDisplayValues();
  for (let i = 0; i < vals.length; i++) {
    if (vals[i].some(v => /順位|名前|ユーザー|配信者|ライバー/.test(v))) return i + 1;
  }
  return 1;
}

/** 見出しの文字 → 入れる値の種類 */
function mapHeader(h) {
  const s = String(h).trim().toLowerCase();
  if (!s) return '';
  if (/^級$|グレード|クラス|^級/.test(s)) return 'grade';
  if (/順位|rank|^no\.?$|^#$/.test(s)) return 'rank';
  if (/twitter|ツイッター|^x\b|^x[\s(（]|x\s*\(|x（/.test(s) || s === 'x') return 'x';
  if (/insta|インスタ/.test(s)) return 'instagram';
  if (/tiktok|ティック/.test(s)) return 'tiktok';
  if (/youtube|ユーチューブ/.test(s)) return 'youtube';
  if (/その他|備考|メモ|other/.test(s)) return 'other';
  if (/sns/.test(s)) return 'sns';
  if (/ポイント|point|pt|スコア/.test(s)) return 'point';
  if (/フォロワー|follower/.test(s)) return 'followers';
  if (/プロフ|profile|url|リンク|ふわっち/.test(s)) return 'profile';
  if (/名前|ユーザー名|配信者|ライバー|ニックネーム|name/.test(s)) return 'name';
  if (/id|アカウント/.test(s)) return 'id';
  return '';
}
