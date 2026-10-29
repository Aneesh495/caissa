// Use the installed native TypeScript CLI with an exact prepaid output inventory.
import { readFileSync, mkdirSync, readdirSync } from 'node:fs';
import { resolve, relative } from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';

const scope = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const sha = (data) => createHash('sha256').update(data).digest('hex');
mkdirSync(resolve(scope.output, 'product/dist'), { recursive: true });
const args = ['--project', resolve(scope.root, 'tsconfig.json'), '--outDir', resolve(scope.output, 'product/dist'), '--typeRoots', scope.type_roots, '--listFiles'];
const actual = spawnSync(scope.typescript_executable, args, { cwd: scope.root, encoding: 'utf8', timeout: 55000, maxBuffer: 1024 * 1024 });
if (actual.error || actual.status !== 0 || actual.signal || actual.stderr) throw new Error('Final TypeScript CLI failed: '+actual.stdout+actual.stderr);
const outputs = {};
for (const entry of readdirSync(resolve(scope.output, 'product/dist'), { recursive: true, withFileTypes: true })) {
  if (!entry.isFile()) continue;
  const file = resolve(entry.parentPath, entry.name);
  const name = relative(scope.output, file).split('\\').join('/');
  if (!/^product\/dist\/(?:web\/app|analysis-service\/(?:native|server|telemetry))\.js(?:\.map)?$/.test(name)) throw new Error('Compiler emitted an unadmitted file.');
  outputs[name] = sha(readFileSync(file));
}
if (Object.keys(outputs).length !== 8) throw new Error('Compiler did not emit the exact eight-file inventory.');
const sourceInputs = {};
for (const line of actual.stdout.trim().split(/\r?\n/)) {
  const file = resolve(scope.root, line);sourceInputs[file] = sha(readFileSync(file));
}
const result = { status: 'compiled', node: process.version, typescript: JSON.parse(readFileSync(resolve(scope.typescript, 'package.json'), 'utf8')).version,
  types_node: JSON.parse(readFileSync(resolve(scope.type_roots, 'node/package.json'), 'utf8')).version,
  compiler_exit: actual.status, compiler_pid: actual.pid, compiler_sha256: sha(readFileSync(scope.typescript_executable)), compiler_arguments: args,
  outputs, source_inputs: sourceInputs };
console.log(JSON.stringify({ artifact: 'BUILD.json', data: Buffer.from(JSON.stringify(result)).toString('base64') }));
