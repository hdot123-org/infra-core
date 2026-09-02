/**
 * Four-channel authentication tests — VAL-WPARITY-002
 *
 * Channel 1: X-Hub-Signature-256 HMAC (standard GitHub webhook)
 * Channel 2: X-CI-Token header matching CI_TOKEN secret (ci-notify class)
 * Channel 3: X-Linear-Signature HMAC (Linear webhook signing; bare hex, no prefix)
 * Channel 4: X-Posthog-Token header matching POSTHOG_TOKEN secret (PostHog alert class)
 *
 * At least one must pass; all missing/wrong → 401 fail-closed.
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

// Helper: compute bare-hex HMAC-SHA256 (Linear X-Linear-Signature format, no "sha256=" prefix)
async function computeLinearHmac(payload, secret) {
  const prefixed = await computeHmac(payload, secret);
  return prefixed.slice('sha256='.length);
}

describe('Four-channel authentication (fail-closed) — VAL-WPARITY-002', () => {
  const SECRET = 'test-secret-for-unit-tests';
  const CI_TOKEN = 'fake-ci-token';
  const LINEAR_SECRET = 'test-linear-secret';
  const POSTHOG_SECRET = 'test-posthog-secret';
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

  // Channel 3: X-Linear-Signature HMAC (Linear webhook signing; bare hex, no prefix)
  it('Channel 3 pass: correct bare-hex X-Linear-Signature → forwarded to linear-to-droid', async () => {
    const linearPayload = JSON.stringify({
      webhookId: 'wh-lin-1',
      action: 'create',
      type: 'Issue',
      data: { id: 'ISS-1', title: 'Test Issue' },
    });
    // Linear sends bare hex (no "sha256=" prefix)
    const bareHexSig = await computeLinearHmac(linearPayload, LINEAR_SECRET);

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Linear-Signature': bareHexSig,
        // intentionally NO x-github-event header — Linear payloads arrive without it
      },
      body: linearPayload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: SECRET,
      CI_TOKEN,
      LINEAR_WEBHOOK_TOKEN: LINEAR_SECRET,
    };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 200);
    assert.equal(body.route, 'linear-to-droid');
    assert.equal(body.forwarded, true);
    assert.equal(fetchCalls.length, 1);
    assert.equal(fetchCalls[0].url, 'https://ci-webhook.exa.edu.kg/hooks/linear-to-droid');
  });

  it('Channel 3 fail: wrong X-Linear-Signature → 401 rejected', async () => {
    const linearPayload = JSON.stringify({
      webhookId: 'wh-lin-1',
      action: 'create',
      type: 'Issue',
      data: { id: 'ISS-1', title: 'Test Issue' },
    });
    // Signature computed with a different secret → must not pass
    const wrongSig = await computeLinearHmac(linearPayload, 'wrong-linear-secret');

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Linear-Signature': wrongSig,
      },
      body: linearPayload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: SECRET,
      CI_TOKEN,
      LINEAR_WEBHOOK_TOKEN: LINEAR_SECRET,
    };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 401);
    assert.match(body.error, /Authentication failed/);
    assert.equal(fetchCalls.length, 0);
  });

  it('Channel 3 fail: missing X-Linear-Signature (no other channel) → 401 rejected', async () => {
    const linearPayload = JSON.stringify({
      webhookId: 'wh-lin-1',
      action: 'create',
      type: 'Issue',
      data: { id: 'ISS-1', title: 'Test Issue' },
    });

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // no signature, no token headers
      },
      body: linearPayload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: SECRET,
      CI_TOKEN,
      LINEAR_WEBHOOK_TOKEN: LINEAR_SECRET,
      POSTHOG_TOKEN: POSTHOG_SECRET,
    };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 401);
    assert.match(body.error, /Authentication failed/);
    assert.equal(fetchCalls.length, 0);
  });

  // Channel 4: X-Posthog-Token equality (PostHog alert class)
  it('Channel 4 pass: x-posthog-token matching POSTHOG_TOKEN → forwarded to posthog-error', async () => {
    const posthogPayload = JSON.stringify({
      event: 'alert',
      error_type: 'test_error',
      count: 5,
    });

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Posthog-Token': POSTHOG_SECRET,
      },
      body: posthogPayload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: SECRET,
      CI_TOKEN,
      POSTHOG_TOKEN: POSTHOG_SECRET,
    };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 200);
    assert.equal(body.route, 'posthog-error');
    assert.equal(body.forwarded, true);
    assert.equal(fetchCalls.length, 1);
    assert.equal(fetchCalls[0].url, 'https://ci-webhook.exa.edu.kg/hooks/posthog-error');
  });

  it('Channel 4 fail: wrong x-posthog-token → 401 rejected', async () => {
    const posthogPayload = JSON.stringify({
      event: 'alert',
      error_type: 'test_error',
      count: 5,
    });

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Posthog-Token': 'wrong-posthog-token',
      },
      body: posthogPayload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: SECRET,
      CI_TOKEN,
      POSTHOG_TOKEN: POSTHOG_SECRET,
    };
    const resp = await worker.fetch(request, env, {});
    const body = await resp.json();

    assert.equal(resp.status, 401);
    assert.match(body.error, /Authentication failed/);
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
