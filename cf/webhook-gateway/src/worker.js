/**
 * CF Worker — webhook-gateway
 *
 * Fetch handler: POST /webhook/events (unified multiplexer)
 * Scheduled handler: cron → repository_dispatch
 *
 * 硬边界：
 * - 双通道认证：X-Hub-Signature-256 HMAC 或 token 头匹配任一放行；双缺失/错误 401
 * - 出站 token 全部来自 Worker secrets，代码零硬编码
 * - 全字段透传（不丢字段、不改写）；Linear Issue/Comment 重建 {action,type,data}
 * - PostHog/Linear 类并入 /webhook/events 分类器（统一路径裁定）
 */

import { route, detectLinear } from './router.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const CI_WEBHOOK_BASE = 'https://ci-webhook.exa.edu.kg';
const GITHUB_API_BASE = 'https://api.github.com';
const POSTHOG_CAPTURE_URL = 'https://us.posthog.com/capture/';
const MAX_RETRIES = 2;
const RETRY_BASE_MS = 500;
const IDEMPOTENCY_WINDOW_SEC = 600; // 10 minutes
const POSTHOG_CAPTURE_TIMEOUT_MS = 2000; // 2s timeout for PostHog capture

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
// PostHog metadata capture (metadata-only, no payload fields)
// ---------------------------------------------------------------------------
const POSTHOG_ALLOWED_FIELDS = new Set([
  'route',
  'event',
  'repo',
  'outcome',
  'http_status',
  'duration_ms',
  'request_id',
]);

/**
 * Capture metadata-only event to PostHog.
 * Returns a Promise (or undefined if skipped) so callers can wrap with ctx.waitUntil
 * to prevent CF Workers runtime from truncating the fire-and-forget request.
 * Silently catches errors + 2s abort — never affects the main forwarding path.
 */
export function capturePostHog(env, ctx, metadata) {
  // Backward-compatible: if ctx is omitted (2-arg call from older tests), skip waitUntil
  if (metadata === undefined && ctx && typeof ctx.waitUntil !== 'function') {
    metadata = ctx;
    ctx = null;
  }

  const key = env.POSTHOG_CAPTURE_KEY;
  if (!key) {
    console.warn('[posthog] POSTHOG_CAPTURE_KEY not configured, capture skipped');
    return;
  }

  // Build properties — whitelist enforcement: only metadata fields allowed
  const properties = {};
  for (const [k, v] of Object.entries(metadata)) {
    if (POSTHOG_ALLOWED_FIELDS.has(k)) {
      properties[k] = v;
    }
  }

  const payload = {
    api_key: key,
    event: 'cf_worker_request',
    properties: {
      distinct_id: 'webhook-gateway',
      ...properties,
    },
  };

  // Fire-and-forget with 2s abort — never blocks main path
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), POSTHOG_CAPTURE_TIMEOUT_MS);

  const promise = fetch(POSTHOG_CAPTURE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: controller.signal,
  })
    .then((resp) => {
      clearTimeout(timeout);
      if (!resp.ok) {
        console.warn(`[posthog] capture response ${resp.status}`);
      }
    })
    .catch((err) => {
      clearTimeout(timeout);
      console.warn(`[posthog] capture failed: ${err.message}`);
    });

  // Wrap with ctx.waitUntil so CF Workers runtime doesn't truncate the request
  if (ctx && typeof ctx.waitUntil === 'function') {
    ctx.waitUntil(promise);
  }

  return promise;
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
    return handleGitHubWebhook(request, env, ctx);
  }

  // POST /webhook/posthog-error — passthrough to Mac:5555
  if (pathname === '/webhook/posthog-error' && method === 'POST') {
    return handlePosthogError(request, env, ctx);
  }

  // Health / root
  if (pathname === '/' || pathname === '/health') {
    return jsonResponse({ status: 'ok', service: 'webhook-gateway' });
  }

  return jsonResponse({ status: 'error', error: 'Not Found' }, 404);
}

async function handleGitHubWebhook(request, env, ctx) {
  const startTime = Date.now();
  const body = await request.text();
  const signature = request.headers.get('x-hub-signature-256');
  const githubEvent = request.headers.get('x-github-event') || '';
  const requestId = request.headers.get('x-github-delivery') || '';

  // Dual-channel authentication (fail-closed):
  // Channel 1: X-Hub-Signature-256 HMAC (standard GitHub webhook)
  // Channel 2: Token header (ci-notify class with X-CI-Token matching CI_TOKEN secret)
  // At least one must pass; both missing/wrong → 401
  const secret = env.GITHUB_WEBHOOK_SECRET || null;
  const ciToken = env.CI_TOKEN || null;
  const inboundCiToken = request.headers.get('x-ci-token') || '';

  let hmacValid = false;
  let tokenValid = false;

  if (secret && signature) {
    hmacValid = await verifySignature(body, signature, secret);
  }

  // ci-notify class: X-CI-Token header matches CI_TOKEN secret
  if (ciToken && inboundCiToken && ciToken === inboundCiToken) {
    tokenValid = true;
  }

  if (!hmacValid && !tokenValid) {
    const duration = Date.now() - startTime;
    capturePostHog(env, ctx, {
      route: 'github-webhook',
      event: githubEvent,
      outcome: 'rejected',
      http_status: 401,
      duration_ms: duration,
      request_id: requestId,
    });
    return jsonResponse(
      { status: 'error', error: 'Authentication failed' },
      401
    );
  }

  // Parse payload
  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    const duration = Date.now() - startTime;
    capturePostHog(env, ctx, {
      route: 'github-webhook',
      event: githubEvent,
      outcome: 'rejected',
      http_status: 400,
      duration_ms: duration,
      request_id: requestId,
    });
    return jsonResponse({ status: 'error', error: 'Invalid JSON' }, 400);
  }

  // Route decision (pass headers for posthog token detection)
  const headersObj = {};
  for (const [key, value] of request.headers.entries()) {
    headersObj[key.toLowerCase()] = value;
  }
  const decision = route(githubEvent, payload, headersObj);
  const repo = payload.repository?.full_name || '';

  if (decision.action === 'none') {
    const duration = Date.now() - startTime;
    capturePostHog(env, ctx, {
      route: decision.route,
      event: decision.event,
      repo,
      outcome: 'ok',
      http_status: 200,
      duration_ms: duration,
      request_id: requestId,
    });
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

  // Inject token from Worker secrets based on route
  if (decision.tokenSecret === 'CI_TOKEN') {
    headers['X-CI-Token'] = env.CI_TOKEN || '';
  } else if (decision.tokenSecret === 'WIKI_TOKEN') {
    headers['X-Wiki-Token'] = env.WIKI_TOKEN || '';
    headers['X-GitHub-Event'] = 'push'; // VAL-WPARITY-003: dual-header requirement
  } else if (decision.tokenSecret === 'LINEAR_WEBHOOK_TOKEN') {
    headers['X-Webhook-Token'] = env.LINEAR_WEBHOOK_TOKEN || '';
  } else if (decision.tokenSecret === 'POSTHOG_PASSTHROUGH') {
    headers['X-Posthog-Token'] = headersObj['x-posthog-token'] || '';
  }

  // Linear Issue/Comment reconstruction: extract {action, type, data}
  let forwardBody = body;
  if (decision.tokenSecret === 'LINEAR_WEBHOOK_TOKEN') {
    const linearDetect = detectLinear(githubEvent, payload);
    if (linearDetect.isLinear && (linearDetect.resourceType === 'Issue' || linearDetect.resourceType === 'Comment')) {
      // Reconstruct minimal payload for linear-to-droid
      const reconstructed = {
        action: payload.action,
        type: payload.type,
        data: payload.data
      };
      forwardBody = JSON.stringify(reconstructed);
    }
  }

  // Full field passthrough — body is sent as-is (no field drop/rewrite)
  // Exception: Linear Issue/Comment reconstruction (minimal payload)
  try {
    await fetchWithRetry(targetUrl, {
      method: 'POST',
      headers,
      body: forwardBody,
    });
    const duration = Date.now() - startTime;
    capturePostHog(env, ctx, {
      route: decision.route,
      event: decision.event,
      repo,
      outcome: 'forwarded',
      http_status: 200,
      duration_ms: duration,
      request_id: requestId,
    });
  } catch (err) {
    const duration = Date.now() - startTime;
    capturePostHog(env, ctx, {
      route: decision.route,
      event: decision.event,
      repo,
      outcome: 'error',
      http_status: 502,
      duration_ms: duration,
      request_id: requestId,
    });
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

async function handlePosthogError(request, env, ctx) {
  const startTime = Date.now();
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
    const duration = Date.now() - startTime;
    capturePostHog(env, ctx, {
      route: 'posthog-error',
      event: 'posthog-error',
      outcome: 'forwarded',
      http_status: 200,
      duration_ms: duration,
    });
  } catch (err) {
    const duration = Date.now() - startTime;
    capturePostHog(env, ctx, {
      route: 'posthog-error',
      event: 'posthog-error',
      outcome: 'error',
      http_status: 502,
      duration_ms: duration,
    });
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
  const startTime = Date.now();
  const dispatchToken = env.DISPATCH_TOKEN || null;
  const kv = env.IDEMPOTENCY_KV || null;

  // Idempotency check
  const idempotencyKey = `dispatch:${Math.floor(event.scheduledTime / 1000 / IDEMPOTENCY_WINDOW_SEC)}`;
  if (kv) {
    const existing = await kv.get(idempotencyKey);
    if (existing) {
      console.log(`[scheduled] Idempotency hit: ${idempotencyKey}, skipping`);
      const duration = Date.now() - startTime;
      capturePostHog(env, ctx, {
        route: 'scheduled',
        event: 'cron',
        outcome: 'ok',
        duration_ms: duration,
        request_id: `scheduled-${idempotencyKey}`,
      });
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
    const duration = Date.now() - startTime;
    capturePostHog(env, ctx, {
      route: 'scheduled',
      event: 'cron',
      outcome: 'rejected',
      duration_ms: duration,
      request_id: `scheduled-${idempotencyKey}`,
    });
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
    const duration = Date.now() - startTime;
    capturePostHog(env, ctx, {
      route: 'scheduled',
      event: 'cron',
      outcome: resp.ok ? 'forwarded' : 'error',
      http_status: resp.status,
      duration_ms: duration,
      request_id: `scheduled-${idempotencyKey}`,
    });
  } catch (err) {
    console.error(`[scheduled] dispatch failed: ${err.message}`);
    const duration = Date.now() - startTime;
    capturePostHog(env, ctx, {
      route: 'scheduled',
      event: 'cron',
      outcome: 'error',
      duration_ms: duration,
      request_id: `scheduled-${idempotencyKey}`,
    });
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
