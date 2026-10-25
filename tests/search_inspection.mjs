import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { parseStatistics, parseTrace } from '../dist/analysis-service/telemetry.js';

const output = resolve(process.argv[2]);
await mkdir(output, { recursive: false });
const engine = resolve(process.env.CAISSA_ENGINE ?? 'build-search-context/caissa');
const initial = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const observations = [];
async function fixedProbe(tracing) {
  return await new Promise((accept, reject) => {
    const child = spawn(engine, [], { stdio: 'pipe' }); const lines = []; let buffer = '', best = false;
    const timer = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('Finite native inspection probe timed out.')); }, 5000);
    child.on('error', reject);
    child.stderr.on('data', () => {});
    child.stdout.on('data', (chunk) => {
      buffer += chunk.toString();
      if (buffer.length > 1024 * 1024) { child.kill('SIGKILL'); reject(new Error('Native inspection byte limit.')); return; }
      let end;
      while ((end = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, end).trim(); buffer = buffer.slice(end + 1); lines.push(line);
        if (line === 'uciok') child.stdin.write(`setoption name Threads value 1\nsetoption name Hash value 16\nsetoption name Search Stats value true\nsetoption name Trace Samples value ${tracing ? 8 : 0}\nisready\n`);
        if (line === 'readyok') child.stdin.write('position startpos\ngo nodes 10000\n');
        if (line.startsWith('bestmove ')) { best = true; child.stdin.end('quit\n'); }
      }
    });
    child.on('close', (code) => { clearTimeout(timer); if (code !== 0 || !best) reject(new Error('Native inspection probe did not complete.')); else accept(lines); });
    child.stdin.write('uci\n');
  });
}
const plain = await fixedProbe(false), traced = await fixedProbe(true);
await writeFile(output + '/native-plain.json', JSON.stringify(plain));
await writeFile(output + '/native-traced.json', JSON.stringify(traced));
const stableInfo = (lines) => lines.filter((line) => line.startsWith('info depth ')).map((line) => line.replace(/ time \d+/, '').replace(/ nps \d+/, ''));
assert.deepEqual(stableInfo(plain), stableInfo(traced));
assert.equal(plain.at(-1), traced.at(-1));
const summaryLine = traced.find((line) => line.startsWith('info string stats ')); assert(summaryLine);
const statistics = parseStatistics(summaryLine); assert.equal(statistics.visited_nodes, 10000);
for (const key of ['accumulator_pushes', 'accumulator_materializations', 'accumulator_copies', 'accumulator_refreshes', 'accumulator_delta_squares']) assert.equal(statistics[key], 0);
const stableCounters = (value) => Object.fromEntries(Object.entries(value).filter(([key]) => !['elapsed_ms', 'eval_ns'].includes(key)));
assert.deepEqual(stableCounters(parseStatistics(plain.find((line) => line.startsWith('info string stats ')))), stableCounters(statistics));
const traceLines = traced.filter((line) => line.startsWith('info string trace ')); assert.equal(traceLines.length, 8);
for (const line of traceLines) parseTrace(line);
assert(!plain.some((line) => line.startsWith('info string trace ')));
observations.push({ case: 'native-inspection-fixed-node-parity', nodes: 10000, samples: traceLines.length });
let rejections = 0;
for (const bad of [summaryLine.replace('visited_nodes 10000', 'visited_nodes -1'), summaryLine.replace('visited_nodes 10000', 'visited_nodes 9007199254740993'), summaryLine + ' extra 0', summaryLine.replace('qnodes ', 'visited_nodes '), summaryLine.replace(/ elapsed_ms \d+/, ''), summaryLine.replace('table_bytes ', 'table_bytes NaN ')]) {
  assert.throws(() => parseStatistics(bad)); rejections++;
}
for (const bad of [traceLines[0].replace('synthetic 0', 'synthetic 2'), traceLines[0].replace(/alpha -?\d+ beta -?\d+/, 'alpha 5 beta 5'), traceLines[0] + '\nuci', traceLines[0].replace(/depth \d+/, 'depth 65')]) {
  assert.throws(() => parseTrace(bad)); rejections++;
}
observations.push({ case: 'malformed-native-telemetry-rejected', rejections });

const port = 18767, base = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ['dist/analysis-service/server.js'], { env: { ...process.env, PORT: String(port), CAISSA_ENGINE: engine }, stdio: ['ignore', 'pipe', 'pipe'] });
let logs = '';
for (const pipe of [server.stdout, server.stderr]) pipe.on('data', (chunk) => { logs += chunk.toString(); if (logs.length > 65536) server.kill('SIGKILL'); });
try {
  let session;
  for (let i = 0; i < 50; i++) {
    try { const response = await fetch(base + '/api/session', { signal: AbortSignal.timeout(500) }); if (response.ok) { session = await response.json(); break; } } catch {}
    await new Promise((done) => setTimeout(done, 100));
  }
  assert(session, 'Finite inspection service readiness failed.');
  const headers = { 'Content-Type': 'application/json', 'X-Caissa-Token': session.token, 'X-Caissa-Session': session.session };
  const request = { fen: initial, moves: ['e2e4', 'e7e5'], chess960: false, threads: 1, hash: 16, multipv: 2, milliseconds: 250 };
  async function search(label, config) {
    const response = await fetch(base + '/api/analyze', { method: 'POST', headers, body: JSON.stringify(config), signal: AbortSignal.timeout(5000) });
    assert.equal(response.status, 200); const raw = await response.text();
    await writeFile(output + '/' + label + '.sse', raw);
    const events = raw.trim().split('\n\n').map((frame) => ({ event: frame.split('\n')[0].slice(7), value: JSON.parse(frame.split('\n')[1].slice(6)) }));
    assert(!events.some((row) => row.event === 'error'), raw); assert(events.some((row) => row.event === 'bestmove'));
    return events;
  }
  const disabled = await search('default', request);
  assert(!disabled.some((row) => ['statistics', 'trace'].includes(row.event)));
  for (const threads of [1, 4]) {
    const events = await search('inspected-' + threads, { ...request, inspect: true, threads });
    const stats = events.filter((row) => row.event === 'statistics'); assert.equal(stats.length, 1);
    assert(stats[0].value.visited_nodes > 0 && stats[0].value.completed_depth_nodes <= stats[0].value.visited_nodes);
    const samples = events.filter((row) => row.event === 'trace'); assert(samples.length > 0 && samples.length <= 8 * threads);
    assert(events.findIndex((row) => row.event === 'statistics') < events.findIndex((row) => row.event === 'trace'));
    for (const sample of samples.slice(0, 3)) {
      const state = await fetch(base + '/api/state', { method: 'POST', headers, body: JSON.stringify({ fen: sample.value.fen }), signal: AbortSignal.timeout(5000) });
      assert.equal(state.status, 200, await state.text());
    }
    observations.push({ case: 'actual-inspection-stream', threads, visited: stats[0].value.visited_nodes, samples: samples.length });
  }
  const terminal = await search('terminal', { ...request, inspect: true, moves: [], fen: '7k/6Q1/5K2/8/8/8/8/8 b - - 150 80' });
  assert.equal(terminal.find((row) => row.event === 'statistics').value.visited_nodes, 0);
  assert.equal(terminal.find((row) => row.event === 'bestmove').value.move, '0000');
  assert(!terminal.some((row) => row.event === 'trace'));
  const invalid = await fetch(base + '/api/analyze', { method: 'POST', headers, body: JSON.stringify({ ...request, inspect: 'yes' }), signal: AbortSignal.timeout(5000) });
  assert.equal(invalid.status, 400);
  const controller = new AbortController(); const response = await fetch(base + '/api/analyze', { method: 'POST', headers, signal: controller.signal, body: JSON.stringify({ ...request, inspect: true, milliseconds: 30000 }) });
  const reader = response.body.getReader(); let partial = '';
  while (!partial.includes('event: info')) { const block = await reader.read(); assert(!block.done); partial += new TextDecoder().decode(block.value); }
  controller.abort(); await writeFile(output + '/cancelled.sse', partial);
  let health;
  for (let i = 0; i < 40; i++) {
    health = await (await fetch(base + '/api/health', { headers, signal: AbortSignal.timeout(1000) })).json();
    if (health.analyses === 0) break; await new Promise((done) => setTimeout(done, 25));
  }
  assert.equal(health.analyses, 0);
  observations.push({ case: 'terminal-zero-summary-invalid-input-and-cancellation', completed: true });
  await writeFile(output + '/SUMMARY.json', JSON.stringify({ status: 'passed', observations, full_acceptance: false }, null, 2) + '\n');
  console.log(JSON.stringify({ status: 'passed', observations, full_acceptance: false }));
} finally {
  server.kill('SIGTERM'); await new Promise((done) => { if (server.exitCode !== null) done(); else { server.once('close', done); setTimeout(() => { server.kill('SIGKILL'); done(); }, 1500).unref(); } });
  await writeFile(output + '/service.log', logs);
}
