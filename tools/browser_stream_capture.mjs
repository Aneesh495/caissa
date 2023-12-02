// Observe a clone of each real analysis response. Requests and returned responses
// are forwarded unchanged. No route interception, replacement or replay occurs.
export async function observeNativeStreams(page, base, accept) {
  await page.exposeBinding('__caissaNativeStreamEvidence', (_source, value) => accept(value));
  await page.addInitScript(({ base }) => {
    const originalFetch = window.fetch, pending = new Set();
    window.__caissaNativeCaptureIdle = () => Promise.all([...pending]);
    window.fetch = async function (...args) {
      const response = await Reflect.apply(originalFetch, this, args);
      const [input, init] = args;
      const url = new URL(typeof input === 'string' ? input : input.url, location.href);
      if (url.href !== base + '/api/analyze') return response;
      const clone = response.clone();
      const row = { url: url.pathname, method: init?.method ?? 'GET', status: response.status,
        request: init?.body, headers: Object.fromEntries(new Headers(init?.headers)),
        capture_source: 'original-browser-response-clone', transport_complete: false };
      const observation = (async () => {
        const chunks = []; let length = 0;
        try {
          const reader = clone.body.getReader();
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            length += value.byteLength;
            if (length > 8 * 1024 * 1024) throw new Error('Original analysis capture exceeded its byte ceiling.');
            chunks.push(value);
          }
          reader.releaseLock();
          const bytes = new Uint8Array(length); let offset = 0;
          for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
          row.body = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
          row.body_bytes = length; row.transport_complete = true;
        } catch (error) {
          row.aborted = true;
          row.capture_error = { name: String(error?.name ?? 'Error').slice(0, 80), message: String(error?.message ?? error).slice(0, 512) };
        }
        await window.__caissaNativeStreamEvidence(row);
      })();
      pending.add(observation);
      void observation.then(() => pending.delete(observation), () => {});
      return response;
    };
  }, { base });
}
