import assert from 'node:assert/strict';
const base = process.env.CAISSA_URL ?? 'http://127.0.0.1:8765';
const initial = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const session = await (await fetch(base + '/api/session')).json();
const headers = { 'Content-Type': 'application/json', 'X-Caissa-Token': session.token, 'X-Caissa-Session': session.session };
async function post(path, data, expected = 200) {
  const response = await fetch(base + '/api/' + path, { method: 'POST', headers, body: JSON.stringify(data) });
  assert.equal(response.status, expected, await response.clone().text()); return response;
}
const position = await (await post('state', { fen: initial })).json(); assert.equal(position.moves.length, 20);
const moved = await (await post('move', { fen: initial, move: 'e2e4' })).json(); assert.equal(moved.san, 'e4');
assert.match(moved.fen, / b KQkq e3 0 1$/);
const game = await (await post('pgn', { pgn: '1. e4 (1. d4 d5) e5 2. Nf3 *' })).json(); assert.equal(game.nodes.length, 6);
const round = await (await post('pgn', { pgn: game.pgn })).json(); assert.equal(round.pgn, game.pgn);
await post('state', { fen: 'invalid' }, 400); await post('move', { fen: initial, move: 'a1a8' }, 400);
const controller = new AbortController();
const response = await fetch(base + '/api/analyze', { method: 'POST', headers, signal: controller.signal, body: JSON.stringify({ fen: initial, moves: ['e2e4', 'e7e5'], chess960: false, threads: 1, hash: 16, multipv: 3, milliseconds: 3000 }) });
assert.equal(response.status, 200); const reader = response.body.getReader(); const decoder = new TextDecoder(); let text = '';
while (!text.includes('event: info')) { const result = await reader.read(); assert(!result.done); text += decoder.decode(result.value); }
assert.match(text, /"pv":\[/); controller.abort();
await new Promise((resolve) => setTimeout(resolve, 350));
const health = await (await fetch(base + '/api/health', { headers })).json(); assert.equal(health.analyses, 0);
const malicious = await fetch(base + '/api/state', { method: 'POST', headers: { ...headers, Origin: 'http://hostile.invalid' }, body: JSON.stringify({ fen: initial }) }); assert.equal(malicious.status, 403);
const missing = await fetch(base + '/api/state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fen: initial }) }); assert.equal(missing.status, 403);
console.log(JSON.stringify({ status: 'passed', nativePosition: true, nativePGN: true, nativeAnalysis: true, cancellationCleanup: true, malformedInput: true, tokenAndOrigin: true }));
