// TikTok LIVE リーグランキングのスクショ1枚を読み取り、順位・表示名・コイン・行の位置を返す
import Anthropic from '@anthropic-ai/sdk';
import { z } from 'zod';
import { zodOutputFormat } from '@anthropic-ai/sdk/helpers/zod';

const RankingSchema = z.object({
  league: z.string().describe('画面に表示されているリーグ名（例: D5, C3）。見えなければ空文字'),
  rows: z.array(z.object({
    rank: z.number().int().describe('順位の数字'),
    name: z.string().describe('表示名。絵文字・記号も含めて画面の通りに'),
    coins: z.string().describe('コイン数など右側の数値。画面の表記のまま'),
    top: z.number().describe('この行の上端の位置。画像の高さに対する割合(0〜1)'),
    bottom: z.number().describe('この行の下端の位置。画像の高さに対する割合(0〜1)')
  }))
});

const PROMPT = [
  'これはTikTok LIVEのリーグランキング画面のスクリーンショットです。',
  '画面に見えている順位付きの行をすべて読み取ってください。',
  '- 画面下部に固定表示される自分自身の行や、見出し・ボタンは含めない',
  '- 上下の端で途中までしか写っていない行は、順位と名前が読めるものだけ含める',
  '- 表示名は1文字ずつ正確に（絵文字・記号・全角半角もそのまま）',
  '- top / bottom はアイコンと名前を含む行全体の範囲を、画像の高さに対する割合で'
].join('\n');

const client = new Anthropic();
const MODEL = process.env.CLAUDE_MODEL || 'claude-opus-5-5';

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { 'content-type': 'application/json' }
  });
}

export default async (req) => {
  if (req.method !== 'POST') return json({ error: 'Method not allowed' }, 405);
  if (!process.env.APP_PASSCODE || req.headers.get('x-app-passcode') !== process.env.APP_PASSCODE) {
    return json({ error: '合言葉が違います（またはNetlifyにAPP_PASSCODEが未設定です）' }, 401);
  }
  if (!process.env.ANTHROPIC_API_KEY) {
    return json({ error: 'NetlifyにANTHROPIC_API_KEYが設定されていません' }, 500);
  }

  let body;
  try { body = await req.json(); } catch { return json({ error: 'リクエストの形式が不正です' }, 400); }
  const image = body && body.image;
  const mediaType = (body && body.mediaType) || 'image/jpeg';
  if (!image) return json({ error: '画像がありません' }, 400);

  try {
    const response = await client.messages.parse({
      model: MODEL,
      max_tokens: 16000,
      output_config: { effort: 'low', format: zodOutputFormat(RankingSchema) },
      messages: [{
        role: 'user',
        content: [
          { type: 'image', source: { type: 'base64', media_type: mediaType, data: image } },
          { type: 'text', text: PROMPT }
        ]
      }]
    });

    if (response.stop_reason === 'refusal') {
      return json({ error: 'この画像は読み取りを断られました。別のスクショで試してください' }, 422);
    }
    if (response.stop_reason === 'max_tokens' || !response.parsed_output) {
      return json({ error: '読み取り結果を解析できませんでした。もう一度試してください' }, 502);
    }
    return json(response.parsed_output);
  } catch (e) {
    if (e instanceof Anthropic.RateLimitError) {
      return json({ error: '混み合っています。少し待ってから再試行してください' }, 429);
    }
    if (e instanceof Anthropic.AuthenticationError) {
      return json({ error: 'ANTHROPIC_API_KEYが無効です' }, 500);
    }
    if (e instanceof Anthropic.APIError) {
      return json({ error: 'Claude APIエラー: ' + e.message }, 502);
    }
    return json({ error: String(e && e.message ? e.message : e) }, 500);
  }
};

export const config = { path: '/api/league/read' };
