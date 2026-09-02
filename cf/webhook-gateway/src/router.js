/**
 * Pure function routing — no side effects, fully testable.
 *
 * Aligned with n8n Unified Events Multiplexer (github-events-router-v3, 2026-09-02 upgrade).
 * Classification matrix (9 categories):
 *
 * | Input                                               | Route           | Action        |
 * |-----------------------------------------------------|-----------------|---------------|
 * | x-posthog-token header present (PostHog alert)      | posthog-error   | forward       |
 * | Linear payload (webhookId + Issue/Comment)          | linear-to-droid | forward       |
 * | Linear payload (other resource types)               | none            | no forward    |
 * | No x-github-event + body.repo & body.pr_number      | ci-complete     | forward       |
 * | x-github-event: push                                | wiki-refresh    | forward       |
 * | x-github-event: ping                                | none            | 200 + respond |
 * | check_run completed + conclusion ∉ {success,        | none            | log only      |
 * |   skipped, neutral} (blacklist semantic)            |                 |               |
 * | All others                                          | none            | no forwarding |
 */

/**
 * Detect Linear webhook payload.
 * Linear payloads carry webhookId + action + type + data fields.
 * Issue and Comment resource types are forwarded; others → none.
 *
 * @param {string} githubEvent - The x-github-event header value
 * @param {object} payload - Parsed JSON body
 * @returns {{isLinear: boolean, resourceType?: string}}
 */
export function detectLinear(githubEvent, payload) {
  // Linear payloads arrive without x-github-event (or with empty string)
  // and carry a webhookId field plus action/type/data structure
  if (!payload || !payload.webhookId) return { isLinear: false };
  if (!payload.action || !payload.type || !payload.data) {
    return { isLinear: false };
  }
  return { isLinear: true, resourceType: payload.type };
}

/**
 * Determine routing decision for a webhook event.
 *
 * @param {string} githubEvent - The x-github-event header value (may be empty string)
 * @param {object} payload - Parsed JSON body
 * @param {object} headers - Request headers object (for posthog token detection)
 * @returns {{action: string, route: string, event: string, path?: string, tokenSecret?: string, reason?: string}}
 */
export function route(githubEvent, payload, headers) {
  const event = githubEvent || '';
  const hdrs = headers || {};

  // Case 0a: PostHog alert (x-posthog-token header present → unified path)
  const posthogToken =
    hdrs['x-posthog-token'] || hdrs['X-Posthog-Token'] || '';
  if (posthogToken) {
    return {
      action: 'forward',
      route: 'posthog-error',
      event: 'posthog',
      path: '/hooks/posthog-error',
      tokenSecret: 'POSTHOG_PASSTHROUGH',
    };
  }

  // Case 0b: Linear webhook (webhookId + action + type + data fingerprint)
  const linearDetect = detectLinear(event, payload);
  if (linearDetect.isLinear) {
    if (
      linearDetect.resourceType === 'Issue' ||
      linearDetect.resourceType === 'Comment'
    ) {
      return {
        action: 'forward',
        route: 'linear-to-droid',
        event: `linear-${linearDetect.resourceType.toLowerCase()}`,
        path: '/hooks/linear-to-droid',
        tokenSecret: 'LINEAR_WEBHOOK_TOKEN',
      };
    }
    // Other Linear resource types → none
    return {
      action: 'none',
      route: 'none',
      event: `linear-${(linearDetect.resourceType || 'unknown').toLowerCase()}`,
      reason: `Linear resource type '${linearDetect.resourceType}' — no forwarding rule`,
    };
  }

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

  // Case 4: check_run — blacklist semantic: conclusion ∉ {success, skipped, neutral} → none (log only)
  if (event === 'check_run') {
    const action = payload && payload.action;
    const conclusion =
      payload && payload.check_run && payload.check_run.conclusion;

    if (action === 'completed') {
      // Blacklist: only success/skipped/neutral are "ok" conclusions
      // Everything else (failure, timed_out, cancelled, action_required, stale, etc.) → log only
      const okConclusions = ['success', 'skipped', 'neutral'];
      if (conclusion && !okConclusions.includes(conclusion)) {
        return {
          action: 'none',
          route: 'none',
          event: 'check_run',
          reason: `check_run completed with conclusion=${conclusion} — log only, ci-complete channel covers CI notification`,
        };
      }
      // success/skipped/neutral → none (ci-complete channel covers CI notification)
      return {
        action: 'none',
        route: 'none',
        event: 'check_run',
        reason: `check_run completed with conclusion=${conclusion || 'unknown'} — no forwarding, ci-complete channel covers`,
      };
    }

    // Other check_run actions → no forwarding
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
