// Real Chromium, production HTTP routes and original native processes only.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { chromium } from 'playwright';
import { observeNativeStreams } from './browser_stream_capture.mjs';

const root = resolve(process.argv[2]);
const config = JSON.parse(await readFile(root + '/CONFIG.json', 'utf8'));
const port = 18771, base = `http://127.0.0.1:${port}`;
const start = Date.now(), pending = new Set();
let browser, server, context, logs = '', bytes = 0;
const deadline = setTimeout(() => { server?.kill('SIGKILL'); process.exitCode = 1; void browser?.close(); }, 230000);
const records = [], requests = [], errors = [];
const delay = (ms) => new Promise((done) => setTimeout(done, ms));
async function poll(work, message, ms = 8000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (await work()) return; await delay(30); }
  throw new Error(message);
}
async function stopServer() {
  if (!server) return;
  const owned = server; server = undefined;
  const exited = once(owned, 'close'); owned.kill('SIGTERM');
  const timer = setTimeout(() => owned.kill('SIGKILL'), 1500);
  try { await exited; } finally { clearTimeout(timer); }
}
async function startServer(mode) {
  server = spawn(process.execPath, ['dist/analysis-service/server.js'], {
    env: { ...process.env, PORT: String(port), CAISSA_ENGINE: config.engine,
      CAISSA_NETWORK: mode === 'neural' ? config.network : '' }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  for (const pipe of [server.stdout, server.stderr]) pipe.on('data', (chunk) => {
    logs += chunk.toString(); if (logs.length > 1048576) server?.kill('SIGKILL');
  });
  await poll(async () => {
    try { return (await fetch(base + '/api/session', { signal: AbortSignal.timeout(300) })).ok; } catch { return false; }
  }, 'Real service did not become ready.');
}
async function snapshot(page, name, mode, width, extra = {}) {
  const value = await page.evaluate(() => ({
    fen: document.querySelector('#fen').value,
    status: document.querySelector('#status').textContent,
    error: document.querySelector('#status').classList.contains('error'),
    engine: document.querySelector('#engine-label').textContent,
    cells: [...document.querySelectorAll('#board [data-square]')].map((cell) => ({
      square: cell.dataset.square, label: cell.getAttribute('aria-label'), tab: cell.tabIndex,
    })),
    focus: document.activeElement?.getAttribute('data-square'),
    lines: [...document.querySelectorAll('.pv-path')].map((line) => line.textContent),
    depth: document.querySelector('#depth').textContent, nodes: document.querySelector('#nodes').textContent,
    nps: document.querySelector('#nps').textContent, state: document.querySelector('#analysis-state').textContent,
    pgn: document.querySelector('#pgn').value, storage: localStorage.getItem('caissa-game-v1'),
    scrollWidth: document.documentElement.scrollWidth, innerWidth,
    resources: Object.fromEntries(['time', 'threads', 'multipv', 'hash'].map((id) => [id, document.getElementById(id).value])),
  }));
  records.push({ name, mode, width, ...value, ...extra });
  if (['import', 'keyboard-edit', 'analysis', 'restored'].includes(name))
    await page.screenshot({ path: `${root}/${mode}-${width}/${name}.png`, fullPage: true });
  assert(value.scrollWidth <= width, 'Page has horizontal overflow.');
  return value;
}
async function exercise(mode, width) {
  const folder = `${root}/${mode}-${width}`; await mkdir(folder);
  context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  const page = await context.newPage(); page.setDefaultTimeout(8000);
  await observeNativeStreams(page, base, (row) => {
    bytes += row.body_bytes ?? 0;
    if (bytes > 32 * 1024 * 1024) throw new Error('Browser network evidence exceeded its ceiling.');
    requests.push({ mode, width, ...row });
  });
  async function idle(name) {
    const sessionRow = requests.find((r) => r.mode === mode && r.width === width && r.url === '/api/session' && r.body);
    assert(sessionRow); const session = JSON.parse(sessionRow.body);
    let health;
    await poll(async () => {
      const response = await fetch(base + '/api/health', { headers: { 'x-caissa-token': session.token,
        'x-caissa-session': session.session }, signal: AbortSignal.timeout(500) });
      assert.equal(response.status, 200); health = await response.json();
      return health.analyses === 0 && health.positions === 0;
    }, 'Cancelled native worker was not reaped.', 1500);
    records.push({ name, mode, width, health });
  }
  page.on('pageerror', (error) => errors.push({ mode, width, message: error.message }));
  page.on('response', (response) => {
    if (!response.url().startsWith(base + '/api/')) return;
    if (new URL(response.url()).pathname === '/api/analyze') return;
    const task = (async () => {
      const request = response.request(); const row = { mode, width, url: new URL(response.url()).pathname,
        method: request.method(), status: response.status(), request: request.postData(), headers: request.headers() };
      try {
        const failure = await response.finished(); if (failure) throw failure;
        row.body = await response.text(); row.transport_complete = true;
        row.body_bytes = Buffer.byteLength(row.body); bytes += row.body_bytes;
      } catch (error) {
        row.aborted = true; row.transport_complete = false;
        row.capture_error = { name: String(error?.name ?? 'Error').slice(0, 80), message: String(error?.message ?? error).slice(0, 512) };
      }
      if (bytes > 32 * 1024 * 1024) throw new Error('Browser network evidence exceeded its ceiling.');
      requests.push(row);
    })();
    pending.add(task); void task.finally(() => pending.delete(task));
  });
  await page.goto(base);
  await page.waitForFunction(() => document.querySelectorAll('#board button').length === 64 && document.querySelector('#status').textContent.includes('Select a piece'));
  await snapshot(page, 'fresh', mode, width);
  await page.locator('.moves-panel > details > summary').click();
  await page.locator('#pgn').fill('[Event "Caissa browser integration"]\n\n1. e4 (1. d4 d5) e5 2. Nf3 *');
  await page.locator('#import-pgn').click();
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('Imported 5'));
  await snapshot(page, 'import', mode, width);
  const c2 = page.locator('[data-square="c2"]'); await c2.focus(); await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelector('[data-square="c2"]').classList.contains('selected'));
  await page.keyboard.press('ArrowUp'); await page.keyboard.press('ArrowUp'); await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelector('#fen').value.startsWith('rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/'));
  const edited = await snapshot(page, 'keyboard-edit', mode, width); assert.equal(edited.focus, 'c4');
  await page.locator('#new-variation').click(); await page.locator('#export-pgn').click();
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('Exported'));
  const exported = await snapshot(page, 'export', mode, width);
  await page.locator('#flip').click(); const flipped = await snapshot(page, 'flip', mode, width); assert.equal(flipped.cells[0].square, 'h1');
  await page.locator('#flip').click();
  for (const [id, value] of Object.entries({ time: '1000', threads: '1', multipv: '3', hash: '16' })) await page.locator('#' + id).selectOption(value);
  await page.locator('#inspect-search').check();
  await page.locator('#analyze').click();
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('Analysis complete.'));
  await poll(() => requests.some((row) => row.mode === mode && row.width === width && row.url === '/api/analyze'
    && row.transport_complete === true && JSON.parse(row.request).milliseconds === 1000 && row.body.includes('event: bestmove')),
  'Original completed native analysis response was not fully captured.');
  const analysis = await snapshot(page, 'analysis', mode, width); assert(analysis.lines.length > 0); assert.notEqual(analysis.nodes, '0');
  assert.equal(analysis.state, 'READY');
  await page.locator('#time').selectOption('30000'); await page.locator('#analyze').click();
  await page.waitForFunction(() => document.querySelector('#cancel').disabled === false && document.querySelectorAll('.pv-path').length > 0);
  const stopped = Date.now(); await page.locator('#cancel').click();
  await page.waitForFunction(() => document.querySelector('#analysis-state').textContent === 'READY');
  await snapshot(page, 'cancel', mode, width, { elapsed_ms: Date.now() - stopped });
  await idle('cancel-reaped');
  await page.locator('#analyze').click(); await page.waitForFunction(() => !document.querySelector('#cancel').disabled);
  await page.locator('#first').click(); await delay(400);
  const changed = await snapshot(page, 'position-change', mode, width);
  assert.equal(changed.nodes, '0'); assert.equal(changed.depth, '0 / 0'); assert.equal(changed.lines.length, 0);
  await idle('navigation-reaped');
  await page.locator('#fen').fill('this is not a chess position'); await page.locator('#load-fen').click();
  await page.waitForFunction(() => document.querySelector('#status').classList.contains('error'));
  await snapshot(page, 'malformed-fen', mode, width);
  await page.locator('#fen').fill(edited.fen); await page.locator('#load-fen').click();
  await page.waitForFunction(() => document.querySelector('#status').textContent.includes('Select a piece'));
  // Restore the edited original tree, then exercise process restart and browser
  // persistence. No route interception, response substitution or clock mocks.
  await page.locator('#pgn').fill(exported.pgn); await page.locator('#import-pgn').click();
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('Imported'));
  await page.locator('#next').click(); await page.waitForFunction((fen) => document.querySelector('#fen').value === fen, edited.fen);
  const oldSession = requests.find((r) => r.mode === mode && r.width === width && r.url === '/api/session' && r.body);
  assert(oldSession); const previous = JSON.parse(oldSession.body);
  await stopServer(); await startServer(mode);
  const stale = await fetch(base + '/api/state', { method: 'POST', headers: { 'content-type': 'application/json',
    'x-caissa-token': previous.token, 'x-caissa-session': previous.session }, body: JSON.stringify({ fen: edited.fen }), signal: AbortSignal.timeout(1500) });
  const staleBody = await stale.text(); assert.equal(stale.status, 403);
  records.push({ name: 'stale-session', mode, width, status: stale.status, body: staleBody });
  await page.reload(); await page.waitForFunction((fen) => document.querySelector('#fen').value === fen && document.querySelector('#status').textContent.includes('Select a piece'), edited.fen);
  await snapshot(page, 'restored', mode, width);
  await page.locator('.moves-panel > details > summary').click(); await page.locator('#export-pgn').click();
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('Exported'));
  const final = await snapshot(page, 'final-export', mode, width); assert.equal(final.pgn, exported.pgn);
  await page.evaluate(() => window.__caissaNativeCaptureIdle());
  await context.tracing.stop({ path: folder + '/trace.zip' }); await context.close(); context = undefined;
  await Promise.all([...pending]);
}
try {
  browser = await chromium.launch({ headless: true });
  for (const mode of ['classical', 'neural']) {
    await startServer(mode);
    for (const width of [1280, 390]) await exercise(mode, width);
    await stopServer();
  }
  assert.equal(errors.length, 0, JSON.stringify(errors));
  await writeFile(root + '/BROWSER.json', JSON.stringify({ schema: 'caissa-browser-observations-v1', browser: browser.version(), elapsed_ms: Date.now() - start, records, errors }, null, 2));
  console.log(JSON.stringify({ status: 'recorded', contexts: 4, records: records.length, full_G12_certified: false }));
} finally {
  if (context) { await context.tracing.stop({ path: root + '/failed-trace.zip' }).catch(() => {}); await context.close(); }
  await stopServer(); await browser?.close(); await Promise.allSettled([...pending]); clearTimeout(deadline);
  await writeFile(root + '/NETWORK.json', JSON.stringify(requests));
  await writeFile(root + '/service.log', logs);
  await writeFile(root + '/ERRORS.json', JSON.stringify(errors));
}
