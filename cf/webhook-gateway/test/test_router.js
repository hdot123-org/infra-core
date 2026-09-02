/**
 * Router unit tests — 5 routing cases aligned with n8n github-events-router-v3.
 * Uses node --test (built-in test runner).
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { route } from '../src/router.js';

describe('route() — 5-class routing matrix', () => {
  it('Case 1: Actions notify (no x-github-event + body.repo & body.pr_number) → ci-complete', () => {
    const decision = route('', { repo: 'test/repo', pr_number: 42 });
    assert.equal(decision.action, 'forward');
    assert.equal(decision.route, 'ci-complete');
    assert.equal(decision.event, 'actions-notify');
    assert.equal(decision.path, '/hooks/ci-complete');
    assert.equal(decision.tokenSecret, 'CI_TOKEN');
  });

  it('Case 2: push → wiki-refresh', () => {
    const decision = route('push', { ref: 'refs/heads/main' });
    assert.equal(decision.action, 'forward');
    assert.equal(decision.route, 'wiki-refresh');
    assert.equal(decision.event, 'push');
    assert.equal(decision.path, '/hooks/wiki-refresh');
    assert.equal(decision.tokenSecret, 'WIKI_TOKEN');
  });

  it('Case 3: ping → none (handshake)', () => {
    const decision = route('ping', { zen: 'testing' });
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'ping');
  });

  it('Case 4: check_run completed with failure conclusion → none (log only)', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'failure' },
    });
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'check_run');
    assert.match(decision.reason, /failure/);
  });

  it('Case 4b: check_run completed with success → none (ci-complete channel covers)', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'success' },
    });
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'check_run');
  });

  it('Case 4c: check_run completed with timed_out → none', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'timed_out' },
    });
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
  });

  it('Case 4d: check_run completed with skipped → none', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'skipped' },
    });
    assert.equal(decision.action, 'none');
  });

  it('Case 4e: check_run completed with neutral → none', () => {
    const decision = route('check_run', {
      action: 'completed',
      check_run: { conclusion: 'neutral' },
    });
    assert.equal(decision.action, 'none');
  });

  it('Case 5: unknown event → none', () => {
    const decision = route('pull_request', { action: 'opened' });
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'pull_request');
  });

  it('Case 5b: empty event, no repo/pr_number → none', () => {
    const decision = route('', { some_other_field: true });
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
    assert.equal(decision.event, 'unknown');
  });

  it('Case 5c: completely empty → none', () => {
    const decision = route('', {});
    assert.equal(decision.action, 'none');
    assert.equal(decision.route, 'none');
  });
});
