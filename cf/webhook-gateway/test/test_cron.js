/**
 * Cron handler tests — repository_dispatch mock + idempotency.
 * Asserts: (a) URL is api.github.com repository_dispatch endpoint;
 * (b) event_type matches design; (c) Authorization from DISPATCH_TOKEN secret;
 * (d) Idempotency lock prevents duplicate dispatches.
 */
import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/worker.js';

describe('Scheduled handler (cron → repository_dispatch)', () => {
  let originalFetch;
  let fetchCalls;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    fetchCalls = [];
    globalThis.fetch = async (url, opts) => {
      fetchCalls.push({ url, opts });
      return { ok: true, status: 204 };
    };
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('Dispatches to api.github.com with correct event_type and Authorization', async () => {
    const event = { scheduledTime: 1700000000000, cron: '*/10 * * * *' };
    const env = { DISPATCH_TOKEN: 'test-dispatch-token-xyz' };

    await worker.scheduled(event, env, {});

    assert.equal(fetchCalls.length, 1);
    const call = fetchCalls[0];
    assert.equal(
      call.url,
      'https://api.github.com/repos/hdot123-org/infra-core/dispatches'
    );
    assert.equal(call.opts.method, 'POST');
    assert.equal(call.opts.headers['Authorization'], 'token test-dispatch-token-xyz');

    const body = JSON.parse(call.opts.body);
    assert.equal(body.event_type, 'webhook-gateway-heartbeat');
    assert.equal(body.client_payload.source, 'webhook-gateway');
    assert.ok(body.client_payload.scheduled_time);
  });

  it('No DISPATCH_TOKEN → log warning, no dispatch call', async () => {
    const event = { scheduledTime: 1700000000000, cron: '*/10 * * * *' };
    const env = {}; // no DISPATCH_TOKEN

    await worker.scheduled(event, env, {});

    assert.equal(fetchCalls.length, 0);
  });

  it('Idempotency: KV lock prevents duplicate dispatch within window', async () => {
    const kvStore = new Map();
    const mockKV = {
      get: async (key) => kvStore.get(key) || null,
      put: async (key, value, opts) => {
        kvStore.set(key, value);
      },
    };

    const event1 = { scheduledTime: 1700000000000, cron: '*/10 * * * *' };
    const env = {
      DISPATCH_TOKEN: 'test-dispatch-token',
      IDEMPOTENCY_KV: mockKV,
    };

    // First call — should dispatch
    await worker.scheduled(event1, env, {});
    assert.equal(fetchCalls.length, 1);
    assert.equal(kvStore.size, 1);

    // Second call with same time window — should skip (idempotent)
    await worker.scheduled(event1, env, {});
    assert.equal(fetchCalls.length, 1); // still 1, not 2

    // Third call with different time window — should dispatch again
    const event2 = { scheduledTime: 1700000600000 + 600000, cron: '*/10 * * * *' };
    await worker.scheduled(event2, env, {});
    assert.equal(fetchCalls.length, 2);
  });

  it('KV not bound → dispatch proceeds without idempotency', async () => {
    const event = { scheduledTime: 1700000000000, cron: '*/10 * * * *' };
    const env = { DISPATCH_TOKEN: 'test-dispatch-token' };
    // No IDEMPOTENCY_KV

    await worker.scheduled(event, env, {});
    assert.equal(fetchCalls.length, 1);
  });
});
