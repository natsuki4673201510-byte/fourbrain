export default async (req) => {
  try {
    if (req.method !== 'POST') {
      return new Response(JSON.stringify({ error: 'Method not allowed' }), { status: 405 });
    }
    if (!process.env.ANTHROPIC_API_KEY) {
      return new Response(JSON.stringify({ error: 'サーバー側にANTHROPIC_API_KEYが設定されていません。Netlifyの環境変数を確認してください。' }), { status: 500 });
    }

    var body = await req.json();
    var system = body.system || '';
    var messages = body.messages || [];

    var upstream = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': process.env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify({
        model: 'claude-sonnet-5',
        max_tokens: 1000,
        system: system,
        messages: messages
      })
    });

    var data = await upstream.json();

    if (!upstream.ok) {
      var msg = (data && data.error && data.error.message) || ('Upstream error (HTTP ' + upstream.status + ')');
      return new Response(JSON.stringify({ error: msg }), { status: upstream.status });
    }

    var text = '';
    if (data && data.content){
      for (var i = 0; i < data.content.length; i++){
        if (data.content[i].type === 'text'){ text += data.content[i].text; }
      }
    }

    return new Response(JSON.stringify({ text: text }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e && e.message ? e.message : e) }), { status: 500 });
  }
};

export const config = { path: '/api/chat' };
