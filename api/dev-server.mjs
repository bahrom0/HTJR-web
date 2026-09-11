import http from 'node:http';
import handler from './index.mjs';

const port = Number(process.env.API_PORT || 8787);
const server = http.createServer((request, response) => {
  const incoming = new URL(request.url || '/', 'http://127.0.0.1');
  if (incoming.pathname.startsWith('/api/')) {
    incoming.searchParams.set('path', incoming.pathname.slice('/api/'.length));
    request.url = `/api/index?${incoming.searchParams.toString()}`;
  }
  void handler(request, response);
});

server.listen(port, '127.0.0.1', () => {
  console.log(`Tajik HTR API ready on http://127.0.0.1:${port}`);
});
