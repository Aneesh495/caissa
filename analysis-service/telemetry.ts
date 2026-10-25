export const statisticNames = [
  'visited_nodes', 'table_bytes', 'elapsed_ms', 'qnodes', 'tt_hits',
  'ordering_hints', 'tt_cutoffs', 'beta_cutoffs', 'null_cutoffs', 'lmr',
  'researches', 'futility', 'eval_calls', 'eval_ns', 'evaluation_cache_hits',
  'evaluation_cache_bytes', 'neural_evaluations', 'neural_bound_cutoffs',
  'completed_depth_nodes',
] as const;
export type SearchStatistics = Record<typeof statisticNames[number], number>;
export interface SearchTrace {
  depth: number; ply: number; alpha: number; beta: number; synthetic: boolean; fen: string;
}
export function parseStatistics(line: string): SearchStatistics {
  const tokens = line.trim().split(/\s+/);
  if (tokens.slice(0, 3).join(' ') !== 'info string stats' || tokens.length !== 3 + statisticNames.length * 2) throw new Error('Invalid search statistics layout.');
  const result: Record<string, number> = {};
  for (let i = 3; i < tokens.length; i += 2) {
    const name = tokens[i], text = tokens[i + 1];
    if (name === undefined || text === undefined || !statisticNames.some((key) => key === name) || Object.hasOwn(result, name) || !/^\d+$/.test(text)) throw new Error('Invalid search statistics field.');
    const value = Number(text);
    if (!Number.isSafeInteger(value)) throw new Error('Search counter exceeds its exact integer range.');
    result[name] = value;
  }
  // All names were admitted exactly once. Build the typed result without an
  // unchecked assertion across the native/browser transport boundary.
  const counter = (name: typeof statisticNames[number]): number => {
    const value = result[name]; if (value === undefined) throw new Error('Missing search counter.'); return value;
  };
  const statistics: SearchStatistics = {
    visited_nodes: counter('visited_nodes'), table_bytes: counter('table_bytes'), elapsed_ms: counter('elapsed_ms'),
    qnodes: counter('qnodes'), tt_hits: counter('tt_hits'), ordering_hints: counter('ordering_hints'),
    tt_cutoffs: counter('tt_cutoffs'), beta_cutoffs: counter('beta_cutoffs'), null_cutoffs: counter('null_cutoffs'),
    lmr: counter('lmr'), researches: counter('researches'), futility: counter('futility'),
    eval_calls: counter('eval_calls'), eval_ns: counter('eval_ns'), evaluation_cache_hits: counter('evaluation_cache_hits'),
    evaluation_cache_bytes: counter('evaluation_cache_bytes'), neural_evaluations: counter('neural_evaluations'),
    neural_bound_cutoffs: counter('neural_bound_cutoffs'), completed_depth_nodes: counter('completed_depth_nodes'),
  };
  if (statistics.completed_depth_nodes > statistics.visited_nodes || statistics.qnodes > statistics.visited_nodes || statistics.tt_cutoffs > statistics.tt_hits) throw new Error('Inconsistent search statistics.');
  return statistics;
}
export function parseTrace(line: string): SearchTrace {
  const match = /^info string trace depth (\d+) ply (\d+) alpha (-?\d+) beta (-?\d+) synthetic ([01]) fen ([^\r\n\0]+)$/.exec(line);
  if (!match) throw new Error('Invalid search sample layout.');
  const depth = Number(match[1]), ply = Number(match[2]), alpha = Number(match[3]), beta = Number(match[4]), fen = match[6];
  if (!Number.isSafeInteger(depth) || depth > 64 || !Number.isSafeInteger(ply) || ply > 128 || !Number.isSafeInteger(alpha) || !Number.isSafeInteger(beta) || alpha < -32000 || beta > 32000 || alpha >= beta || fen === undefined || fen.length > 256 || fen.split(' ').length !== 6) throw new Error('Search sample exceeds its bounds.');
  return { depth, ply, alpha, beta, synthetic: match[5] === '1', fen };
}
