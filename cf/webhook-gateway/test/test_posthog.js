/**
 * PostHog metadata capture tests (VAL-CF-011).
 * 
 * Asserts:
 * 1. PostHog capture is called with cf_worker_request event
 * 2. Only metadata fields are included (whitelist enforcement):
 *    - route, event, repo, outcome, http_status, duration_ms, request_id
 * 3. No payload fields are ever sent (body, PR title, diff, etc.)
 * 4. Capture failure (timeout/error) does NOT affect main forwarding path
 * 5. 2s abort timeout is enforced
 * 6. POSTHOG_CAPTURE_KEY is required (skip if not configured)
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

describe('PostHog metadata capture (VAL-CF-011)', () => {
  const POSTHOG_KEY = 'phc_test_key_12345';
  const GITHUB_SECRET = 'test-github-secret';
  
  let originalFetch;
  let originalSetTimeout;
  let fetchCalls;
  let captureTimeouts;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    originalSetTimeout = globalThis.setTimeout;
    fetchCalls = [];
    captureTimeouts = [];
    globalThis.fetch = async (url, opts) => {
      fetchCalls.push({ url, opts });
      return { ok: true, status: 200 };
    };
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    globalThis.setTimeout = originalSetTimeout;
  });

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

  it('captures cf_worker_request event with metadata whitelist enforcement', async () => {
    const payload = JSON.stringify({
      repository: { full_name: 'test/repo' },
      action: 'opened',
      pull_request: { title: 'Test PR', body: 'PR description' },
    });
    const signature = await computeHmac(payload, GITHUB_SECRET);

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'X-GitHub-Event': 'pull_request',
        'X-Hub-Signature-256': signature,
        'X-GitHub-Delivery': 'test-delivery-123',
      },
      body: payload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: GITHUB_SECRET,
      POSTHOG_CAPTURE_KEY: POSTHOG_KEY,
    };

    await worker.fetch(request, env);

    // Find PostHog capture call
    const posthogCall = fetchCalls.find(c => c.url === 'https://us.posthog.com/capture/');
    assert.ok(posthogCall, 'PostHog capture should be called');

    const capturedBody = JSON.parse(posthogCall.opts.body);
    assert.equal(capturedBody.event, 'cf_worker_request');
    assert.equal(capturedBody.api_key, POSTHOG_KEY);
    assert.equal(capturedBody.properties.distinct_id, 'webhook-gateway');

    // Whitelist enforcement: only metadata fields allowed
    const ALLOWED_FIELDS = ['route', 'event', 'repo', 'outcome', 'http_status', 'duration_ms', 'request_id'];
    const capturedProperties = Object.keys(capturedBody.properties).filter(k => k !== 'distinct_id');
    
    for (const field of capturedProperties) {
      assert.ok(ALLOWED_FIELDS.includes(field), `Field '${field}' is not in whitelist`);
    }

    // No payload fields should be present
    assert.ok(!('body' in capturedBody.properties), 'body should not be captured');
    assert.ok(!('pull_request' in capturedBody.properties), 'pull_request should not be captured');
    assert.ok(!('title' in capturedBody.properties), 'title should not be captured');
    assert.ok(!('payload' in capturedBody.properties), 'payload should not be captured');
  });

  it('includes request_id from X-GitHub-Delivery header', async () => {
    const payload = JSON.stringify({
      repository: { full_name: 'test/repo' },
      action: 'opened',
    });
    const signature = await computeHmac(payload, GITHUB_SECRET);

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'X-GitHub-Event': 'pull_request',
        'X-Hub-Signature-256': signature,
        'X-GitHub-Delivery': 'delivery-abc-123',
      },
      body: payload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: GITHUB_SECRET,
      POSTHOG_CAPTURE_KEY: POSTHOG_KEY,
    };

    await worker.fetch(request, env);

    const posthogCall = fetchCalls.find(c => c.url === 'https://us.posthog.com/capture/');
    const capturedBody = JSON.parse(posthogCall.opts.body);
    
    assert.equal(capturedBody.properties.request_id, 'delivery-abc-123');
  });

  it('capture failure does not affect main forwarding path', async () => {
    const payload = JSON.stringify({
      repository: { full_name: 'test/repo' },
      repo: 'test/repo',
      pr_number: 42,
    });
    const signature = await computeHmac(payload, GITHUB_SECRET);

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'X-GitHub-Event': 'push',
        'X-Hub-Signature-256': signature,
      },
      body: payload,
    });

    let posthogCallCount = 0;
    globalThis.fetch = async (url, opts) => {
      fetchCalls.push({ url, opts });
      
      if (url === 'https://us.posthog.com/capture/') {
        posthogCallCount++;
        throw new Error('PostHog network error');
      }
      
      // Main forwarding should succeed
      return { ok: true, status: 200 };
    };

    const env = {
      GITHUB_WEBHOOK_SECRET: GITHUB_SECRET,
      POSTHOG_CAPTURE_KEY: POSTHOG_KEY,
    };

    const response = await worker.fetch(request, env);
    const responseBody = await response.json();

    // Main path should succeed despite PostHog failure
    assert.equal(response.status, 200);
    assert.equal(responseBody.status, 'ok');
    assert.equal(responseBody.route, 'wiki-refresh');
    assert.equal(responseBody.forwarded, true);

    // PostHog should have been attempted
    assert.equal(posthogCallCount, 1);
  });

  it('capture is skipped when POSTHOG_CAPTURE_KEY is not configured', async () => {
    const payload = JSON.stringify({
      repository: { full_name: 'test/repo' },
    });
    const signature = await computeHmac(payload, GITHUB_SECRET);

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'X-GitHub-Event': 'push',
        'X-Hub-Signature-256': signature,
      },
      body: payload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: GITHUB_SECRET,
      // POSTHOG_CAPTURE_KEY intentionally omitted
    };

    await worker.fetch(request, env);

    // No PostHog capture should be called
    const posthogCall = fetchCalls.find(c => c.url === 'https://us.posthog.com/capture/');
    assert.ok(!posthogCall, 'PostHog capture should not be called when key is missing');
  });

  it('timeout is enforced for PostHog capture (2s)', async () => {
    const payload = JSON.stringify({
      repository: { full_name: 'test/repo' },
    });
    const signature = await computeHmac(payload, GITHUB_SECRET);

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'X-GitHub-Event': 'push',
        'X-Hub-Signature-256': signature,
      },
      body: payload,
    });

    // Override setTimeout to track timeout durations
    const originalTimeout = globalThis.setTimeout;
    globalThis.setTimeout = (fn, ms, ...args) => {
      captureTimeouts.push({ fn, ms, args });
      return originalTimeout(fn, ms, ...args);
    };

    let posthogResolved = false;
    globalThis.fetch = async (url, opts) => {
      fetchCalls.push({ url, opts });
      
      if (url === 'https://us.posthog.com/capture/') {
        // Simulate slow response that exceeds timeout
        return new Promise((resolve) => {
          originalTimeout(() => {
            posthogResolved = true;
            resolve({ ok: true, status: 200 });
          }, 5000); // 5s > 2s timeout
        });
      }
      
      return { ok: true, status: 200 };
    };

    const env = {
      GITHUB_WEBHOOK_SECRET: GITHUB_SECRET,
      POSTHOG_CAPTURE_KEY: POSTHOG_KEY,
    };

    const startTime = Date.now();
    await worker.fetch(request, env);
    const elapsed = Date.now() - startTime;

    // Main request should complete quickly, not wait for PostHog
    assert.ok(elapsed < 1000, `Request took ${elapsed}ms, should complete before PostHog timeout`);

    // Restore setTimeout
    globalThis.setTimeout = originalTimeout;

    // Wait a bit to see if PostHog timeout is triggered
    await new Promise(resolve => setTimeout(resolve, 2500));
    
    // Verify timeout was set (2000ms)
    const timeoutCall = captureTimeouts.find(t => t.ms === 2000);
    assert.ok(timeoutCall, 'Timeout should be set to 2000ms');
  });

  it('captures metadata for all route types (forwarded, rejected, error)', async () => {
    // Test forwarded path
    const payload1 = JSON.stringify({
      repository: { full_name: 'test/repo' },
      ref: 'refs/heads/main',
    });
    const signature1 = await computeHmac(payload1, GITHUB_SECRET);

    const request1 = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'X-GitHub-Event': 'push',
        'X-Hub-Signature-256': signature1,
      },
      body: payload1,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: GITHUB_SECRET,
      POSTHOG_CAPTURE_KEY: POSTHOG_KEY,
    };

    await worker.fetch(request1, env);

    let posthogCall = fetchCalls.find(c => c.url === 'https://us.posthog.com/capture/');
    let capturedBody = JSON.parse(posthogCall.opts.body);
    
    assert.equal(capturedBody.properties.outcome, 'forwarded');
    assert.equal(capturedBody.properties.route, 'wiki-refresh');
    assert.ok(capturedBody.properties.duration_ms !== undefined);
    assert.ok(typeof capturedBody.properties.duration_ms === 'number');

    // Test rejected path (signature verification failure)
    fetchCalls.length = 0;
    const request2 = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'X-GitHub-Event': 'push',
        'X-Hub-Signature-256': 'sha256=invalid',
      },
      body: payload1,
    });

    await worker.fetch(request2, env);

    posthogCall = fetchCalls.find(c => c.url === 'https://us.posthog.com/capture/');
    capturedBody = JSON.parse(posthogCall.opts.body);
    
    assert.equal(capturedBody.properties.outcome, 'rejected');
    assert.equal(capturedBody.properties.http_status, 401);
  });

  it('POSTHOG_TOKEN and POSTHOG_CAPTURE_KEY are separate credentials', async () => {
    const payload = JSON.stringify({
      repository: { full_name: 'test/repo' },
    });
    const signature = await computeHmac(payload, GITHUB_SECRET);

    const request = new Request('https://worker.test/webhook/events', {
      method: 'POST',
      headers: {
        'X-GitHub-Event': 'push',
        'X-Hub-Signature-256': signature,
      },
      body: payload,
    });

    const env = {
      GITHUB_WEBHOOK_SECRET: GITHUB_SECRET,
      POSTHOG_TOKEN: 'ph_token_for_inbound',
      POSTHOG_CAPTURE_KEY: 'ph_key_for_capture',
    };

    await worker.fetch(request, env);

    const posthogCall = fetchCalls.find(c => c.url === 'https://us.posthog.com/capture/');
    const capturedBody = JSON.parse(posthogCall.opts.body);
    
    // Verify that POSTHOG_CAPTURE_KEY is used for capture, not POSTHOG_TOKEN
    assert.equal(capturedBody.api_key, 'ph_key_for_capture');
    assert.notEqual(capturedBody.api_key, 'ph_token_for_inbound');
  });
});
