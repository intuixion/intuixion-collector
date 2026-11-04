"""
Phase 2 — Cross-statute conflict detection (MVP).

Heuristic: if retrieved chunks span 3+ distinct statute families, prepend a
reconciliation note to the user message so the agent explicitly addresses any
conflicting obligations before answering.

Future upgrade: replace the count heuristic with a lightweight Haiku LLM scan
that checks specific modal-verb conflicts (must/must not, may/may not) across
the retrieved chunk texts.
"""

# Map slug prefixes → statute family display name (longest-prefix wins)
_FAMILIES: list[tuple[str, str]] = sorted(
    [
        ("constitution", "Constitution"),
        ("companies_act", "Companies Act"),
        ("companies", "Companies Act"),
        ("popia", "POPIA"),
        ("paja", "PAJA"),
        ("fica", "FICA"),
        ("fsra", "FSRA"),
        ("nca", "NCA"),
        ("bcea", "BCEA"),
        ("lra", "LRA"),
        ("eea", "EEA"),
        ("cpa", "CPA"),
        ("msa", "MSA"),
        ("bbbee", "B-BBEE"),
        ("prescription", "Prescription Act"),
        ("king", "King IV"),
    ],
    key=lambda t: -len(t[0]),  # longest prefix first
)


def _statute_family(slug: str) -> str:
    for prefix, name in _FAMILIES:
        if slug.startswith(prefix):
            return name
    return slug.split("_")[0].upper()


def detect_conflicts(chunks: list[dict]) -> dict:
    """
    Scan retrieved chunks for potential cross-statute conflicts.

    Returns:
        {
            "has_conflict": bool,
            "families": list[str],     -- statute families present in chunks
            "reconcile_note": str,     -- inject into agent prompt when has_conflict
        }
    """
    families = sorted(
        {_statute_family(c.get("slug", "")) for c in chunks if c.get("slug")}
    )

    if len(families) < 3:
        return {"has_conflict": False, "families": families, "reconcile_note": ""}

    reconcile_note = (
        f"Note: this question draws on {len(families)} statutes "
        f"({', '.join(families[:6])}). "
        "Before answering, explicitly check whether any statute imposes an obligation "
        "that conflicts with or qualifies an obligation in another. "
        "Where obligations conflict, state which takes precedence and why "
        "(e.g. lex specialis, later-in-time, or express override)."
    )
    return {"has_conflict": True, "families": families, "reconcile_note": reconcile_note}
