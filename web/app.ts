interface TreeNode { id: number; parent: number; fen: string; san: string; uci: string; comment: string; children: number[]; nags: number[]; }
interface Game { initial: string; chess960: boolean; result: string; tags: Record<string, string>; nodes: TreeNode[]; pgn?: string; }
interface PositionState { fen: string; check: boolean; moves: string[]; }
interface Line { depth?: number; seldepth?: number; multipv?: number; scoreType?: string; score?: number; nodes?: number; nps?: number; pv?: string[]; bound?: string; }
interface Session { token: string; session: string; engine: string; evaluation: string; }
const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const symbols: Record<string, string> = { K: '♚', Q: '♛', R: '♜', B: '♝', N: '♞', P: '♟', k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟' };
const names: Record<string, string> = { k: 'king', q: 'queen', r: 'rook', b: 'bishop', n: 'knight', p: 'pawn' };
function element<T extends HTMLElement>(id: string): T { const found = document.getElementById(id); if (!found) throw new Error(`Missing element ${id}`); return found as T; }
function emptyGame(fen = START, chess960 = false): Game { return { initial: fen, chess960, result: '*', tags: {}, nodes: [{ id: 0, parent: 0, fen, san: '', uci: '', comment: '', children: [], nags: [] }] }; }
let game = emptyGame(), current = 0, flipped = false, selected: string | undefined, legal: string[] = [], session: Session;
let generation = 0, playing = 0, active: AbortController | undefined;
const variations = new Map<number, Line>();
let evaluations: { node: number; cp: number }[] = [];
const board = element('board');
function status(message: string, error = false): void { const target = element('status'); target.textContent = message; target.classList.toggle('error', error); }
function safe(work: () => Promise<void>): void { void work().catch((error: unknown) => status(error instanceof Error ? error.message : 'Operation failed.', true)); }
async function api<T>(path: string, value: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Caissa-Token': session.token, 'X-Caissa-Session': session.session }, body: JSON.stringify(value) });
  const data = await response.json() as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof data['error'] === 'string' ? data['error'] : 'Local engine request failed.');
  return data as T;
}
function node(id = current): TreeNode { const result = game.nodes[id]; if (!result) throw new Error('Variation node is missing.'); return result; }
function save(): void { try { localStorage.setItem('caissa-game-v1', JSON.stringify({ version: 2, pgn: pgnText(), path: movePath(), evaluations: evaluations.slice(-60) })); } catch { status('Position is usable, but browser storage is full.', true); } }
function pieces(fen: string): Map<string, string> {
  const map = new Map<string, string>(); let rank = 8, file = 0;
  for (const ch of fen.split(' ')[0] ?? '') {
    if (ch === '/') { rank--; file = 0; }
    else if (/\d/.test(ch)) file += Number(ch);
    else { map.set(String.fromCharCode(97 + file) + rank, ch); file++; }
  }
  return map;
}
function boardSquares(): string[] {
  const result: string[] = [];
  for (let r = 0; r < 8; r++) for (let f = 0; f < 8; f++) result.push(String.fromCharCode(97 + (flipped ? 7 - f : f)) + (flipped ? r + 1 : 8 - r));
  return result;
}
function drawBoard(focus?: string): void {
  const map = pieces(node().fen), side = node().fen.split(' ')[1], last = node().uci;
  board.replaceChildren();
  for (const [i, square] of boardSquares().entries()) {
    const piece = map.get(square); const button = document.createElement('button');
    button.type = 'button'; button.className = `square ${(square.charCodeAt(0) + Number(square[1])) % 2 === 0 ? 'dark' : 'light'}`;
    button.dataset['square'] = square; button.setAttribute('role', 'gridcell'); button.tabIndex = square === (focus ?? selected ?? 'e2') ? 0 : -1;
    button.setAttribute('aria-label', `${square}${piece ? ' ' + (piece === piece.toUpperCase() ? 'white ' : 'black ') + names[piece.toLowerCase()] : ' empty'}`);
    const targets = selected ? legal.filter((m) => m.slice(0, 2) === selected).map((m) => m.slice(2, 4)) : [];
    button.classList.toggle('selected', square === selected); button.classList.toggle('legal', targets.includes(square)); button.classList.toggle('capture', !!piece);
    button.classList.toggle('last-move', last.slice(0, 2) === square || last.slice(2, 4) === square);
    if (piece) { const span = document.createElement('span'); span.className = `piece ${piece === piece.toUpperCase() ? 'white' : 'black'}`; span.textContent = symbols[piece] ?? ''; button.append(span); }
    if (i >= 56 || i % 8 === 0) { const coordinate = document.createElement('span'); coordinate.className = 'coordinate'; coordinate.textContent = i >= 56 ? square[0] ?? '' : square[1] ?? ''; button.append(coordinate); }
    button.addEventListener('click', () => safe(() => choose(square)));
    button.addEventListener('keydown', (event) => {
      const delta: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -8, ArrowDown: 8 };
      const offset = delta[event.key]; if (offset === undefined) return; event.preventDefault();
      const next = Math.max(0, Math.min(63, i + offset)); const target = board.children[next] as HTMLButtonElement | undefined;
      for (const child of board.children) (child as HTMLButtonElement).tabIndex = -1;
      if (target) { target.tabIndex = 0; target.focus(); }
    }); board.append(button);
  }
  element('turn').textContent = side === 'w' ? 'White to move' : 'Black to move';
  element<HTMLSelectElement>('variant').value = game.chess960 ? 'chess960' : 'standard';
  element('move-number').textContent = 'Move ' + node().fen.split(' ')[5]; element<HTMLInputElement>('fen').value = node().fen;
  if (focus) (board.querySelector(`[data-square="${focus}"]`) as HTMLButtonElement | null)?.focus();
}
async function choose(square: string): Promise<void> {
  if (selected) {
    const choices = legal.filter((move) => move.startsWith(selected + square));
    if (choices.length) {
      let move = choices[0];
      if (choices.length > 1) {
        const dialog = element<HTMLDialogElement>('promotion'); dialog.returnValue = ''; dialog.showModal();
        const promotion = await new Promise<string>((accept) => dialog.addEventListener('close', () => accept(dialog.returnValue), { once: true }));
        if (!promotion) return; move = choices.find((m) => m.endsWith(promotion));
      }
      if (move) await appendMove(move); return;
    }
  }
  const piece = pieces(node().fen).get(square); const ours = piece && (node().fen.split(' ')[1] === 'w' ? piece === piece.toUpperCase() : piece === piece.toLowerCase());
  selected = ours && selected !== square ? square : undefined; drawBoard(square);
}
function cancel(): void { active?.abort(); active = undefined; element<HTMLButtonElement>('cancel').disabled = true; element<HTMLButtonElement>('analyze').disabled = false; element('analysis-state').textContent = 'READY'; element('analysis-state').classList.remove('active'); }
async function selectNode(id: number, manual = true): Promise<void> {
  if (manual) playing++; generation++; const version = generation; cancel(); current = id; selected = undefined; legal = []; variations.clear(); drawLines(); drawBoard(); drawMoves(); save();
  const value = await api<PositionState>('state', { fen: node().fen, chess960: game.chess960 });
  if (version !== generation) return; legal = value.moves; drawBoard();
  status(value.moves.length ? (value.check ? 'Check. Find a legal reply.' : 'Select a piece or start an analysis.') : (value.check ? 'Checkmate.' : 'No legal moves.'));
}
async function appendMove(move: string, playbackId?: number): Promise<void> {
  const parent = current, version = generation; const before = node(parent);
  const value = await api<{ fen: string; san: string }>('move', { fen: before.fen, move, chess960: game.chess960 });
  if (version !== generation || parent !== current) return;
  let child = before.children.find((id) => node(id).uci === move);
  if (child === undefined) {
    if (game.nodes.length >= 2000) throw new Error('Variation limit reached. Export this game before continuing.');
    child = game.nodes.length; game.nodes.push({ id: child, parent, fen: value.fen, san: value.san, uci: move, comment: '', children: [], nags: [] }); before.children.push(child); game.result = '*';
  }
  await selectNode(child, playbackId === undefined);
}
function drawMoves(): void {
  const target = element('moves'); target.replaceChildren();
  if (!node(0).children.length) { target.textContent = 'Your lines will appear here.'; return; }
  function branch(parent: number, container: HTMLElement, firstChild?: number, nesting = 0): void {
    if (nesting > 64) return; let next = firstChild ?? node(parent).children[0];
    while (next !== undefined) {
      const entry = node(next), before = node(entry.parent), fields = before.fen.split(' '); const span = document.createElement('span'); span.className = 'move-entry';
      const number = document.createElement('span'); number.className = 'move-number'; number.textContent = `${fields[5]}${fields[1] === 'w' ? '.' : '…'}`;
      const button = document.createElement('button'); button.textContent = entry.san; button.classList.toggle('current', next === current); button.title = entry.comment;
      const id = next; button.addEventListener('click', () => safe(() => selectNode(id))); span.append(number, button); container.append(span);
      if (before.children[0] === next) for (const sibling of before.children.slice(1)) {
        const alternative = document.createElement('div'); alternative.className = 'variation'; branch(entry.parent, alternative, sibling, nesting + 1); container.append(alternative);
      }
      next = entry.children[0];
    }
  }
  branch(0, target);
}
function drawHistory(): void {
  const values = evaluations.slice(-60); const points = values.map((entry, i) => `${values.length <= 1 ? 220 : i * 440 / (values.length - 1)},${50 - Math.tanh(entry.cp / 500) * 43}`).join(' ');
  element<SVGElement & HTMLElement>('history-line').setAttribute('points', points);
}
function drawLines(): void {
  const target = element('lines'); target.replaceChildren();
  if (!variations.size) { const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'The board is yours. Start an analysis to explore its possibilities.'; target.append(empty); return; }
  for (const [rank, line] of [...variations].sort((a, b) => a[0] - b[0])) {
    const row = document.createElement('div'); row.className = 'pv-line'; const score = document.createElement('strong'); score.className = 'pv-score';
    const sign = node().fen.split(' ')[1] === 'w' ? 1 : -1; const value = (line.score ?? 0) * sign;
    score.textContent = line.scoreType === 'mate' ? `#${value}` : `${value >= 0 ? '+' : ''}${(value / 100).toFixed(2)}`;
    const path = document.createElement('span'); path.className = 'pv-path'; path.textContent = `${rank}. ${(line.pv ?? []).join(' ')}${line.bound ? ' (' + line.bound + ')' : ''}`;
    const play = document.createElement('button'); play.textContent = 'Play line'; play.title = 'Add this principal variation to the game';
    const captured = [...(line.pv ?? [])]; play.addEventListener('click', () => safe(async () => { const identity = ++playing; for (const move of captured) { if (playing !== identity) break; const before = current; await appendMove(move, identity); if (current === before) break; await new Promise((resolve) => window.setTimeout(resolve, 100)); } }));
    row.append(score, path, play); target.append(row);
  }
}
function movePath(): string[] { const path: string[] = []; let id = current; while (id) { const entry = node(id); path.push(entry.uci); id = entry.parent; } return path.reverse(); }
async function startAnalysis(): Promise<void> {
  cancel(); const controller = new AbortController(); active = controller; const version = generation, capturedNode = current, capturedSide = node().fen.split(' ')[1];
  element<HTMLButtonElement>('cancel').disabled = false; element<HTMLButtonElement>('analyze').disabled = true; element('analysis-state').textContent = 'SEARCHING'; element('analysis-state').classList.add('active');
  const numeric = (id: string): number => Number(element<HTMLSelectElement>(id).value);
  try {
    const response = await fetch('/api/analyze', { method: 'POST', signal: controller.signal, headers: { 'Content-Type': 'application/json', 'X-Caissa-Token': session.token, 'X-Caissa-Session': session.session }, body: JSON.stringify({ fen: game.initial, moves: movePath(), chess960: game.chess960, milliseconds: numeric('time'), threads: numeric('threads'), hash: numeric('hash'), multipv: numeric('multipv') }) });
    if (!response.ok) { const error = await response.json() as { error: string }; throw new Error(error.error); }
    const reader = response.body?.getReader(); if (!reader) throw new Error('Analysis stream unavailable.');
    const decoder = new TextDecoder(); let buffer = '';
    for (;;) {
      const chunk = await reader.read(); if (chunk.done) break; buffer += decoder.decode(chunk.value, { stream: true });
      if (buffer.length > 65536) throw new Error('Analysis stream exceeded its limit.');
      let end: number;
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2);
        if (generation !== version || active !== controller) continue;
        const event = frame.split('\n').find((s) => s.startsWith('event: '))?.slice(7); const raw = frame.split('\n').find((s) => s.startsWith('data: '))?.slice(6); if (!raw) continue;
        const data = JSON.parse(raw) as Line & { message?: string; move?: string };
        if (event === 'error') throw new Error(data.message ?? 'Engine analysis failed.');
        if (event === 'info') {
          variations.set(data.multipv ?? 1, data); drawLines(); element('depth').textContent = `${data.depth ?? 0} / ${data.seldepth ?? 0}`; element('nodes').textContent = (data.nodes ?? 0).toLocaleString(); element('nps').textContent = (data.nps ?? 0).toLocaleString();
          if ((data.multipv ?? 1) === 1 && data.scoreType === 'cp') {
            const cp = (data.score ?? 0) * (capturedSide === 'w' ? 1 : -1); const old = evaluations.find((item) => item.node === capturedNode); if (old) old.cp = cp; else evaluations.push({ node: capturedNode, cp }); drawHistory(); save();
          }
        } else if (event === 'bestmove') status(data.move === '0000' ? 'The game has ended.' : `Analysis complete. Best move: ${data.move ?? ''}.`);
      }
    }
  } catch (error) { if (!(error instanceof DOMException && error.name === 'AbortError')) throw error; }
  finally { if (active === controller) cancel(); }
}
function quote(value: string): string { return value.replaceAll('\\', '\\\\').replaceAll('"', '\\"').replace(/[\r\n]/g, ' '); }
function pgnText(): string {
  const tags = { ...game.tags, Result: game.result } as Record<string, string>;
  if (game.initial !== START) { tags['FEN'] = game.initial; tags['SetUp'] = '1'; }
  if (game.chess960) tags['Variant'] = 'Chess960';
  const output = Object.entries(tags).map(([key, value]) => `[${key} "${quote(value)}"]`).join('\n') + '\n\n';
  function branch(child: number, nesting = 0): string {
    if (nesting > 64) throw new Error('Variation nesting exceeds export limit.'); let text = '';
    for (;;) {
      const entry = node(child), parent = node(entry.parent), fields = parent.fen.split(' ');
      text += `${fields[5]}${fields[1] === 'w' ? '.' : '...'} ${entry.san} `;
      if (entry.nags?.length) text += entry.nags.map((n) => '$' + n).join(' ') + ' ';
      if (entry.comment) text += `{${entry.comment.replaceAll('}', ']')}} `;
      if (parent.children[0] === child) for (const sibling of parent.children.slice(1)) text += `( ${branch(sibling, nesting + 1)}) `;
      const next = entry.children[0]; if (next === undefined) break; child = next;
    }
    return text;
  }
  const child = node(0).children[0]; return output + (node(0).comment ? '{' + node(0).comment.replaceAll('}', ']') + '} ' : '') + (child === undefined ? '' : branch(child)) + game.result;
}
element('analyze').addEventListener('click', () => safe(startAnalysis)); element('cancel').addEventListener('click', () => { cancel(); status('Analysis stopped. The last completed lines are retained.'); });
element('flip').addEventListener('click', () => { flipped = !flipped; drawBoard(); });
element('reset').addEventListener('click', () => safe(async () => { game = emptyGame(); evaluations = []; drawHistory(); await selectNode(0); }));
element('load-fen').addEventListener('click', () => safe(async () => { const chess960 = element<HTMLSelectElement>('variant').value === 'chess960'; const value = await api<PositionState>('state', { fen: element<HTMLInputElement>('fen').value, chess960 }); game = emptyGame(value.fen, chess960); evaluations = []; drawHistory(); await selectNode(0); }));
element('import-pgn').addEventListener('click', () => safe(async () => { const value = await api<Game>('pgn', { pgn: element<HTMLTextAreaElement>('pgn').value }); game = value; evaluations = []; drawHistory(); await selectNode(0); status(`Imported ${game.nodes.length - 1} moves and variations.`); }));
element('export-pgn').addEventListener('click', () => safe(async () => { const value = await api<Game>('pgn', { pgn: pgnText() }); element<HTMLTextAreaElement>('pgn').value = value.pgn ?? ''; status('Exported the actual game tree, including edited variations.'); }));
element('new-variation').addEventListener('click', () => { let id = current; while (id) { const entry = node(id), parent = node(entry.parent); parent.children = [id, ...parent.children.filter((child) => child !== id)]; id = entry.parent; } drawMoves(); save(); status('Selected variation is now the main line.'); });
element('first').addEventListener('click', () => safe(() => selectNode(0))); element('previous').addEventListener('click', () => safe(() => selectNode(node().parent)));
element('next').addEventListener('click', () => safe(() => selectNode(node().children[0] ?? current))); element('last').addEventListener('click', () => safe(async () => { let id = current; while (node(id).children[0] !== undefined) id = node(id).children[0] ?? id; await selectNode(id); }));
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') { cancel(); selected = undefined; playing++; drawBoard(); } });
async function boot(): Promise<void> {
  const response = await fetch('/api/session'); if (!response.ok) throw new Error('Local session unavailable. Reload to retry.'); session = await response.json() as Session;
  element('engine-label').textContent = `${session.engine} · ${session.evaluation} evaluation`;
  try {
    const saved = localStorage.getItem('caissa-game-v1');
    if (saved && saved.length < 1024 * 1024) {
      const value = JSON.parse(saved) as { version: number; pgn: string; path: string[]; evaluations: { node: number; cp: number }[] };
      if (value.version === 2 && typeof value.pgn === 'string' && Array.isArray(value.path) && value.path.length <= 512) {
        game = await api<Game>('pgn', { pgn: value.pgn }); current = 0;
        for (const move of value.path) { const child = node(current).children.find((id) => node(id).uci === move); if (child === undefined) break; current = child; }
        evaluations = Array.isArray(value.evaluations) ? value.evaluations.filter((entry) => Number.isInteger(entry.node) && Number.isFinite(entry.cp)).slice(-60) : [];
      }
    }
  } catch { game = emptyGame(); current = 0; status('Saved position could not be restored. Starting a new board.', true); }
  drawHistory(); await selectNode(current);
}
safe(boot);
