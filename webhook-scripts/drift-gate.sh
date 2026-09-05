#!/bin/bash
# drift-gate.sh — three-state drift gate (architecture §2.1)
#
# Checks whether the production webhook scripts directory is in sync with
# the repository's webhook-scripts/ managed files. Three states:
#
#   GATE_INVALID (exit 2): baseline untrustworthy — do not judge drift
#     - Not a git repository
#     - Not on 'main' branch
#     - HEAD != origin/main (after git fetch)
#     - webhook-scripts/ or src/infra_core/engine/ working tree dirty
#
#   IN_SYNC (exit 0): baseline trustworthy, --check reports no drift
#
#   DRIFT (exit 1): baseline trustworthy, --check reports drift
#     Alert with per-file diff --stat. Never triggers sync. Direction
#     must be judged by a human reading the diff.
#
# Usage:
#   drift-gate.sh --repo-root PATH [--prod-root PATH]
#
# Options:
#   --repo-root PATH   Repository root (required; launchd CWD is not a git repo)
#   --prod-root PATH   Production directory (default: ~/.factory/webhook/scripts)
#   --check            (ignored; always in check mode — gate never syncs)

set -uo pipefail

# === Parameters ===
REPO_ROOT=""
PROD_ROOT="${HOME}/.factory/webhook/scripts"

usage() {
    echo "Usage: $0 --repo-root PATH [--prod-root PATH]"
    echo ""
    echo "Three-state drift gate (architecture §2.1):"
    echo "  GATE_INVALID (exit 2): baseline untrustworthy"
    echo "  IN_SYNC (exit 0):      baseline trustworthy, no drift"
    echo "  DRIFT (exit 1):        baseline trustworthy, drift detected"
    echo ""
    echo "Options:"
    echo "  --repo-root PATH   Repository root (required)"
    echo "  --prod-root PATH   Production directory (default: ~/.factory/webhook/scripts)"
    exit 1
}

log() {
    echo "[drift-gate] $*"
}

gate_invalid() {
    log "GATE_INVALID: $1"
    exit 2
}

# === Parse arguments ===
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-root)
            REPO_ROOT="$2"
            shift 2
            ;;
        --prod-root)
            PROD_ROOT="$2"
            shift 2
            ;;
        --check)
            # Always in check mode — gate never syncs
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "ERROR: Unknown option: $1" >&2
            usage
            ;;
    esac
done

if [[ -z "$REPO_ROOT" ]]; then
    # Try to auto-detect from current git context
    REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    if [[ -z "$REPO_ROOT" ]]; then
        # Not in a git repo and no --repo-root given → GATE_INVALID
        echo "[drift-gate] GATE_INVALID: --repo-root not provided and not in a git repository" >&2
        exit 2
    fi
fi

if [[ ! -d "$REPO_ROOT" ]]; then
    gate_invalid "REPO_ROOT does not exist: $REPO_ROOT"
fi

cd "$REPO_ROOT" || gate_invalid "Cannot cd to REPO_ROOT: $REPO_ROOT"

# === Pre-flight checks (GATE_INVALID conditions) ===

# 1. Must be a git repository
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    gate_invalid "Not a git repository: $REPO_ROOT"
fi

# 2. Must be on 'main' branch
CURRENT_BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || true)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    gate_invalid "Not on 'main' branch (current: $CURRENT_BRANCH)"
fi

# 3. git fetch must succeed
if ! git fetch origin >/dev/null 2>&1; then
    gate_invalid "git fetch origin failed"
fi

# 4. HEAD must equal origin/main
LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_MAIN="$(git rev-parse origin/main 2>/dev/null || true)"
if [[ -z "$REMOTE_MAIN" ]]; then
    gate_invalid "Cannot resolve origin/main"
fi
if [[ "$LOCAL_HEAD" != "$REMOTE_MAIN" ]]; then
    gate_invalid "HEAD != origin/main (local: ${LOCAL_HEAD:0:8}, remote: ${REMOTE_MAIN:0:8})"
fi

# 5. webhook-scripts/ must have clean working tree
WEBHOOK_DIRTY="$(git status --porcelain webhook-scripts/ 2>/dev/null)"
if [[ -n "$WEBHOOK_DIRTY" ]]; then
    gate_invalid "webhook-scripts/ working tree dirty"
fi

# 6. src/infra_core/engine/ must have clean working tree
ENGINE_DIRTY="$(git status --porcelain src/infra_core/engine/ 2>/dev/null)"
if [[ -n "$ENGINE_DIRTY" ]]; then
    gate_invalid "src/infra_core/engine/ working tree dirty"
fi

# === Baseline trustworthy — run --check ===
SYNC_SCRIPT="${REPO_ROOT}/webhook-scripts/sync-webhook-scripts.sh"

if [[ ! -f "$SYNC_SCRIPT" ]]; then
    gate_invalid "sync-webhook-scripts.sh not found at $SYNC_SCRIPT"
fi

log "Baseline trustworthy, running sync --check"
CHECK_OUTPUT="$(bash "$SYNC_SCRIPT" --check --repo-root "$REPO_ROOT" --prod-root "$PROD_ROOT" 2>&1)"
CHECK_EXIT=$?

if [[ $CHECK_EXIT -eq 0 ]]; then
    log "IN_SYNC: all managed files in sync"
    echo "$CHECK_OUTPUT"
    exit 0
else
    log "DRIFT: sync --check reported drift"
    echo "$CHECK_OUTPUT"
    # Per-file diff --stat for alert (read-only, no sync)
    log "DRIFT details:"
    # Get list of managed files from MANIFEST.sh
    MANIFEST="${REPO_ROOT}/webhook-scripts/MANIFEST.sh"
    if [[ -f "$MANIFEST" ]]; then
        MANAGED_FILES=()
        # shellcheck source=/dev/null disable=SC1091
        source "$MANIFEST"
        for file in "${MANAGED_FILES[@]:-}"; do
            [[ -z "$file" ]] && continue
            REPO_FILE="${REPO_ROOT}/webhook-scripts/${file}"
            PROD_FILE="${PROD_ROOT}/${file}"
            if [[ -f "$REPO_FILE" && -f "$PROD_FILE" ]]; then
                if ! diff -q "$REPO_FILE" "$PROD_FILE" >/dev/null 2>&1; then
                    log "  ${file}: differs"
                elif [[ ! -f "$PROD_FILE" ]]; then
                    log "  ${file}: missing in production"
                fi
            elif [[ -f "$REPO_FILE" && ! -f "$PROD_FILE" ]]; then
                log "  ${file}: missing in production"
            fi
        done
    fi
    exit 1
fi
