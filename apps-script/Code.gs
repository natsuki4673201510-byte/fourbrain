/**
 * TikTok LIVE リーグランキング書き込み用 Google Apps Script
 *
 * 使い方（最初の1回だけ）:
 *  1. 書き込み先のスプレッドシートを開く → 拡張機能 → Apps Script
 *  2. このファイルの中身を全部貼り付け、下の SECRET を好きな合言葉に変える
 *     （NetlifyのAPP_PASSCODEと同じにする）
 *  3. デプロイ → 新しいデプロイ → 種類「ウェブアプリ」
 *     次のユーザーとして実行: 自分 / アクセスできるユーザー: 全員
 *  4. 表示されたURL（.../exec）をNetlifyのGAS_URLに設定
 */
const SECRET = 'ここを合言葉に変える';

const LEAGUES = [
  'D5', 'D4', 'D3', 'D2', 'D1',
  'C5', 'C4', 'C3', 'C2', 'C1',
  'B5', 'B4', 'B3', 'B2', 'B1'
];
const MAX_RANK = 99;
const FIRST_ROW = 3;          // 1行目: リーグ名 / 2行目: 見出し / 3行目から 1〜99位
const BLOCK = 4;              // 順位・ID・URL + 空き列
const DICT_SHEET = '辞書';     // 表示名 → ID の対応表

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  const p = e.parameter || {};
  if (p.secret !== SECRET) return out_({ error: '合言葉が一致しません（Apps ScriptのSECRETを確認）' });
  if (p.action === 'dict') return out_({ dict: readDict_() });
  return out_({ ok: true });
}

function doPost(e) {
  let data;
  try { data = JSON.parse(e.postData.contents); } catch (err) { return out_({ error: '形式が不正です' }); }
  if (data.secret !== SECRET) return out_({ error: '合言葉が一致しません（Apps ScriptのSECRETを確認）' });

  const idx = LEAGUES.indexOf(data.league);
  if (idx < 0) return out_({ error: '不明なリーグ: ' + data.league });
  if (!/^\d{4}-\d{2}-\d{2}$/.test(data.date || '')) return out_({ error: '日付の形式が不正です' });

  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const sheet = ensureDaySheet_(data.date);
    const idCol = idx * BLOCK + 2;
    const values = [];
    for (let r = 1; r <= MAX_RANK; r++) values.push(['']);
    let written = 0;
    (data.rows || []).forEach(function (row) {
      const rank = Number(row.rank);
      const id = cleanId_(row.id);
      if (rank >= 1 && rank <= MAX_RANK && id) { values[rank - 1][0] = id; written++; }
    });
    sheet.getRange(FIRST_ROW, idCol, MAX_RANK, 1).setValues(values);
    updateDict_(data.dict || [], data.date);
    return out_({ ok: true, written: written, sheet: data.date, league: data.league });
  } finally {
    lock.releaseLock();
  }
}

function cleanId_(id) {
  return String(id || '').trim().replace(/^https?:\/\/(www\.)?tiktok\.com\//, '').replace(/^@/, '').replace(/[/?#].*$/, '');
}

/** 日付タブがなければ作る（見出し・順位・URL数式入り） */
function ensureDaySheet_(date) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(date);
  if (sheet) return sheet;

  sheet = ss.insertSheet(date, 0);
  const lastCol = LEAGUES.length * BLOCK - 1;
  if (sheet.getMaxColumns() < lastCol) sheet.insertColumnsAfter(sheet.getMaxColumns(), lastCol - sheet.getMaxColumns());

  LEAGUES.forEach(function (league, i) {
    const c = i * BLOCK + 1;
    sheet.getRange(1, c).setValue(league).setFontWeight('bold');
    sheet.getRange(2, c, 1, 3).setValues([['順位', 'ID', 'URL']]).setFontWeight('bold').setBackground('#eeeeee');
    const ranks = [];
    for (let r = 1; r <= MAX_RANK; r++) ranks.push([r]);
    sheet.getRange(FIRST_ROW, c, MAX_RANK, 1).setValues(ranks);
    sheet.getRange(FIRST_ROW, c + 1, MAX_RANK, 1).setNumberFormat('@'); // 数字だけのIDが数値に化けないように
    sheet.getRange(FIRST_ROW, c + 2, MAX_RANK, 1)
      .setFormulaR1C1('=IF(RC[-1]="","","https://www.tiktok.com/@"&RC[-1])');
    sheet.setColumnWidth(c, 40);
    sheet.setColumnWidth(c + 1, 140);
    sheet.setColumnWidth(c + 2, 240);
    if (i < LEAGUES.length - 1) sheet.setColumnWidth(c + 3, 20);
  });
  sheet.setFrozenRows(2);
  return sheet;
}

function dictSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(DICT_SHEET);
  if (!sheet) {
    sheet = ss.insertSheet(DICT_SHEET);
    sheet.getRange(1, 1, 1, 3).setValues([['表示名', 'ID', '最終確認日']]).setFontWeight('bold');
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function normName_(name) {
  return String(name || '').normalize('NFKC').replace(/\s+/g, ' ').trim();
}

function readDict_() {
  const sheet = dictSheet_();
  const last = sheet.getLastRow();
  const dict = {};
  if (last < 2) return dict;
  sheet.getRange(2, 1, last - 1, 2).getValues().forEach(function (r) {
    const k = normName_(r[0]);
    if (k && r[1]) dict[k] = String(r[1]);
  });
  return dict;
}

function updateDict_(entries, date) {
  if (!entries.length) return;
  const sheet = dictSheet_();
  const last = sheet.getLastRow();
  const rowsByName = {};
  if (last >= 2) {
    sheet.getRange(2, 1, last - 1, 1).getValues().forEach(function (r, i) {
      rowsByName[normName_(r[0])] = i + 2;
    });
  }
  entries.forEach(function (e) {
    const name = normName_(e.name);
    const id = cleanId_(e.id);
    if (!name || !id) return;
    if (rowsByName[name]) {
      sheet.getRange(rowsByName[name], 2, 1, 2).setValues([[id, date]]);
    } else {
      sheet.appendRow([name, id, date]);
      rowsByName[name] = sheet.getLastRow();
    }
  });
}
