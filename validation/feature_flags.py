"""
Feature flags — toggleable per tenant (tech direction cross-cutting practice).

Current implementation: env-var global flags. Phase 2 will add per-tenant
overrides from the database; all call sites use is_enabled() so no changes
at call sites are needed when that happens.

Usage:
    from validation.feature_flags import is_enabled
    if is_enabled("citation_validation", tenant_id):
        ...

Flags (set DISABLED_FEATURES=flag1,flag2 in .env to turn off):
    citation_validation   — Option A + retry + Option B judge
    audit_logging         — write every query to query_audit_log
    confidence_scoring    — compute and return confidence_tier
    saflii_links          — include SAFLII/NoteUp URLs in citations
"""

import os
from functools import lru_cache

_ALL_FLAGS = {
    "citation_validation",
    "audit_logging",
    "confidence_scoring",
    "saflii_links",
    "conflict_detection",   # Phase 2: cross-statute reconciliation note
}


@lru_cache(maxsize=1)
def _disabled_global() -> frozenset[str]:
    raw = os.getenv("DISABLED_FEATURES", "")
    return frozenset(f.strip().lower() for f in raw.split(",") if f.strip())


def is_enabled(flag: str, tenant_id: str | None = None) -> bool:
    """
    Return True if the feature is enabled for this tenant.
    Phase 2: extend this to check a per-tenant DB override before the global default.
    """
    if flag not in _ALL_FLAGS:
        return True  # unknown flags are on by default
    return flag not in _disabled_global()
