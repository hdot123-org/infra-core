/**
 * gh-proxy worker — GitHub proxy with private repo support
 *
 * Origin: ~/cf/xun201811/gh-proxy/worker.js (Cloudflare API snapshot 2026-09-02)
 * Modified: Added PAT injection for hdot123-org private repos (Basic auth form)
 *
 * Auth model (3 layers, all in code):
 *   1. Source IP whitelist (CF-Connecting-IP check) — 404 if not allowed
 *   2. PROXY_KEY header check — 404 if missing/wrong
 *   3. Host whitelist — 403 if target host not allowed
 *
 * PAT injection:
 *   - For /https://github.com/hdot123-org/* paths: inject Basic auth
 *     (x-access-token:<PAT> base64-encoded) — github.com git smart-http
 *     endpoint REJECTS Bearer/token form (returns 401), only Basic works
 *   - For all other paths: forward as-is (strip incoming auth headers)
 *   - Public repos: zero behavior change
 *   - Private repos (hdot123-org only): PAT enables access
 */

// Source IP whitelist: only ce-01 runner IP allowed (CF-Connecting-IP)
// This is the original security gate from ~/cf/xun201811/gh-proxy/worker.js
var ALLOWED_IPS = ["47.111.21.195"];

var ALLOWED_HOSTS = [
  "github.com",
  "raw.githubusercontent.com",
  "codeload.github.com",
  "objects.githubusercontent.com",
  "assets.githubusercontent.com",
  "gist.github.com",
  "api.github.com"
];

/**
 * Check if request path targets hdot123-org private repos
 * @param {string} targetPath - decoded target path (e.g., "https://github.com/hdot123-org/infra-core.git/...")
 * @returns {boolean}
 */
function isPrivateRepoPath(targetPath) {
  return targetPath.startsWith("https://github.com/hdot123-org/");
}

/**
 * Build upstream request headers
 * @param {Request} request - incoming request
 * @param {string} targetUrl - upstream URL
 * @param {boolean} injectPAT - whether to inject PAT
 * @param {string|null} pat - PAT value (from env.GH_PRIVATE_PAT)
 * @returns {Headers}
 */
function buildUpstreamHeaders(request, targetUrl, injectPAT, pat) {
  const headers = new Headers();

  // Copy incoming headers, strip hop-by-hop and CF-specific
  for (const [k, v] of request.headers) {
    const lk = k.toLowerCase();
    if ([
      "host",
      "cf-connecting-ip",
      "cf-ipcountry",
      "cf-ray",
      "cf-visitor",
      "x-forwarded-for",
      "x-forwarded-proto",
      "true-client-ip",
      "cdn-loop",
      "accept-encoding",
      // Strip incoming auth headers (client may send its own, we override for private repos)
      "authorization",
      "x-proxy-key"
    ].includes(lk)) continue;
    headers.set(k, v);
  }

  // Inject PAT for private repos (Basic auth form - github.com requires this)
  if (injectPAT && pat) {
    // github.com git smart-http endpoint REJECTS Bearer/token form (401)
    // Only Basic auth with x-access-token:<PAT> works
    headers.set("Authorization", "Basic " + btoa("x-access-token:" + pat));
  }

  return headers;
}

export default {
  async fetch(request, env, ctx) {
    // 0. Source IP whitelist (CF-Connecting-IP) — first gate, 404 if not allowed
    const clientIP = request.headers.get("cf-connecting-ip");
    if (!ALLOWED_IPS.includes(clientIP)) {
      return new Response("Not Found", { status: 404 });
    }

    // 1. PROXY_KEY auth check
    const proxyKey = request.headers.get("x-proxy-key");
    if (!env.PROXY_KEY || !proxyKey || proxyKey !== env.PROXY_KEY) {
      return new Response("Not Found", { status: 404 });
    }

    // 2. Parse target URL from path
    const url = new URL(request.url);
    let target = url.pathname.substring(1) + url.search;
    // Normalize: /https:/github.com → /https://github.com
    target = target.replace(/^(https?):\/(?!\/)/, "$1://");

    if (!target.startsWith("https://")) {
      return new Response("usage: /https://github.com/...", { status: 400 });
    }

    let targetUrl;
    try {
      targetUrl = new URL(target);
    } catch {
      return new Response("invalid target url", { status: 400 });
    }

    // 3. Host whitelist
    if (!ALLOWED_HOSTS.includes(targetUrl.hostname)) {
      return new Response("host not allowed: " + targetUrl.hostname, { status: 403 });
    }

    // 4. Determine if PAT injection needed
    const injectPAT = isPrivateRepoPath(target);
    const pat = env.GH_PRIVATE_PAT || null;

    // 5. Build upstream headers
    const upstreamHeaders = buildUpstreamHeaders(request, target, injectPAT, pat);

    // 6. Forward request
    const resp = await fetch(targetUrl.toString(), {
      method: request.method,
      headers: upstreamHeaders,
      body: ["GET", "HEAD"].includes(request.method) ? void 0 : request.body,
      redirect: "follow"
    });

    // 7. Build response (strip set-cookie, add CORS)
    const respHeaders = new Headers(resp.headers);
    respHeaders.delete("set-cookie");
    respHeaders.set("access-control-allow-origin", "*");

    return new Response(resp.body, {
      status: resp.status,
      statusText: resp.statusText,
      headers: respHeaders
    });
  }
};
