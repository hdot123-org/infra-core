/**
 * Outbound header & full-passthrough tests.
 * Asserts: (a) X-CI-Token/X-Wiki-Token from Worker secrets, not hardcoded;
 * (b) Full field passthrough (no field drop/rewrite).
 */
import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import worker from '../src/worker.js';

// Node 18 无全局 WebCrypto（crypto.subtle 为 CF Workers 运行时原生能力，Node 19+ 才默认全局）。
// 测试环境注入同构 polyfill；幂等守卫避免覆盖 Node 19+ 已有全局。
if (!globalThis.crypto) {
  globalThis.crypto = webcrypto;
}

async function computeHmac(payload, secret) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, encoder.encode(payload));
  const hex = Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
  return `sha256=${hex}`;
}

describe('Outbound headers & passthrough', () => {
  const SECRET = 'test-secret-outbound';
  let originalFetch;
  let fetchCalls;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    fetchCalls = [];
    globalThis.fetch = async (url, opts) => {
      fetchCalls.push({ url, opts });
      return { ok: true, status: 200 };
    };
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('Actions notify → X-CI-Token from env secret, not hardcoded', async () => {
    const payload = JSON.stringify({
      repo: 'test/repo',
      pr_number: 42,
      run_url: 'https://github.com/test/repo/actions/runs/123',
      extra_field: 'preserved',
    });
    const signature = await computeHmac(payload, SECRET);

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': signature,
      },
      body: payload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: SECRET,
      CI_TOKEN: 'secret-ci-token-value',
    };
    const resp = await worker.fetch(request, env, {});
    assert.equal(resp.status, 200);

    // Assert outbound call
    assert.equal(fetchCalls.length, 1);
    const call = fetchCalls[0];
    assert.equal(call.url, 'https://ci-webhook.exa.edu.kg/hooks/ci-complete');
    assert.equal(call.opts.method, 'POST');
    assert.equal(call.opts.headers['X-CI-Token'], 'secret-ci-token-value');
    assert.equal(call.opts.headers['Content-Type'], 'application/json');

    // Full passthrough — body sent as-is
    assert.equal(call.opts.body, payload);

    // Verify no field dropped by parsing the sent body
    const sentBody = JSON.parse(call.opts.body);
    assert.equal(sentBody.repo, 'test/repo');
    assert.equal(sentBody.pr_number, 42);
    assert.equal(sentBody.run_url, 'https://github.com/test/repo/actions/runs/123');
    assert.equal(sentBody.extra_field, 'preserved');
  });

  it('Push → X-Wiki-Token from env secret, full passthrough', async () => {
    const payload = JSON.stringify({
      ref: 'refs/heads/main',
      after: 'abc123',
      repository: { full_name: 'test/repo' },
      run_url: 'https://github.com/test/repo/commit/abc123',
    });
    const signature = await computeHmac(payload, SECRET);

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': signature,
        'X-GitHub-Event': 'push',
      },
      body: payload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: SECRET,
      WIKI_TOKEN: 'secret-wiki-token-value',
    };
    const resp = await worker.fetch(request, env, {});
    assert.equal(resp.status, 200);

    assert.equal(fetchCalls.length, 1);
    const call = fetchCalls[0];
    assert.equal(call.url, 'https://ci-webhook.exa.edu.kg/hooks/wiki-refresh');
    assert.equal(call.opts.headers['X-Wiki-Token'], 'secret-wiki-token-value');

    // Full passthrough
    const sentBody = JSON.parse(call.opts.body);
    assert.equal(sentBody.ref, 'refs/heads/main');
    assert.equal(sentBody.after, 'abc123');
    assert.equal(sentBody.run_url, 'https://github.com/test/repo/commit/abc123');
  });

  it('Ping → no outbound call', async () => {
    const payload = JSON.stringify({ zen: 'Keep it simple' });
    const signature = await computeHmac(payload, SECRET);

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': signature,
        'X-GitHub-Event': 'ping',
      },
      body: payload,
    });

    const env = { GITHUB_WEBHOOK_SECRET: SECRET };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 200);
    assert.equal(body.forwarded, false);
    assert.equal(fetchCalls.length, 0);
  });

  it('PostHog error → transparent X-Posthog-Token passthrough', async () => {
    const payload = JSON.stringify({ error_type: 'test', count: 1 });

    const request = new Request('https://worker.test/webhook/posthog-error', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Posthog-Token': 'posthog-secret-value',
      },
      body: payload,
    });

    const env = {};
    const resp = await worker.fetch(request, env, {});
    assert.equal(resp.status, 200);

    assert.equal(fetchCalls.length, 1);
    const call = fetchCalls[0];
    assert.equal(call.url, 'https://ci-webhook.exa.edu.kg/hooks/posthog-error');
    assert.equal(call.opts.headers['X-Posthog-Token'], 'posthog-secret-value');
    assert.equal(call.opts.body, payload);
  });

  it('GET on /webhook/events → 405 Method Not Allowed', async () => {
    const request = new Request('https://worker.test/webhook/events', {
      method: 'GET',
    });

    const env = {};
    const resp = await worker.fetch(request, env, {});
    assert.equal(resp.status, 405);
  });
});
