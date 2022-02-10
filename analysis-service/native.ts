import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { resolve } from 'node:path';

export const enginePath = resolve(process.env['CAISSA_ENGINE'] ?? 'build/caissa');
export class RequestError extends Error {
  constructor(message: string, public readonly status = 400) { super(message); }
}
let commands = 0;
const children = new Set<ChildProcessWithoutNullStreams>();
export async function nativeJson(args: string[], input = '', timeoutMs = 5000): Promise<unknown> {
  if (commands >= 4) throw new RequestError('Position workers are busy. Retry shortly.', 429);
  commands++;
  try {
    return await new Promise((accept, reject) => {
      const child = spawn(enginePath, args, { stdio: 'pipe' }); children.add(child);
      let output = '', error = '', settled = false;
      const timer = setTimeout(() => { child.kill('SIGKILL'); finish(new RequestError('Position command timed out.', 408)); }, timeoutMs);
      function finish(failure?: Error): void {
        if (settled) return; settled = true; clearTimeout(timer); children.delete(child);
        if (failure) reject(failure);
        else { try { accept(JSON.parse(output) as unknown); } catch { reject(new RequestError('Engine returned invalid data.', 502)); } }
      }
      child.stdout.on('data', (chunk: Buffer) => {
        output += chunk.toString('utf8');
        if (Buffer.byteLength(output) > 4 * 1024 * 1024) { child.kill('SIGKILL'); finish(new RequestError('Position response exceeded limit.', 413)); }
      });
      child.stderr.on('data', (chunk: Buffer) => { if (error.length < 4096) error += chunk.toString('utf8'); });
      child.on('error', () => finish(new RequestError('Engine executable unavailable. Run make build.', 503)));
      child.on('close', (code) => finish(code === 0 ? undefined : new RequestError(error.trim() || 'Engine rejected the input.')));
      child.stdin.on('error', () => {}); child.stdin.end(input);
    });
  } finally { commands--; }
}
export interface AnalysisRequest { fen: string; moves: string[]; chess960: boolean; threads: number; hash: number; multipv: number; milliseconds: number; }
export interface AnalysisHandle { cancel(): void; }
let activeAnalysis = 0;
export function analyze(request: AnalysisRequest, emit: (event: string, value: unknown) => boolean, done: () => void): AnalysisHandle {
  if (activeAnalysis >= 2) throw new RequestError('Two analyses are already running. Cancel one and retry.', 429);
  activeAnalysis++;
  const child = spawn(enginePath, [], { stdio: 'pipe' }); children.add(child);
  let finished = false, initialized = false, closing = false;
  const timeout = setTimeout(() => cancel(), request.milliseconds + 3000);
  let killTimer: ReturnType<typeof setTimeout> | undefined;
  function cleanup(): void {
    if (finished) return; finished = true; clearTimeout(timeout); if (killTimer) clearTimeout(killTimer);
    activeAnalysis--; children.delete(child); done();
  }
  function cancel(): void {
    if (finished || closing) return; closing = true;
    child.stdin.write('stop\nquit\n');
    killTimer = setTimeout(() => child.kill('SIGKILL'), 200);
  }
  child.on('error', () => { emit('error', { message: 'Engine unavailable.' }); cleanup(); });
  child.on('close', cleanup); child.stdin.on('error', () => {});
  const lines = createInterface({ input: child.stdout });
  lines.on('line', (line) => {
    if (line.length > 8192) { emit('error', { message: 'Oversized engine message.' }); cancel(); return; }
    if (line === 'uciok') {
      child.stdin.write(`setoption name Threads value ${request.threads}\nsetoption name Hash value ${request.hash}\nsetoption name MultiPV value ${request.multipv}\nsetoption name UCI_Chess960 value ${request.chess960}\nisready\n`);
    } else if (line === 'readyok' && !initialized && !closing) {
      initialized = true;
      child.stdin.write(`position fen ${request.fen}${request.moves.length ? ' moves ' + request.moves.join(' ') : ''}\ngo movetime ${request.milliseconds}\n`);
      emit('started', { engine: 'Caissa', evaluation: 'classical', milliseconds: request.milliseconds });
    } else if (line.startsWith('info depth ')) {
      if (!emit('info', parseInfo(line))) cancel();
    } else if (line.startsWith('info string error ')) {
      emit('error', { message: line.slice(18) }); cancel();
    } else if (line.startsWith('bestmove ')) {
      emit('bestmove', { move: line.split(' ')[1] }); cancel();
    }
  });
  child.stderr.on('data', () => {}); child.stdin.write('uci\n');
  return { cancel };
}
export function parseInfo(line: string): Record<string, unknown> {
  const tokens = line.split(/\s+/); const record: Record<string, unknown> = {};
  for (let i = 1; i < tokens.length; i++) {
    const word = tokens[i]; if (!word) continue;
    if (word === 'pv') { record['pv'] = tokens.slice(i + 1); break; }
    if (word === 'score') { record['scoreType'] = tokens[++i]; record['score'] = Number(tokens[++i]); }
    else if (['depth', 'seldepth', 'multipv', 'nodes', 'time', 'nps', 'hashfull'].includes(word)) record[word] = Number(tokens[++i]);
    else if (word === 'lowerbound' || word === 'upperbound') record['bound'] = word;
  }
  return record;
}
export function shutdown(): void { for (const child of children) child.kill('SIGTERM'); }
export function workerCounts(): { positions: number; analyses: number } { return { positions: commands, analyses: activeAnalysis }; }
