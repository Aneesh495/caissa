import assert from 'node:assert/strict';

// These are adversarial subprocess transports, not chess engines or move mocks.
// The separate integration test continues to exercise original Caissa analysis.
process.env.CAISSA_ENGINE = process.execPath;
const { nativeJson, shutdown, workerCounts } = await import('../dist/analysis-service/native.js');
const deadline = setTimeout(() => { shutdown(); console.error('Worker ownership test exceeded 15 seconds.'); process.exit(1); }, 15000);
async function idle() {
  const end = Date.now() + 1500;
  while (workerCounts().positions && Date.now() < end) await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(workerCounts().positions, 0, 'owned processes were not reaped');
}
try {
  const emit = 'process.stdout.write(Buffer.alloc(5*1024*1024, 120));setInterval(()=>{},1000)';
  let reservedOnRejection = 0;
  const pending = Array.from({ length: 4 }, () => nativeJson(['-e', emit]).then(
    () => assert.fail('oversized subprocess response accepted'),
    (error) => { assert.equal(error.status, 413); assert(workerCounts().positions > 0); reservedOnRejection++; },
  ));
  assert.equal(workerCounts().positions, 4);
  await assert.rejects(nativeJson(['-e', 'console.log("{}")']), (error) => error.status === 429);
  await Promise.all(pending); await idle(); assert.equal(reservedOnRejection, 4);
  await assert.rejects(nativeJson(['-e', 'setInterval(()=>{},1000)'], '', 20), (error) => error.status === 408);
  await idle();
  await assert.rejects(nativeJson(['-e', 'console.log("invalid JSON")']), (error) => error.status === 502);
  await idle();
  // Force a multibyte character across separate pipe writes.
  const unicode = 'const b=Buffer.from("♞");process.stdout.write("{\\"text\\":\\"");process.stdout.write(b.subarray(0,1));setTimeout(()=>{process.stdout.write(b.subarray(1));process.stdout.end("\\"}")},20)';
  assert.deepEqual(await nativeJson(['-e', unicode]), { text: '♞' }); await idle();
  await assert.rejects(nativeJson(['\0']), TypeError); await idle();
  const stopped = nativeJson(['-e', 'setInterval(()=>{},1000)']);
  shutdown(); await assert.rejects(stopped); await idle();
  assert.deepEqual(await nativeJson(['-e', 'console.log("{\\"recovered\\":true}")']), { recovered: true });
  await idle();
  console.log(JSON.stringify({ status: 'passed', occupiedLimit: 4, reservedUntilClose: reservedOnRejection,
    timeoutReaped: true, malformedRejected: true, unicodePreserved: true, synchronousSpawnFailure: true,
    shutdownReaped: true, capacityRecovered: true, scope: 'adversarial subprocess transport; real chess integration separate' }));
} finally { clearTimeout(deadline); shutdown(); }
