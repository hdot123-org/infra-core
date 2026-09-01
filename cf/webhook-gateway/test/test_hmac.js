/**
 * HMAC verification tests — 3 states: correct pass / wrong reject / missing secret reject.
 * Tests the fetch handler directly with mock environments.
 */
import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/worker.js';

// Helper: compute HMAC-SHA256 signature
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

describe('HMAC verification (fail-closed)', () => {
  const SECRET = 'test-secret-for-unit-tests';
  const PAYLOAD = JSON.stringify({ repo: 'test/repo', pr_number: 1 });

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

  it('Correct signature → forwarded', async () => {
    const signature = await computeHmac(PAYLOAD, SECRET);
    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': signature,
        'X-GitHub-Event': '',
      },
      body: PAYLOAD,
    });

    const env = { GITHUB_WEBHOOK_SECRET: SECRET, CI_TOKEN: 'fake-ci-token' };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 200);
    assert.equal(body.forwarded, true);
    assert.equal(fetchCalls.length, 1);
  });

  it('Wrong signature → 401 rejected', async () => {
    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': 'sha256=0000000000000000000000000000000000000000000000000000000000000000',
        'X-GitHub-Event': '',
      },
      body: PAYLOAD,
    });

    const env = { GITHUB_WEBHOOK_SECRET: SECRET };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 401);
    assert.match(body.error, /Signature verification failed/);
    assert.equal(fetchCalls.length, 0); // not forwarded
  });

  it('Missing secret (env not configured) → 401 rejected (fail-closed)', async () => {
    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': 'sha256=anything',
        'X-GitHub-Event': 'push',
      },
      body: PAYLOAD,
    });

    // No GITHUB_WEBHOOK_SECRET in env — fail-closed
    const env = {};
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 401);
    assert.match(body.error, /Signature verification failed/);
    assert.equal(fetchCalls.length, 0);
  });

  it('Missing signature header → 401 rejected', async () => {
    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-GitHub-Event': 'push',
      },
      body: PAYLOAD,
    });

    const env = { GITHUB_WEBHOOK_SECRET: SECRET };
    const resp = await worker.fetch(request, env, {});

    assert.equal(resp.status, 401);
    assert.equal(fetchCalls.length, 0);
  });
});
