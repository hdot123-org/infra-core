/**
 * Router unit tests — 9 routing categories aligned with Unified Events Multiplexer.
 * Uses node --test (built-in test runner).
 *
 * Categories (priority order):
 * 1. PostHog: x-posthog-token header present → posthog-error forward
 * 2. Linear Issue/Comment → linear-to-droid forward
 * 3. Linear other types → none
 * 4. CI-Notify: no x-github-event + body.repo & body.pr_number → ci-complete forward
 * 5. ping → none
 * 6. push → wiki-refresh forward
 * 7. check_run failed: conclusion ∉ {success,skipped,neutral} → none (log only)
 * 8. check_run ok: conclusion ∈ {success,skipped,neutral} → none
 * 9. unknown → none
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { route, detectLinear } from '../src/router.js';

describe('route() — 9-class routing matrix', () => {
  it('Category 1: PostHog with x-posthog-token header → posthog-error forward', () => {
    const decision = route('', { some: 'data' }, { 'x-posthog-token': 'test-token' });
    assert.equal(decision.action, 'forward');
    assert.equal(decision.route, 'posthog-error');
    assert.equal(decision.event, 'posthog');
    assert.equal(decision.tokenSecret, 'POSTHOG_PASSTHROUGH');
  });

  it('Category 2a: Linear Issue → linear-to-droid forward', () => {
    const decision = route('', {
      webhookId: 'wh-123',
      action: 'create',
      type: 'Issue',
      data: { id: 'ISS-1' }
    }, {});
    assert.equal(decision.action, 'forward');
    assert.equal(decision.route, 'linear-to-droid');
    assert.equal(decision.event, 'linear-issue');
    assert.equal(decision.tokenSecret, 'LINEAR_WEBHOOK_TOKEN');
    assert.equal(decision.path, '/hooks/linear-to-droid');
  });

  it('Category 2b: Linear Comment → linear-to-droid forward', () => {
    const decision = route('', {
      webhookId: 'wh-123',
      action: 'create',
      type: 'Comment',
      data: { id: 'C-1' }
    }, {});
    assert.equal(decision.action, 'forward');
    assert.equal(decision.route, 'linear-to-droid');
    assert.equal(decision.event, 'linear-comment');
    assert.equal(decision.tokenSecret, 'LINEAR_WEBHOOK_TOKEN');
  });

  it('Category 3: Linear other type (Project) → none (no forwarding rule)', () => {
    const decision = route('', {
      webhookId: 'wh-123',
      action: 'update',
      type: 'Project',
      data: { id: 'P-1' }
    }, {});
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'linear-project');
    assert.match(decision.reason, /no forwarding rule/);
  });

  it('Category 3b: Linear other type (Cycle) → none', () => {
    const decision = route('', {
      webhookId: 'wh-123',
      action: 'start',
      type: 'Cycle',
      data: { id: 'CY-1' }
    }, {});
    assert.equal(decision.action, 'none');
    assert.equal(decision.event, 'linear-cycle');
  });

  it('Category 4: CI-Notify (no x-github-event + repo & pr_number) → ci-complete forward', () => {
    const decision = route('', { repo: 'test/repo', pr_number: 42 }, {});
    assert.equal(decision.action, 'forward');
    assert.equal(decision.route, 'ci-complete');
    assert.equal(decision.event, 'actions-notify');
    assert.equal(decision.tokenSecret, 'CI_TOKEN');
  });

  it('Category 5: ping → none (handshake)', () => {
    const decision = route('ping', { zen: 'testing' }, {});
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'ping');
  });

  it('Category 6: push → wiki-refresh forward', () => {
    const decision = route('push', { ref: 'refs/heads/main' }, {});
    assert.equal(decision.action, 'forward');
    assert.equal(decision.route, 'wiki-refresh');
    assert.equal(decision.event, 'push');
    assert.equal(decision.tokenSecret, 'WIKI_TOKEN');
    assert.equal(decision.path, '/hooks/wiki-refresh');
  });

  it('Category 7: check_run completed with failure conclusion → none (log only, blacklist)', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'failure' },
    }, {});
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'check_run');
    assert.match(decision.reason, /failure/);
  });

  it('Category 7b: check_run completed with timed_out → none (log only, blacklist)', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'timed_out' },
    }, {});
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.match(decision.reason, /timed_out/);
  });

  it('Category 7c: check_run completed with cancelled → none (log only, blacklist)', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'cancelled' },
    }, {});
    assert.equal(decision.action, 'none');
    assert.match(decision.reason, /cancelled/);
  });

  it('Category 8a: check_run completed with success → none (blacklist: ok conclusion)', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'success' },
    }, {});
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'check_run');
  });

  it('Category 8b: check_run completed with skipped → none (blacklist: ok conclusion)', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'skipped' },
    }, {});
    assert.equal(decision.action, 'none');
  });

  it('Category 8c: check_run completed with neutral → none (blacklist: ok conclusion)', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'neutral' },
    }, {});
    assert.equal(decision.action, 'none');
  });

  it('Category 9a: unknown event → none', () => {
    const decision = route('pull_request', { action: 'opened' }, {});
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'pull_request');
  });

  it('Category 9b: empty event, no repo/pr_number → none', () => {
    const decision = route('', { some_other_field: true }, {});
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'unknown');
  });

  it('Category 9c: completely empty → none', () => {
    const decision = route('', {}, {});
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
  });

  // Priority tests
  it('Priority: PostHog token takes precedence over Linear detection', () => {
    const decision = route('', {
      webhookId: 'wh-123',
      action: 'create',
      type: 'Issue',
      data: { id: 'ISS-1' }
    }, { 'x-posthog-token': 'test-token' });
    assert.equal(decision.action, 'forward');
    assert.equal(decision.route, 'posthog-error');
  });

  it('Priority: Linear detection takes precedence over CI-Notify', () => {
    const decision = route('', {
      webhookId: 'wh-123',
      action: 'create',
      type: 'Issue',
      data: { id: 'ISS-1' },
      repo: 'test/repo',
      pr_number: 42
    }, {});
    assert.equal(decision.action, 'forward');
    assert.equal(decision.route, 'linear-to-droid');
  });
});

describe('detectLinear() — Linear payload detection', () => {
  it('Detects Linear Issue payload', () => {
    const result = detectLinear('', {
      webhookId: 'wh-123',
      action: 'create',
      type: 'Issue',
      data: { id: 'ISS-1' }
    });
    assert.equal(result.isLinear, true);
    assert.equal(result.resourceType, 'Issue');
  });

  it('Detects Linear Comment payload', () => {
    const result = detectLinear('', {
      webhookId: 'wh-123',
      action: 'create',
      type: 'Comment',
      data: { id: 'C-1' }
    });
    assert.equal(result.isLinear, true);
    assert.equal(result.resourceType, 'Comment');
  });

  it('Returns isLinear=false for non-Linear payload', () => {
    const result = detectLinear('push', { ref: 'refs/heads/main' });
    assert.equal(result.isLinear, false);
  });

  it('Returns isLinear=false when webhookId missing', () => {
    const result = detectLinear('', {
      action: 'create',
      type: 'Issue',
      data: { id: 'ISS-1' }
    });
    assert.equal(result.isLinear, false);
  });

  it('Returns isLinear=false when action missing', () => {
    const result = detectLinear('', {
      webhookId: 'wh-123',
      type: 'Issue',
      data: { id: 'ISS-1' }
    });
    assert.equal(result.isLinear, false);
  });

  it('Returns isLinear=false for null payload', () => {
    const result = detectLinear('', null);
    assert.equal(result.isLinear, false);
  });
});
