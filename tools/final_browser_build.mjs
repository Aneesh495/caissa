// Emit the actual compiler output to the metered Python owner, never to disk.
import { readFileSync } from 'node:fs';
import { resolve, relative } from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const scope = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const ts = require(resolve(scope.typescript, 'lib/typescript.js'));
const sha = (data) => createHash('sha256').update(data).digest('hex');
const config = ts.readConfigFile(resolve(scope.root, 'tsconfig.json'), ts.sys.readFile);
if (config.error) throw new Error('Cannot read the pinned TypeScript configuration.');
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, scope.root);
const options = { ...parsed.options, outDir: resolve(scope.output, 'product/dist'), typeRoots: [scope.type_roots] };
const program = ts.createProgram(parsed.fileNames, options);
const errors = [...parsed.errors, ...ts.getPreEmitDiagnostics(program)];
if (errors.length) throw new Error(ts.formatDiagnosticsWithColorAndContext(errors, { getCurrentDirectory: () => scope.root, getCanonicalFileName: (x) => x, getNewLine: () => '\n' }));
const outputs = {};
const emitted = program.emit(undefined, (name, value) => {
  const path = relative(scope.output, name).split('\\').join('/');
  if (!/^product\/dist\/(?:web\/app|analysis-service\/(?:native|server|telemetry))\.js(?:\.map)?$/.test(path)) throw new Error('Compiler output escaped the exact eight-file inventory.');
  const bytes = Buffer.from(value);outputs[path] = sha(bytes);
  console.log(JSON.stringify({ artifact: path, data: bytes.toString('base64') }));
});
if (emitted.emitSkipped || emitted.diagnostics.length || Object.keys(outputs).length !== 8) throw new Error('Compiler did not finish the exact final build.');
const sourceInputs = Object.fromEntries(program.getSourceFiles().map((file) => [file.fileName, sha(Buffer.from(file.text))]));
console.log(JSON.stringify({ artifact: 'BUILD.json', data: Buffer.from(JSON.stringify({ status: 'compiled', node: process.version, typescript: ts.version, types_node: JSON.parse(readFileSync(resolve(scope.type_roots, 'node/package.json'), 'utf8')).version, outputs, source_inputs: sourceInputs })).toString('base64') }));
