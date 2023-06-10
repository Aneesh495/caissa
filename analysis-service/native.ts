import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { resolve } from 'node:path';
import { StringDecoder } from 'node:string_decoder';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { parseStatistics, parseTrace } from './telemetry.js';

export const enginePath = resolve(process.env['CAISSA_ENGINE'] ?? 'build/caissa');
const networkPath = process.env['CAISSA_NETWORK'] ? resolve(process.env['CAISSA_NETWORK']) : undefined;
if (networkPath && /[\r\n\0]/.test(networkPath)) throw new Error('Invalid local network path.');
// Serving the experimental selected model is opt-in. The normal analysis room
// continues to use the unchanged classical evaluator.
export const evaluation = networkPath ? 'experimental neural blend (10%)' : 'classical';
export const networkSha256 = networkPath ? createHash('sha256').update(readFileSync(networkPath)).digest('hex') : null;
export class RequestError extends Error {
  constructor(message: string, public readonly status = 400) { super(message); }
}
let commands = 0;
const children = new Set<ChildProcessWithoutNullStreams>();
export async function nativeJson(args: string[], input = '', timeoutMs = 5000): Promise<unknown> {
  if (commands >= 4) throw new RequestError('Position workers are busy. Retry shortly.', 429);
  commands++;
  // A rejected response still owns its process until the close event reaps it.
  // Releasing on rejection permits new workers to overlap a child being killed.
  let spawned = false;
  try {
    return await new Promise((accept, reject) => {
      const child = spawn(enginePath, args, { stdio: 'pipe' }); spawned = true; children.add(child);
      const decoder = new StringDecoder('utf8');
      let output = '', error = '', settled = false, outputBytes = 0;
      const timer = setTimeout(() => { child.kill('SIGKILL'); finish(new RequestError('Position command timed out.', 408)); }, timeoutMs);
      function finish(failure?: Error): void {
        if (settled) return; settled = true; clearTimeout(timer);
        if (failure) reject(failure);
        else { try { accept(JSON.parse(output + decoder.end()) as unknown); } catch { reject(new RequestError('Engine returned invalid data.', 502)); } }
      }
      child.stdout.on('data', (chunk: Buffer) => {
        if (settled) return;
        outputBytes += chunk.length;
        if (outputBytes > 4 * 1024 * 1024) { child.kill('SIGKILL'); finish(new RequestError('Position response exceeded limit.', 413)); return; }
        output += decoder.write(chunk);
      });
      child.stderr.on('data', (chunk: Buffer) => { if (error.length < 4096) error += chunk.toString('utf8').slice(0, 4096 - error.length); });
      child.on('error', () => finish(new RequestError('Engine executable unavailable. Run make build.', 503)));
      child.on('close', (code) => {
        commands--; children.delete(child);
        finish(code === 0 ? undefined : new RequestError(error.trim() || 'Engine rejected the input.'));
      });
      child.stdin.on('error', () => {}); child.stdin.end(input);
    });
  } catch (error) {
    // spawn normally reports errors asynchronously and still emits close.
    // Only synchronous spawn failure has no child to release the reservation.
    if (!spawned) commands--;
    throw error;
  }
}
export interface AnalysisRequest { fen: string; moves: string[]; chess960: boolean; threads: number; hash: number; multipv: number; milliseconds: number; inspect: boolean; }
export interface AnalysisHandle { cancel(): void; }
let activeAnalysis = 0;
export function analyze(request: AnalysisRequest, emit: (event: string, value: unknown) => boolean, done: () => void): AnalysisHandle {
  if (activeAnalysis >= 2) throw new RequestError('Two analyses are already running. Cancel one and retry.', 429);
  activeAnalysis++;
  const child = spawn(enginePath, [], { stdio: 'pipe' }); children.add(child);
  let finished = false, initialized = false, closing = false, sawStatistics = false, traces = 0;
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
  child.on('error', () => { emit('error', { message: 'Engine unavailable.' }); });
  child.on('close', cleanup); child.stdin.on('error', () => {});
  const lines = createInterface({ input: child.stdout });
  lines.on('line', (line) => {
    if (closing && !line.startsWith('bestmove ')) return;
    if (line.length > 8192) { emit('error', { message: 'Oversized engine message.' }); cancel(); return; }
    if (line === 'uciok') {
      const evaluator = networkPath ? `setoption name EvalFile value ${networkPath}\nsetoption name Neural Weight value 10\nsetoption name Use Neural value true\n` : 'setoption name Use Neural value false\n';
      child.stdin.write(`setoption name Threads value ${request.threads}\nsetoption name Hash value ${request.hash}\nsetoption name MultiPV value ${request.multipv}\nsetoption name UCI_Chess960 value ${request.chess960}\n${evaluator}setoption name Lazy Neural value true\nsetoption name Search Stats value ${request.inspect}\nsetoption name Trace Samples value ${request.inspect ? 8 : 0}\nisready\n`);
    } else if (line === 'readyok' && !initialized && !closing) {
      initialized = true;
      child.stdin.write(`position fen ${request.fen}${request.moves.length ? ' moves ' + request.moves.join(' ') : ''}\ngo movetime ${request.milliseconds}\n`);
      emit('started', { engine: 'Caissa', evaluation, networkSha256, milliseconds: request.milliseconds });
    } else if (line.startsWith('info depth ')) {
      if (!emit('info', parseInfo(line))) cancel();
    } else if (request.inspect && (line.startsWith('info string stats ') || line.startsWith('info string trace '))) {
      try {
        if (line.startsWith('info string stats ')) {
          if (sawStatistics) throw new Error('Duplicate search summary.');
          const statistics = parseStatistics(line); sawStatistics = true;
          if (!emit('statistics', statistics)) cancel();
        } else {
          if (!sawStatistics || ++traces > 8 * request.threads) throw new Error('Search samples exceed the requested limit.');
          if (!emit('trace', parseTrace(line))) cancel();
        }
      } catch (error) {
        emit('error', { message: error instanceof Error ? error.message : 'Invalid search inspection.' }); cancel();
      }
    } else if (line.startsWith('info string error ')) {
      emit('error', { message: line.slice(18) }); cancel();
    } else if (line.startsWith('bestmove ')) {
      if (request.inspect && !sawStatistics) emit('error', { message: 'Engine ended without the requested search summary.' });
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
export function shutdown(): void {
  for (const child of children) child.kill('SIGTERM');
  setTimeout(() => { for (const child of children) child.kill('SIGKILL'); }, 200).unref();
}
export function workerCounts(): { positions: number; analyses: number } { return { positions: commands, analyses: activeAnalysis }; }
