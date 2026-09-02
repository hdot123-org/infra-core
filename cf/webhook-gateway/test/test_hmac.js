/**
 * Dual-channel authentication tests — VAL-WPARITY-002
 *
 * Channel 1: X-Hub-Signature-256 HMAC (standard GitHub webhook)
 * Channel 2: X-CI-Token header matching CI_TOKEN secret (ci-notify class)
 *
 * At least one must pass; both missing/wrong → 401 fail-closed.
 */
import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import worker from '../src/worker.js';

// Node 18 WebCrypto polyfill
if (!globalThis.crypto) {
  globalThis.crypto = webcrypto;
}

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

describe('Dual-channel authentication (fail-closed) — VAL-WPARITY-002', () => {
  const SECRET = 'test-secret-for-unit-tests';
  const CI_TOKEN = 'fake-ci-token';
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

  // Channel 1: HMAC
  it('Channel 1 pass: correct HMAC signature → forwarded', async () => {
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

    const env = { GITHUB_WEBHOOK_SECRET: SECRET, CI_TOKEN };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 200);
    assert.equal(body.forwarded, true);
    assert.equal(fetchCalls.length, 1);
  });

  it('Channel 1 fail: wrong HMAC → 401 rejected', async () => {
    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': 'sha256=0000000000000000000000000000000000000000000000000000000000000000',
        'X-GitHub-Event': '',
      },
      body: PAYLOAD,
    });

    const env = { GITHUB_WEBHOOK_SECRET: SECRET, CI_TOKEN };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 401);
    assert.match(body.error, /Authentication failed/);
    assert.equal(fetchCalls.length, 0);
  });

  // Channel 2: CI Token
  it('Channel 2 pass: valid X-CI-Token → forwarded (no HMAC needed)', async () => {
    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CI-Token': CI_TOKEN,
        'X-GitHub-Event': '',
      },
      body: PAYLOAD,
    });

    const env = { GITHUB_WEBHOOK_SECRET: SECRET, CI_TOKEN };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 200);
    assert.equal(body.forwarded, true);
    assert.equal(fetchCalls.length, 1);
  });

  it('Channel 2 fail: wrong X-CI-Token + no HMAC → 401 rejected', async () => {
    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CI-Token': 'wrong-token',
        'X-GitHub-Event': '',
      },
      body: PAYLOAD,
    });

    const env = { GITHUB_WEBHOOK_SECRET: SECRET, CI_TOKEN };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 401);
    assert.match(body.error, /Authentication failed/);
    assert.equal(fetchCalls.length, 0);
  });

  // Both channels fail
  it('Both channels fail: wrong HMAC + wrong CI token → 401 rejected', async () => {
    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': 'sha256=0000000000000000000000000000000000000000000000000000000000000000',
        'X-CI-Token': 'wrong-token',
        'X-GitHub-Event': '',
      },
      body: PAYLOAD,
    });

    const env = { GITHUB_WEBHOOK_SECRET: SECRET, CI_TOKEN };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 401);
    assert.match(body.error, /Authentication failed/);
    assert.equal(fetchCalls.length, 0);
  });

  // Both channels missing
  it('Both channels missing: no HMAC header + no CI token → 401 rejected', async () => {
    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-GitHub-Event': 'push',
      },
      body: PAYLOAD,
    });

    const env = { GITHUB_WEBHOOK_SECRET: SECRET, CI_TOKEN };
    const resp = await worker.fetch(request, env, {});

    assert.equal(resp.status, 401);
    assert.equal(fetchCalls.length, 0);
  });

  // Missing env secrets
  it('Missing GITHUB_WEBHOOK_SECRET + missing CI_TOKEN env → 401 rejected (fail-closed)', async () => {
    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': 'sha256=anything',
        'X-CI-Token': 'some-token',
        'X-GitHub-Event': 'push',
      },
      body: PAYLOAD,
    });

    // No secrets in env — fail-closed
    const env = {};
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 401);
    assert.match(body.error, /Authentication failed/);
    assert.equal(fetchCalls.length, 0);
  });
});
