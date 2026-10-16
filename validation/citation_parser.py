"""
Option A deterministic citation validator (tech direction Phase 1).

Parses [slug, chunk N] tags from generated answers and verifies:
  1. Every claim-bearing clause has an adjacent citation tag.
  2. Every cited slug was actually in the retrieved set (catches hallucinations).

Returns ValidationResult with status and the list of offending clauses.
On failure the caller should attempt one synchronous repair pass (see repair_prompt).
"""

import re
from dataclasses import dataclass, field

# Modal verbs / obligation phrases that signal a legal claim
_CLAIM_VERBS = re.compile(
    r"\b(may|must|shall|is required to|are required to|is prohibited from|"
    r"must not|may not|is entitled to|shall not|requires|mandates|"
    r"is obliged to|cannot|is not permitted)\b",
    re.IGNORECASE,
)

# [slug_name, chunk N] or [slug chunk N] or [chunk:ID] or [Source, chunk 5]
_CITATION_TAG = re.compile(
    r"\[([^\]]{3,120})\]",
)
_CHUNK_MARKER = re.compile(r"chunk\s*[\d:]+", re.IGNORECASE)


@dataclass
class ValidationResult:
    status: str                              # 'grounded' | 'flagged'
    flagged_clauses: list[str] = field(default_factory=list)
    cited_ids: list[str] = field(default_factory=list)
    hallucinated_ids: list[str] = field(default_factory=list)


def validate(answer: str, retrieved_slugs: set[str]) -> ValidationResult:
    """
    Check grounding. retrieved_slugs is the set of slug values from the
    chunks returned by retrieve() for this query.
    """
    sentences = _split_sentences(answer)
    flagged: list[str] = []
    cited_ids: list[str] = []
    hallucinated: list[str] = []

    for sentence in sentences:
        raw_tags = _CITATION_TAG.findall(sentence)
        # Only treat as citation tags those that contain a chunk marker
        tags = [t for t in raw_tags if _CHUNK_MARKER.search(t)]

        # Check for hallucinated citations
        for tag in tags:
            cited_ids.append(tag)
            if retrieved_slugs:
                slug_candidate = re.split(r"[,\s]", tag)[0].strip().lower()
                if not any(slug_candidate in s.lower() for s in retrieved_slugs):
                    hallucinated.append(tag)
                    flagged.append(f"Hallucinated citation [{tag}]: {sentence.strip()[:120]}")

        # Claim with no citation
        if _CLAIM_VERBS.search(sentence) and not tags:
            # Skip boilerplate disclaimers ("you should consult a professional")
            if not re.search(r"\b(consult|seek|qualified professional|verify)\b", sentence, re.I):
                flagged.append(sentence.strip()[:200])

    if flagged or hallucinated:
        return ValidationResult(
            status="flagged",
            flagged_clauses=list(dict.fromkeys(flagged)),  # deduplicate, preserve order
            cited_ids=cited_ids,
            hallucinated_ids=hallucinated,
        )
    return ValidationResult(status="grounded", cited_ids=cited_ids)


def repair_prompt(original_question: str, flagged_clauses: list[str]) -> str:
    """
    Instruction injected on the synchronous retry pass.
    The caller prepends this to a fresh generation request.
    """
    clauses = "\n".join(f"  - {c}" for c in flagged_clauses[:6])
    return (
        "Your previous answer had claims that lacked citations to the retrieved corpus, "
        "or cited sources not in the retrieved set. The affected clauses were:\n"
        f"{clauses}\n\n"
        "Please answer the original question again. For every statement about what a law "
        "requires, permits, or prohibits, immediately follow it with a citation in the "
        "format [source_slug, chunk N] pointing to the retrieved chunk that supports it. "
        "Do not assert anything that is not directly supported by the retrieved passages.\n\n"
        f"Original question: {original_question}"
    )


def _split_sentences(text: str) -> list[str]:
    # Split on sentence-ending punctuation followed by space+capital, or on newlines
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\[\-])|(?<=\n)", text)
    return [p.strip() for p in parts if p.strip()]
