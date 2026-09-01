/**
 * CF Worker — webhook-gateway
 *
 * Fetch handler: 入站 POST /webhook/events + POST /webhook/posthog-error
 * Scheduled handler: cron → repository_dispatch
 *
 * 硬边界：
 * - X-Hub-Signature-256 HMAC 验签 fail-closed（secret 未配置 = 拒绝）
 * - 出站 token 全部来自 Worker secrets，代码零硬编码
 * - 全字段透传（不丢字段、不改写）
 */

import { route } from './router.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const CI_WEBHOOK_BASE = 'https://ci-webhook.exa.edu.kg';
const GITHUB_API_BASE = 'https://api.github.com';
const MAX_RETRIES = 2;
const RETRY_BASE_MS = 500;
const IDEMPOTENCY_WINDOW_SEC = 600; // 10 minutes

// ---------------------------------------------------------------------------
// HMAC Verification (fail-closed)
// ---------------------------------------------------------------------------
async function verifySignature(payload, signature, secret) {
  if (!secret) {
    // fail-closed: secret not configured = reject
    return false;
  }
  if (!signature) {
    return false;
  }

  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, encoder.encode(payload));
  const expected = 'sha256=' + arrayBufferToHex(sig);

  // Constant-time compare
  if (expected.length !== signature.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ signature.charCodeAt(i);
  }
  return diff === 0;
}

function arrayBufferToHex(buffer) {
  return Array.from(new Uint8Array(buffer))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

// ---------------------------------------------------------------------------
// Outbound fetch with retry (2 backoffs)
// ---------------------------------------------------------------------------
async function fetchWithRetry(url, options, retries = MAX_RETRIES) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const resp = await fetch(url, options);
      if (resp.ok || (resp.status >= 300 && resp.status < 500)) {
        return resp;
      }
      lastError = new Error(`HTTP ${resp.status}`);
    } catch (err) {
      lastError = err;
    }
    if (attempt < retries) {
      const delay = RETRY_BASE_MS * Math.pow(2, attempt);
      await sleep(delay);
    }
  }
  throw lastError;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Fetch Handler
// ---------------------------------------------------------------------------
async function handleFetch(request, env, ctx) {
  const url = new URL(request.url);
  const method = request.method.toUpperCase();
  const pathname = url.pathname;

  // GET on any webhook endpoint → 405
  if (
    (pathname === '/webhook/events' || pathname === '/webhook/posthog-error') &&
    method !== 'POST'
  ) {
    return jsonResponse(
      { status: 'error', error: 'Method Not Allowed' },
      405
    );
  }

  // POST /webhook/events — GitHub webhook with HMAC verification
  if (pathname === '/webhook/events' && method === 'POST') {
    return handleGitHubWebhook(request, env);
  }

  // POST /webhook/posthog-error — passthrough to Mac:5555
  if (pathname === '/webhook/posthog-error' && method === 'POST') {
    return handlePosthogError(request, env);
  }

  // Health / root
  if (pathname === '/' || pathname === '/health') {
    return jsonResponse({ status: 'ok', service: 'webhook-gateway' });
  }

  return jsonResponse({ status: 'error', error: 'Not Found' }, 404);
}

async function handleGitHubWebhook(request, env) {
  const body = await request.text();
  const signature = request.headers.get('x-hub-signature-256');
  const githubEvent = request.headers.get('x-github-event') || '';

  // HMAC verification (fail-closed)
  const secret = env.GITHUB_WEBHOOK_SECRET || null;
  const valid = await verifySignature(body, signature, secret);
  if (!valid) {
    return jsonResponse(
      { status: 'error', error: 'Signature verification failed' },
      401
    );
  }

  // Parse payload
  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    return jsonResponse({ status: 'error', error: 'Invalid JSON' }, 400);
  }

  // Route decision
  const decision = route(githubEvent, payload);

  if (decision.action === 'none') {
    return jsonResponse({
      status: 'ok',
      route: decision.route,
      event: decision.event,
      forwarded: false,
      reason: decision.reason || 'no forwarding required',
    });
  }

  // Forward to ci-webhook tunnel
  const targetUrl = CI_WEBHOOK_BASE + decision.path;
  const headers = {
    'Content-Type': 'application/json',
    'User-Agent': 'webhook-gateway/1.0',
  };

  // Inject token from Worker secrets
  if (decision.tokenSecret === 'CI_TOKEN') {
    headers['X-CI-Token'] = env.CI_TOKEN || '';
  } else if (decision.tokenSecret === 'WIKI_TOKEN') {
    headers['X-Wiki-Token'] = env.WIKI_TOKEN || '';
  }

  // Full field passthrough — body is sent as-is (no field drop/rewrite)
  try {
    await fetchWithRetry(targetUrl, {
      method: 'POST',
      headers,
      body,
    });
  } catch (err) {
    return jsonResponse(
      {
        status: 'error',
        error: 'Forwarding failed',
        detail: err.message,
        route: decision.route,
        event: decision.event,
      },
      502
    );
  }

  return jsonResponse({
    status: 'ok',
    route: decision.route,
    event: decision.event,
    forwarded: true,
  });
}

async function handlePosthogError(request, env) {
  const body = await request.text();
  const posthogToken = request.headers.get('x-posthog-token') || '';

  const targetUrl = CI_WEBHOOK_BASE + '/hooks/posthog-error';
  const headers = {
    'Content-Type': 'application/json',
    'User-Agent': 'webhook-gateway/1.0',
    'X-Posthog-Token': posthogToken,
  };

  // Full field passthrough
  try {
    await fetchWithRetry(targetUrl, {
      method: 'POST',
      headers,
      body,
    });
  } catch (err) {
    return jsonResponse(
      { status: 'error', error: 'Forwarding failed', detail: err.message },
      502
    );
  }

  return jsonResponse({ status: 'ok', route: 'posthog-error', forwarded: true });
}

// ---------------------------------------------------------------------------
// Scheduled Handler (cron → repository_dispatch)
// ---------------------------------------------------------------------------
async function handleScheduled(event, env, ctx) {
  const dispatchToken = env.DISPATCH_TOKEN || null;
  const kv = env.IDEMPOTENCY_KV || null;

  // Idempotency check
  const idempotencyKey = `dispatch:${Math.floor(event.scheduledTime / 1000 / IDEMPOTENCY_WINDOW_SEC)}`;
  if (kv) {
    const existing = await kv.get(idempotencyKey);
    if (existing) {
      console.log(`[scheduled] Idempotency hit: ${idempotencyKey}, skipping`);
      return;
    }
    // Set lock with 2x window TTL
    await kv.put(idempotencyKey, '1', {
      expirationTtl: IDEMPOTENCY_WINDOW_SEC * 2,
    });
  }

  // Heartbeat log (always, regardless of dispatch success)
  console.log(
    `[scheduled] Triggered at ${new Date(event.scheduledTime).toISOString()}, key=${idempotencyKey}`
  );

  if (!dispatchToken) {
    console.warn('[scheduled] DISPATCH_TOKEN not configured, dispatch skipped');
    return;
  }

  // repository_dispatch to infra-core
  const dispatchUrl = `${GITHUB_API_BASE}/repos/hdot123-org/infra-core/dispatches`;
  const headers = {
    Authorization: `token ${dispatchToken}`,
    Accept: 'application/vnd.github+json',
    'Content-Type': 'application/json',
    'User-Agent': 'webhook-gateway/1.0',
  };
  const body = JSON.stringify({
    event_type: 'webhook-gateway-heartbeat',
    client_payload: {
      source: 'webhook-gateway',
      scheduled_time: new Date(event.scheduledTime).toISOString(),
    },
  });

  try {
    const resp = await fetch(dispatchUrl, {
      method: 'POST',
      headers,
      body,
    });
    console.log(`[scheduled] dispatch status=${resp.status}`);
  } catch (err) {
    console.error(`[scheduled] dispatch failed: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------
export default {
  fetch: handleFetch,
  scheduled: handleScheduled,
};
