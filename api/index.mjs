import { randomUUID } from 'node:crypto';

const json = (response, status, value) => {
  response.statusCode = status;
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('Cache-Control', 'no-store');
  response.end(JSON.stringify(value));
};

const readBody = async (request, limit = 10 * 1024 * 1024) => {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > limit) throw Object.assign(new Error('Файл превышает лимит 10 МБ.'), { status: 413 });
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
};

const configuration = () => {
  const supabaseUrl = (process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL)?.replace(/\/$/, '');
  const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_KEY || process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  const openrouterKey = process.env.OPENROUTER_API_KEY;
  const bucket = process.env.SUPABASE_BUCKET || 'htr-uploads';
  if (!supabaseUrl || !supabaseKey) {
    throw Object.assign(new Error('Supabase URL или API key не настроены в переменных окружения.'), { status: 500 });
  }
  return { supabaseUrl, supabaseKey, openrouterKey, bucket };
};

const storageHeaders = (key, contentType) => ({
  apikey: key,
  Authorization: `Bearer ${key}`,
  ...(contentType ? { 'Content-Type': contentType } : {}),
});

const restHeaders = (key) => ({
  apikey: key,
  Authorization: `Bearer ${key}`,
  'Content-Type': 'application/json',
  Accept: 'application/json',
});

const storageUrl = ({ supabaseUrl, bucket }, key) =>
  `${supabaseUrl}/storage/v1/object/${encodeURIComponent(bucket)}/${key.split('/').map(encodeURIComponent).join('/')}`;

const restUrl = ({ supabaseUrl }, table, query = '') =>
  `${supabaseUrl}/rest/v1/${table}${query ? `?${query}` : ''}`;

const getSessionId = (request) =>
  String(request.headers['x-session-id'] || 'guest').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 64) || 'guest';

const ensureSession = async (config, sessionId) => {
  try {
    await fetch(restUrl(config, 'access_sessions'), {
      method: 'POST',
      headers: { ...restHeaders(config.supabaseKey), Prefer: 'resolution=merge-duplicates' },
      body: JSON.stringify({ id: sessionId }),
    });
  } catch (err) {
    console.warn('ensureSession warning:', err);
  }
};

const listDocuments = async (request, response) => {
  const config = configuration();
  const session = getSessionId(request);
  const upstream = await fetch(
    restUrl(config, 'documents', `owner_session_id=eq.${encodeURIComponent(session)}&deleted_at=is.null&order=created_at.desc&select=*`),
    { headers: restHeaders(config.supabaseKey) }
  );
  if (!upstream.ok) {
    const errText = await upstream.text();
    console.error('Supabase listDocuments error:', errText);
    return json(response, 200, []);
  }
  const documents = await upstream.json();
  json(response, 200, Array.isArray(documents) ? documents : []);
};

const getDocument = async (request, response, documentId) => {
  const config = configuration();
  const upstream = await fetch(
    restUrl(config, 'documents', `id=eq.${encodeURIComponent(documentId)}&select=*,assets(*),pages(*)`),
    { headers: restHeaders(config.supabaseKey) }
  );
  if (!upstream.ok) {
    throw Object.assign(new Error(`Документ не найден в Supabase.`), { status: 404 });
  }
  const items = await upstream.json();
  if (!items || !items.length) {
    throw Object.assign(new Error('Документ не найден.'), { status: 404 });
  }
  json(response, 200, items[0]);
};

const deleteDocument = async (request, response, documentId) => {
  const config = configuration();
  const upstream = await fetch(
    restUrl(config, 'documents', `id=eq.${encodeURIComponent(documentId)}`),
    {
      method: 'DELETE',
      headers: restHeaders(config.supabaseKey),
    }
  );
  if (!upstream.ok) {
    throw Object.assign(new Error(`Ошибка удаления документа из Supabase: ${await upstream.text()}`), { status: 502 });
  }
  json(response, 200, { success: true });
};

const upload = async (request, response) => {
  const config = configuration();
  const contentType = request.headers['content-type'] || 'application/octet-stream';
  if (!String(contentType).startsWith('image/')) {
    throw Object.assign(new Error('Можно загружать только изображения.'), { status: 415 });
  }
  const bytes = await readBody(request);
  if (!bytes.length) throw Object.assign(new Error('Загруженный файл пуст.'), { status: 422 });

  const session = getSessionId(request);
  const documentId = randomUUID();
  const extension = String(contentType).includes('png') ? 'png' : String(contentType).includes('webp') ? 'webp' : 'jpg';
  const key = `${session}/${documentId}.${extension}`;

  // 1. Upload file to Supabase Storage
  const upstream = await fetch(storageUrl(config, key), {
    method: 'POST',
    headers: { ...storageHeaders(config.supabaseKey, String(contentType)), 'x-upsert': 'true' },
    body: bytes,
  });
  if (!upstream.ok) throw Object.assign(new Error(`Supabase Storage: ${await upstream.text()}`), { status: 502 });

  // 2. Persist document metadata in Supabase PostgreSQL
  await ensureSession(config, session);
  const originalFilename = decodeURIComponent(request.headers['x-original-filename'] || `Скан_${new Date().toISOString().slice(0, 10)}`);
  
  try {
    await fetch(restUrl(config, 'documents'), {
      method: 'POST',
      headers: { ...restHeaders(config.supabaseKey), Prefer: 'return=minimal' },
      body: JSON.stringify({
        id: documentId,
        owner_session_id: session,
        title: originalFilename,
        status: 'draft',
      }),
    });

    await fetch(restUrl(config, 'assets'), {
      method: 'POST',
      headers: { ...restHeaders(config.supabaseKey), Prefer: 'return=minimal' },
      body: JSON.stringify({
        id: documentId,
        owner_session_id: session,
        document_id: documentId,
        storage_key: key,
        sha256: documentId,
        byte_size: bytes.length,
        media_type: contentType,
        original_filename: originalFilename,
      }),
    });

    await fetch(restUrl(config, 'pages'), {
      method: 'POST',
      headers: { ...restHeaders(config.supabaseKey), Prefer: 'return=minimal' },
      body: JSON.stringify({
        id: randomUUID(),
        document_id: documentId,
        source_asset_id: documentId,
        page_index: 0,
      }),
    });
  } catch (err) {
    console.warn('Supabase DB metadata insertion warning:', err);
  }

  json(response, 201, {
    document_id: documentId,
    page_id: '1',
    storage_key: key,
    asset: {
      id: documentId,
      media_type: contentType,
      width: 0,
      height: 0,
      preview_url: `/api/v1/assets?storage_key=${encodeURIComponent(key)}`,
    },
  });
};

const download = async (key) => {
  const config = configuration();
  if (!key || key.includes('..')) throw Object.assign(new Error('Некорректный ключ файла.'), { status: 400 });
  const upstream = await fetch(storageUrl(config, key), { headers: storageHeaders(config.supabaseKey) });
  if (!upstream.ok) throw Object.assign(new Error('Изображение не найдено в Supabase Storage.'), { status: 404 });
  return { upstream, bytes: Buffer.from(await upstream.arrayBuffer()), config };
};

const asset = async (requestUrl, response) => {
  const key = requestUrl.searchParams.get('storage_key') || '';
  const { upstream, bytes } = await download(key);
  response.statusCode = 200;
  response.setHeader('Content-Type', upstream.headers.get('content-type') || 'image/jpeg');
  response.setHeader('Cache-Control', 'private, max-age=300');
  response.end(bytes);
};

const recognize = async (request, response, documentId) => {
  const session = getSessionId(request);
  const payload = JSON.parse((await readBody(request, 64 * 1024)).toString('utf8') || '{}');
  const key = String(payload.storage_key || '');
  const { upstream, bytes, config } = await download(key);
  if (!config.openrouterKey) throw Object.assign(new Error('OPENROUTER_API_KEY не настроен.'), { status: 500 });
  const mediaType = upstream.headers.get('content-type') || 'image/jpeg';
  const prompt = [
    'Transcribe all visible handwritten or printed Tajik Cyrillic text.',
    'Preserve line order from top to bottom and return plain text only.',
    'Use Tajik letters ғ, ӣ, қ, ӯ, ҳ, ҷ exactly; do not replace them with Russian letters.',
    'Do not explain, guess hidden text, or add markdown.',
  ].join(' ');

  const ai = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${config.openrouterKey}`,
      'Content-Type': 'application/json',
      'HTTP-Referer': process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : 'https://vercel.app',
      'X-Title': 'Tajik HTR Studio',
    },
    body: JSON.stringify({
      model: process.env.HTR_OCR_MODEL || 'google/gemini-2.5-flash',
      temperature: 0,
      messages: [{ role: 'user', content: [
        { type: 'text', text: prompt },
        { type: 'image_url', image_url: { url: `data:${mediaType};base64,${bytes.toString('base64')}` } },
      ] }],
    }),
  });
  if (!ai.ok) throw Object.assign(new Error(`OpenRouter Gemini: ${await ai.text()}`), { status: 502 });
  const completion = await ai.json();
  const rawText = String(completion?.choices?.[0]?.message?.content || '').trim();
  if (!rawText) throw Object.assign(new Error('Модель вернула пустой текст.'), { status: 502 });
  const lines = rawText.split(/\r?\n/).map((text, index) => ({ id: `${documentId}-${index + 1}`, position: index + 1, text })).filter(line => line.text.trim());

  // Update Supabase document status and save raw result
  try {
    await fetch(restUrl(config, 'documents', `id=eq.${encodeURIComponent(documentId)}`), {
      method: 'PATCH',
      headers: { ...restHeaders(config.supabaseKey), Prefer: 'return=minimal' },
      body: JSON.stringify({ status: 'ready', updated_at: new Date().toISOString() }),
    });

    await fetch(restUrl(config, 'page_raw_results'), {
      method: 'POST',
      headers: { ...restHeaders(config.supabaseKey), Prefer: 'return=minimal' },
      body: JSON.stringify({
        id: randomUUID(),
        recognition_run_id: randomUUID(),
        page_id: '1',
        owner_session_id: session,
        raw_text: rawText,
      }),
    });
  } catch (err) {
    console.warn('Supabase recognition persistence warning:', err);
  }

  json(response, 200, { document_id: documentId, page_id: '1', raw_text: rawText, lines });
};

export default async function handler(request, response) {
  const requestUrl = new URL(request.url, 'https://vercel.local');
  const path = `/${requestUrl.searchParams.get('path') || ''}`.replace(/\/{2,}/g, '/').replace(/\/$/, '') || '/';
  try {
    if (request.method === 'GET' && path === '/v1/health') {
      return json(response, 200, {
        status: 'ok',
        runtime: 'vercel-node',
        database: 'supabase-postgresql',
        storage: 'supabase-storage',
        ocr: 'gemini',
      });
    }
    if (request.method === 'GET' && path === '/v1/documents') return await listDocuments(request, response);
    if (request.method === 'POST' && path === '/v1/documents/upload') return await upload(request, response);
    if (request.method === 'GET' && path === '/v1/assets') return await asset(requestUrl, response);
    
    const docMatch = path.match(/^\/v1\/documents\/([^/]+)$/);
    if (docMatch) {
      if (request.method === 'GET') return await getDocument(request, response, docMatch[1]);
      if (request.method === 'DELETE') return await deleteDocument(request, response, docMatch[1]);
    }

    const recognition = path.match(/^\/v1\/documents\/([^/]+)\/pages\/[^/]+\/recognize$/);
    if (request.method === 'POST' && recognition) return await recognize(request, response, recognition[1]);
    
    return json(response, 404, { message: 'API route not found.' });
  } catch (error) {
    console.error(error);
    return json(response, error.status || 500, { message: error.message || 'Internal server error.' });
  }
}
