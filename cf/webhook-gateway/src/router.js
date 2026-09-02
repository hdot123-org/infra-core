/**
 * Pure function routing — no side effects, fully testable.
 *
 * Aligns with n8n github-events-router-v3 Code node semantics:
 *
 * | Input                                         | Route         | Action        |
 * |-----------------------------------------------|---------------|---------------|
 * | No x-github-event + body.repo & body.pr_number | ci-complete   | forward       |
 * | x-github-event: push                          | wiki-refresh  | forward       |
 * | x-github-event: ping                          | none          | 200 + respond |
 * | check_run completed + conclusion ∉ {success,   | none          | log only      |
 * |   skipped, neutral}                            |               |               |
 * | All others                                     | none          | no forwarding |
 */

/**
 * Determine routing decision for a GitHub webhook event.
 *
 * @param {string} githubEvent - The x-github-event header value (may be empty string)
 * @param {object} payload - Parsed JSON body
 * @returns {{action: string, route: string, event: string, path?: string, tokenSecret?: string, reason?: string}}
 */
export function route(githubEvent, payload) {
  const event = githubEvent || '';

  // Case 1: No x-github-event header + body has repo & pr_number (Actions notify)
  if (!event && payload && payload.repo && payload.pr_number !== undefined) {
    return {
      action: 'forward',
      route: 'ci-complete',
      event: 'actions-notify',
      path: '/hooks/ci-complete',
      tokenSecret: 'CI_TOKEN',
    };
  }

  // Case 2: push event → wiki-refresh
  if (event === 'push') {
    return {
      action: 'forward',
      route: 'wiki-refresh',
      event: 'push',
      path: '/hooks/wiki-refresh',
      tokenSecret: 'WIKI_TOKEN',
    };
  }

  // Case 3: ping → no forwarding (handshake)
  if (event === 'ping') {
    return {
      action: 'none',
      route: 'none',
      event: 'ping',
      reason: 'ping event — handshake only',
    };
  }

  // Case 4: check_run completed with failure conclusion → log only, no forward
  if (event === 'check_run') {
    const action = payload && payload.action;
    const conclusion =
      payload && payload.check_run && payload.check_run.conclusion;

    if (action === 'completed') {
      const nonSuccessConclusions = [
        'failure',
        'timed_out',
        'cancelled',
        'action_required',
        'stale',
      ];
      if (conclusion && nonSuccessConclusions.includes(conclusion)) {
        return {
          action: 'none',
          route: 'none',
          event: 'check_run',
          reason: `check_run completed with conclusion=${conclusion} — log only, ci-complete channel covers CI notification`,
        };
      }
    }

    // Other check_run actions/conclusions → no forwarding
    return {
      action: 'none',
      route: 'none',
      event: 'check_run',
      reason: 'check_run — no forwarding for this action/conclusion',
    };
  }

  // Case 5: All others → no forwarding
  return {
    action: 'none',
    route: 'none',
    event: event || 'unknown',
    reason: `event '${event || 'unknown'}' — no forwarding rule`,
  };
}
