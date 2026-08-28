#!/usr/bin/env bash
# run_shard.sh — CI-facing wrapper
# Delegates to the engine copy at src/infra_core/engine/droid_review/run_shard.sh
# so the workflow's `bash scripts/droid_review/run_shard.sh` resolves correctly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_SCRIPT="$(cd "$SCRIPT_DIR/../../src/infra_core/engine/droid_review" && pwd)/run_shard.sh"

if [ ! -f "$ENGINE_SCRIPT" ]; then
  echo "::error::Engine run_shard.sh not found at $ENGINE_SCRIPT"
  exit 1
fi

exec bash "$ENGINE_SCRIPT" "$@"
