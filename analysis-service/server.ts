import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { readFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import { resolve } from 'node:path';
import { analyze, nativeJson, RequestError, shutdown, workerCounts, type AnalysisRequest } from './native.js';

const port = Number(process.env['PORT'] ?? '8765');
const token = randomBytes(24).toString('hex');
const allowedOrigin = `http://127.0.0.1:${port}`;
const sessions = new Map<string, number>();
const rate = new Map<string, { start: number; count: number }>();
function json(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); response.end(JSON.stringify(value));
}
function text(value: unknown, name: string, maximum: number): string {
  if (typeof value !== 'string' || value.length > maximum || value.includes('\0')) throw new RequestError(`${name} exceeds its limit or has the wrong type.`);
  return value;
}
function integer(value: unknown, name: string, low: number, high: number): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < low || value > high) throw new RequestError(`${name} must be in [${low},${high}].`);
  return value;
}
async function body(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = []; let size = 0;
  for await (const chunk of request) {
    const part = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk as string); size += part.length;
    if (size > 1024 * 1024) throw new RequestError('Request body exceeds 1 MiB.', 413); chunks.push(part);
  }
  let result: unknown; try { result = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw new RequestError('Malformed JSON.'); }
  if (typeof result !== 'object' || result === null || Array.isArray(result)) throw new RequestError('Request object required.');
  return result as Record<string, unknown>;
}
function authorize(request: IncomingMessage): void {
  if (request.headers.origin && request.headers.origin !== allowedOrigin) throw new RequestError('Origin rejected.', 403);
  if (request.headers['x-caissa-token'] !== token) throw new RequestError('Local session token missing.', 403);
  const key = String(request.headers['x-caissa-session'] ?? '');
  if (!sessions.has(key)) throw new RequestError('Session expired. Reload the page.', 403);
  const now = Date.now(); sessions.set(key, now);
  let current = rate.get(key); if (!current || now - current.start > 1000) { current = { start: now, count: 0 }; rate.set(key, current); }
  if (++current.count > 30) throw new RequestError('Session request rate exceeded.', 429);
}
function analysisRequest(data: Record<string, unknown>): AnalysisRequest {
  const fen = text(data['fen'], 'FEN', 256);
  if (/[\r\n]/.test(fen)) throw new RequestError('FEN contains command delimiters.');
  const moves = data['moves'];
  if (!Array.isArray(moves) || moves.length > 512 || !moves.every((m: unknown) => typeof m === 'string' && /^[a-h][1-8][a-h][1-8][nbrq]?$/.test(m))) throw new RequestError('Invalid move path.');
  if (data['inspect'] !== undefined && typeof data['inspect'] !== 'boolean') throw new RequestError('Inspect search must be a boolean.');
  return { fen, moves: moves as string[], chess960: data['chess960'] === true, threads: integer(data['threads'], 'Threads', 1, 4), hash: integer(data['hash'], 'Hash', 1, 128), multipv: integer(data['multipv'], 'MultiPV', 1, 8), milliseconds: integer(data['milliseconds'], 'Analysis time', 50, 30000), inspect: data['inspect'] === true };
}
async function route(request: IncomingMessage, response: ServerResponse): Promise<void> {
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.setHeader('Referrer-Policy', 'no-referrer');
  response.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'");
  const path = new URL(request.url ?? '/', allowedOrigin).pathname;
  if (request.method === 'GET' && path === '/api/session') {
    if (request.headers.origin && request.headers.origin !== allowedOrigin) throw new RequestError('Origin rejected.', 403);
    for (const [id, time] of sessions) if (Date.now() - time > 3600000) { sessions.delete(id); rate.delete(id); }
    if (sessions.size >= 64) throw new RequestError('Local session limit exceeded.', 429);
    const id = randomBytes(16).toString('hex'); sessions.set(id, Date.now()); json(response, 200, { token, session: id, engine: 'Caissa', evaluation: 'classical' }); return;
  }
  if (path.startsWith('/api/')) {
    authorize(request);
    if (request.method === 'GET' && path === '/api/health') { json(response, 200, workerCounts()); return; }
    if (request.method !== 'POST') throw new RequestError('Method not allowed.', 405);
    const data = await body(request);
    if (path === '/api/pgn') { json(response, 200, await nativeJson(['--pgn-json'], text(data['pgn'], 'PGN', 1024 * 1024))); return; }
    if (path === '/api/state') {
      const fen = text(data['fen'], 'FEN', 256); if (/[\r\n]/.test(fen)) throw new RequestError('Invalid FEN delimiters.');
      const result = await nativeJson(['--inspect'], (data['chess960'] === true ? '960|' : '') + fen + '\n');
      if (typeof result === 'object' && result !== null && 'error' in result) throw new RequestError('Invalid FEN.'); json(response, 200, result); return;
    }
    if (path === '/api/move') {
      const args = ['--move-json', text(data['fen'], 'FEN', 256), text(data['move'], 'Move', 5)]; if (data['chess960'] === true) args.push('960');
      json(response, 200, await nativeJson(args)); return;
    }
    if (path === '/api/analyze') {
      const config = analysisRequest(data);
      // Check the exact root before reserving a persistent analysis worker.
      const position = await nativeJson(['--inspect'], (config.chess960 ? '960|' : '') + config.fen + '\n');
      if (typeof position === 'object' && position !== null && 'error' in position) throw new RequestError('Invalid analysis FEN.');
      let ended = false;
      const handle = analyze(config, (event, value) => {
        if (ended || response.destroyed) return false;
        return response.write(`event: ${event}\ndata: ${JSON.stringify(value)}\n\n`);
      }, () => { ended = true; response.end(); });
      response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' }); response.flushHeaders();
      response.on('close', () => { ended = true; handle.cancel(); }); return;
    }
    throw new RequestError('API route not found.', 404);
  }
  if (request.method !== 'GET') throw new RequestError('Method not allowed.', 405);
  const staticFiles: Record<string, [string, string]> = { '/': ['web/index.html', 'text/html'], '/style.css': ['web/style.css', 'text/css'], '/app.js': ['dist/web/app.js', 'text/javascript'] };
  const resource = staticFiles[path]; if (!resource) throw new RequestError('Page not found.', 404);
  const bytes = await readFile(resolve(resource[0])); response.writeHead(200, { 'Content-Type': resource[1], 'Cache-Control': 'no-store' }); response.end(bytes);
}
const server = createServer((request, response) => {
  void route(request, response).catch((error: unknown) => {
    if (response.headersSent) { response.end(); return; }
    const known = error instanceof RequestError; json(response, known ? error.status : 500, { error: known ? error.message : 'Local service failed.' });
  });
});
server.maxConnections = 64;
server.requestTimeout = 10000; server.headersTimeout = 5000; server.maxHeadersCount = 32;
server.listen(port, '127.0.0.1', () => console.log(`Caissa analysis: ${allowedOrigin}`));
for (const signal of ['SIGTERM', 'SIGINT'] as const) process.on(signal, () => { shutdown(); server.close(); setTimeout(() => process.exit(0), 500).unref(); });
