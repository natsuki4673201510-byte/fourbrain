// スプレッドシート（Google Apps Script）への中継。URLと合言葉をブラウザに出さないためにサーバー側で呼ぶ
function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { 'content-type': 'application/json' }
  });
}

async function readGas(res) {
  const text = await res.text();
  try { return JSON.parse(text); } catch {
    return { error: 'スプレッドシート側の応答が読めません（Apps Scriptのデプロイ設定を確認してください）' };
  }
}

export default async (req) => {
  const passcode = process.env.APP_PASSCODE;
  if (!passcode || req.headers.get('x-app-passcode') !== passcode) {
    return json({ error: '合言葉が違います（またはNetlifyにAPP_PASSCODEが未設定です）' }, 401);
  }
  const gasUrl = process.env.GAS_URL;
  if (!gasUrl) return json({ error: 'NetlifyにGAS_URLが設定されていません' }, 500);

  try {
    if (req.method === 'GET') {
      const url = gasUrl + '?action=dict&secret=' + encodeURIComponent(passcode);
      const data = await readGas(await fetch(url, { redirect: 'follow' }));
      return json(data, data.error ? 502 : 200);
    }
    if (req.method === 'POST') {
      const body = await req.json();
      const res = await fetch(gasUrl, {
        method: 'POST',
        redirect: 'follow',
        headers: { 'content-type': 'text/plain;charset=utf-8' },
        body: JSON.stringify({
          secret: passcode,
          date: body.date,
          league: body.league,
          rows: body.rows || [],
          dict: body.dict || []
        })
      });
      const data = await readGas(res);
      return json(data, data.error ? 502 : 200);
    }
    return json({ error: 'Method not allowed' }, 405);
  } catch (e) {
    return json({ error: String(e && e.message ? e.message : e) }, 500);
  }
};

export const config = { path: '/api/league/sheet' };
