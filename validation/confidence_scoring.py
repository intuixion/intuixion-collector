"""
Confidence tier from source authority (tech direction Phase 1).

Tier is a deterministic function of the source types actually cited —
not a re-run of the semantic similarity score.

Hierarchy:
  high   — constitution or statute
  medium — regulation or code_of_conduct
  low    — guidance, commentary, or unknown

source_type is read from the Qdrant payload field when present,
otherwise inferred from the slug.
"""

import re

_SLUG_TYPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"constitution", re.I), "constitution"),
    (re.compile(
        r"_act_|companies.act|popia|fica|nca_|bcea|_lra_|_eea_|msa_|fsra|_cpa_|"
        r"national_credit|labour_relations|basic_conditions|employment_equity|"
        r"financial_sector|medical_schemes|consumer_protection",
        re.I,
    ), "statute"),
    (re.compile(r"regulation|directive|notice|determination|pronouncement", re.I), "regulation"),
    (re.compile(r"code_of|code\b|charter|standard", re.I), "code_of_conduct"),
    (re.compile(r"guidance|circular|guideline|bulletin|interpretation_note", re.I), "guidance"),
]

_TIER_ORDER = ["constitution", "statute", "regulation", "code_of_conduct", "guidance", "commentary"]

_TIER_LABEL: dict[str, str] = {
    "constitution": "high",
    "statute":      "high",
    "regulation":   "medium",
    "code_of_conduct": "medium",
    "guidance":     "low",
    "commentary":   "low",
}


def infer_source_type(chunk: dict) -> str:
    """Return source_type, falling back to slug-based inference."""
    explicit = (chunk.get("source_type") or "").strip()
    if explicit in _TIER_ORDER:
        return explicit
    slug = (chunk.get("slug") or chunk.get("name") or "").lower()
    for pattern, stype in _SLUG_TYPE_PATTERNS:
        if pattern.search(slug):
            return stype
    return "guidance"


def score(chunks: list[dict]) -> tuple[str, dict]:
    """
    Return (confidence_tier, source_type_breakdown) for a set of retrieved chunks.

    Example:
        tier, breakdown = score(retrieved_chunks)
        # tier == "high", breakdown == {"statute": 5, "regulation": 2, "guidance": 1}
    """
    breakdown: dict[str, int] = {}
    for chunk in chunks:
        stype = infer_source_type(chunk)
        breakdown[stype] = breakdown.get(stype, 0) + 1

    best_type = "guidance"
    for stype in _TIER_ORDER:
        if breakdown.get(stype, 0) > 0:
            best_type = stype
            break

    return _TIER_LABEL.get(best_type, "low"), breakdown
