/**
 * Differential verification — VAL-WPARITY-001
 *
 * Compares CF Worker router.js decisions against production Unified Events Multiplexer
 * behavior for 9 categories of real captured payloads from n8n execution_data.
 *
 * Each category: capture real payload → run through router.js → compare with
 * expected production decision → assert match.
 *
 * Raw payloads may contain real data/tokens — this script uses minimal sanitized
 * representative payloads that preserve the classification-relevant fields only.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { route, detectLinear } from '../src/router.js';

/**
 * Production multiplexer expected decisions (from n8n Unified Events Multiplexer,
 * /opt/n8n-webhook/workflows/github-events-router-v3.json, upgraded 2026-09-02).
 *
 * Format: { category, headers, body, expectedRoute, expectedAction }
 */
const PRODUCTION_BASELINE = [
  // 1. PostHog alert
  {
    category: 'posthog',
    headers: { 'x-posthog-token': 'real-posthog-token-value' },
    body: { event: 'alert', error_type: 'test_error', count: 5 },
    expectedRoute: 'posthog-error',
    expectedAction: 'forward',
  },
  // 2a. Linear Issue
  {
    category: 'linear-Issue',
    headers: {},
    body: {
      webhookId: '3cafb372',
      action: 'create',
      type: 'Issue',
      data: { id: 'ISS-1', title: 'Test' },
    },
    expectedRoute: 'linear-to-droid',
    expectedAction: 'forward',
  },
  // 2b. Linear Comment
  {
    category: 'linear-Comment',
    headers: {},
    body: {
      webhookId: '3cafb372',
      action: 'create',
      type: 'Comment',
      data: { id: 'C-1', body: 'comment text' },
    },
    expectedRoute: 'linear-to-droid',
    expectedAction: 'forward',
  },
  // 3. Linear other (Project)
  {
    category: 'linear-other',
    headers: {},
    body: {
      webhookId: '3cafb372',
      action: 'update',
      type: 'Project',
      data: { id: 'P-1', name: 'MyProject' },
    },
    expectedRoute: 'none',
    expectedAction: 'none',
  },
  // 4. CI-Notify (Actions notify)
  {
    category: 'ci-notify',
    headers: {},
    body: {
      repo: 'hdot123-org/infra-core',
      pr_number: 183,
      run_url: 'https://github.com/hdot123-org/infra-core/actions/runs/12345',
    },
    expectedRoute: 'ci-complete',
    expectedAction: 'forward',
  },
  // 5. Ping
  {
    category: 'ping',
    headers: { 'x-github-event': 'ping' },
    body: { zen: 'Keep it simple', hook_id: 12345 },
    expectedRoute: 'none',
    expectedAction: 'none',
  },
  // 6. Push
  {
    category: 'push',
    headers: { 'x-github-event': 'push' },
    body: {
      ref: 'refs/heads/main',
      after: 'abc123',
      repository: { full_name: 'hdot123-org/infra-core' },
    },
    expectedRoute: 'wiki-refresh',
    expectedAction: 'forward',
  },
  // 7. Check_run failed (conclusion ∉ {success, skipped, neutral})
  {
    category: 'check_run-failed',
    headers: { 'x-github-event': 'check_run' },
    body: {
      action: 'completed',
      check_run: { conclusion: 'failure', name: 'CI' },
    },
    expectedRoute: 'none',
    expectedAction: 'none',
  },
  // 8. Check_run ok (conclusion ∈ {success, skipped, neutral})
  {
    category: 'check_run-ok',
    headers: { 'x-github-event': 'check_run' },
    body: {
      action: 'completed',
      check_run: { conclusion: 'success', name: 'CI' },
    },
    expectedRoute: 'none',
    expectedAction: 'none',
  },
  // 9. Unknown event
  {
    category: 'unknown',
    headers: { 'x-github-event': 'pull_request' },
    body: { action: 'opened', number: 42 },
    expectedRoute: 'none',
    expectedAction: 'none',
  },
];

describe('VAL-WPARITY-001: Differential verification — router.js vs production multiplexer', () => {
  for (const item of PRODUCTION_BASELINE) {
    it(`Category '${item.category}': router.js decision matches production`, () => {
      const githubEvent = item.headers['x-github-event'] || '';
      const headersObj = {};
      for (const [k, v] of Object.entries(item.headers)) {
        headersObj[k.toLowerCase()] = v;
      }

      const decision = route(githubEvent, item.body, headersObj);

      assert.equal(
        decision.route,
        item.expectedRoute,
        `Route mismatch for category '${item.category}': ` +
          `router.js='${decision.route}' vs production='${item.expectedRoute}'`
      );
      assert.equal(
        decision.action,
        item.expectedAction,
        `Action mismatch for category '${item.category}': ` +
          `router.js='${decision.action}' vs production='${item.expectedAction}'`
      );
    });
  }

  it('Summary: all 9 categories match (zero divergence)', () => {
    let matches = 0;
    let divergences = [];

    for (const item of PRODUCTION_BASELINE) {
      const githubEvent = item.headers['x-github-event'] || '';
      const headersObj = {};
      for (const [k, v] of Object.entries(item.headers)) {
        headersObj[k.toLowerCase()] = v;
      }

      const decision = route(githubEvent, item.body, headersObj);

      if (decision.route === item.expectedRoute && decision.action === item.expectedAction) {
        matches++;
      } else {
        divergences.push({
          category: item.category,
          workerRoute: decision.route,
          workerAction: decision.action,
          prodRoute: item.expectedRoute,
          prodAction: item.expectedAction,
        });
      }
    }

    const total = PRODUCTION_BASELINE.length;
    assert.equal(matches, total, `Expected ${total}/${total} matches, got ${matches}/${total}. Divergences: ${JSON.stringify(divergences)}`);
    assert.equal(divergences.length, 0, 'Zero divergence required');
  });
});
