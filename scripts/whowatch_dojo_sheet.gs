/**
 * ふわっち道場 6級ランキング 上位30名のSNSを、Googleスプレッドシートに毎日タブ追加で書き込む。
 *
 * 使い方（最初に1回だけ）:
 *  1. スプレッドシートを開く → 拡張機能 → Apps Script
 *  2. このファイルの中身を全部貼り付けて保存
 *  3. 上の関数選択で「setup」を選んで ▶実行（権限の確認が出たら許可）
 *     → 前日分のタブが1つでき、毎朝10時台の自動実行が登録されます
 *
 * デザイン: TEMPLATE_GID のタブ（ルーキー総合200位 SNS一覧）をそのままコピーし、
 *           見出し行の列名を見て、同じ列に値を入れます（書式・色・列幅はそのまま）。
 */

const TEMPLATE_GID = 1625839944;   // デザインの元にするタブ
const GRADE = '6';                  // 道場の級
const TOP = 30;                     // 上位何名
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
  const tabName = '道場' + GRADE + '級 ' + dash;
  if (ss.getSheetByName(tabName)) return; // 同じ日付のタブがあれば何もしない

  const ranking = fetchJson(API + '/rankings/whowatch_dojo_' + GRADE + '/' + date + '?detail=true')[0];
  const ranks = ranking.rankings.slice(0, TOP);
  const profiles = UrlFetchApp.fetchAll(ranks.map(r => ({
    url: API + '/users/' + encodeURIComponent(r.user.user_path) + '/profile',
    muteHttpExceptions: true,
    headers: { 'User-Agent': 'Mozilla/5.0' },
  }))).map(res => { try { return JSON.parse(res.getContentText()); } catch (e) { return {}; } });

  const rows = ranks.map((r, i) => buildRow(r, profiles[i]));

  // テンプレートのタブをコピー（同じデザイン）
  const template = ss.getSheets().find(s => s.getSheetId() === TEMPLATE_GID);
  if (!template) throw new Error('テンプレートのタブ(gid=' + TEMPLATE_GID + ')が見つかりません');
  const sh = template.copyTo(ss).setName(tabName);
  ss.setActiveSheet(sh);
  ss.moveActiveSheet(1);

  const lastCol = sh.getLastColumn();
  const head = findHeaderRow(sh, lastCol);

  // タイトル（見出し行より上の「SNS一覧」「ふわっち」を含むセル）を書き換え
  if (head > 1) {
    const top = sh.getRange(1, 1, head - 1, lastCol);
    const vals = top.getValues();
    vals.forEach((row, ri) => row.forEach((v, ci) => {
      if (typeof v === 'string' && /SNS一覧|ふわっち|ルーキー/.test(v)) {
        sh.getRange(ri + 1, ci + 1).setValue(
          'ふわっち道場' + GRADE + '級 上位' + TOP + '名 SNS一覧（' + dash + '）' +
          (ranking.is_fixed ? '' : ' ※未確定'));
      }
    }));
  }

  // 元のデータを消す（書式は残す）、余った行は削除
  const firstData = head + 1;
  const maxRows = sh.getMaxRows();
  if (maxRows >= firstData) sh.getRange(firstData, 1, maxRows - head, lastCol).clearContent();
  if (maxRows > head + TOP) sh.deleteRows(head + TOP + 1, maxRows - head - TOP);

  // 見出しの列名に合わせて値を入れる
  const headers = sh.getRange(head, 1, 1, lastCol).getDisplayValues()[0];
  const keys = headers.map(mapHeader);
  const hasProfileCol = keys.indexOf('profile') >= 0;
  const out = rows.map(row => keys.map(k => {
    if (!k) return '';
    if (k === 'name' && !hasProfileCol) {
      return '=HYPERLINK("' + row.profile + '","' + String(row.name).replace(/"/g, '""') + '")';
    }
    return row[k] === undefined ? '' : row[k];
  }));
  if (keys.every(k => !k)) {
    // 列名が読めなかった場合は A列から固定の順で入れる
    const fixed = rows.map(r => [r.rank, r.name, r.point, r.profile, r.x, r.instagram, r.tiktok, r.youtube, r.other]);
    sh.getRange(firstData, 1, fixed.length, fixed[0].length).setValues(fixed);
  } else {
    sh.getRange(firstData, 1, out.length, lastCol).setValues(out);
  }
}

function fetchJson(url) {
  const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (res.getResponseCode() !== 200) throw new Error(url + ' → ' + res.getResponseCode());
  return JSON.parse(res.getContentText());
}

/** 1人分の行データ */
function buildRow(r, p) {
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
  // URLになっていないSNSの書き込み（@ID やSNS名を含む行）
  const mentions = desc.split(/\n/).map(s => s.trim()).filter(s => s &&
    !/https?:\/\//.test(s) &&
    (/[@＠][A-Za-z0-9_.]{2,30}/.test(s) ||
     /(twitter|ツイッター|instagram|インスタ|tiktok|ティックトック|youtube|ユーチューブ|ツイキャス|17live|イチナナ|pococha|ポコチャ|threads|lit\.link|linktr\.ee|(^|[^a-z])x[\s:：@＠])/i.test(s)));
  const any = x.length + instagram.length + tiktok.length + youtube.length + otherUrls.length + mentions.length;
  return {
    rank: r.rank,
    name: (p && p.name) || r.user.name,
    id: path,
    point: r.point,
    profile: 'https://whowatch.tv/profile/' + path,
    x: x.join('\n'),
    instagram: instagram.join('\n'),
    tiktok: tiktok.join('\n'),
    youtube: youtube.join('\n'),
    other: otherUrls.concat(mentions).join('\n') || (p && p.error_message ? '退会済み' : (any ? '' : 'なし')),
    sns: x.concat(instagram, tiktok, youtube, otherUrls, mentions).join('\n') || 'なし',
    followers: p && p.follower_count,
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
