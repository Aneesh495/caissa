// Own only the prospectively admitted service, Chromium and chess children.
const fs = require('node:fs');
const cp = require('node:child_process');
const path = require('node:path');
const crypto = require('node:crypto');
const scope = JSON.parse(fs.readFileSync(process.env.CAISSA_FINAL_SCOPE, 'utf8'));
const role = process.env.CAISSA_FINAL_ROLE;
const original = cp.spawn;
const originalSync = cp.spawnSync;
const counts = { engine: 0, service: 0, browser: 0 };
const emit = (value) => process.stdout.write(JSON.stringify({ _caissa_process_event: value }) + '\n');
cp.spawn = function(file, args = [], options = {}) {
  let kind;
  if (role === 'service' && file === scope.engine) kind = 'engine';
  else if (role === 'browser' && file === scope.node && JSON.stringify(args) === JSON.stringify(['--require', scope.process_preload, path.join(scope.output, 'product/dist/analysis-service/server.js')])) kind = 'service';
  else if (role === 'browser' && file === scope.chromium) kind = 'browser';
  else throw new Error('Unadmitted child in the final browser pipeline.');
  const maximum = { engine: 32, service: 6, browser: 1 }[kind];
  if (++counts[kind] > maximum) throw new Error('Final browser child allowance exhausted.');
  if (kind === 'engine' && crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') !== scope.engine_sha256) throw new Error('Final browser engine changed.');
  const child = original.call(this, file, args, { ...options, detached: false });
  const identity = { kind, parent: process.pid, pid: child.pid, index: counts[kind], command: file, arguments: args };
  emit({ event: 'started', ...identity });
  child.once('close', (code, signal) => emit({ event: 'closed', ...identity, code, signal }));
  return child;
};
let compilerStarts = 0;
cp.spawnSync = function(file, args, options) {
  const expected = ['--project', path.join(scope.root, 'tsconfig.json'), '--outDir', path.join(scope.output, 'product/dist'), '--typeRoots', scope.type_roots, '--listFiles'];
  if (role !== 'build' || scope.maximum_typescript_compiler_starts === 0 || file !== scope.typescript_executable || JSON.stringify(args) !== JSON.stringify(expected) || ++compilerStarts > 1) throw new Error('Unadmitted final compiler invocation.');
  return originalSync.call(this, file, args, { ...options, detached: false });
};
require('node:module').syncBuiltinESMExports();
