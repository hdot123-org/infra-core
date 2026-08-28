#!/usr/bin/env python3
"""Wrapper: delegates to infra_core.engine.droid_review.publish_findings.

Re-exports validate_findings so run_shard.sh can import it via
`from droid_review.publish_findings import validate_findings`.
"""

from infra_core.engine.droid_review.publish_findings import main, validate_findings

__all__ = ["main", "validate_findings"]

if __name__ == "__main__":
    main()
