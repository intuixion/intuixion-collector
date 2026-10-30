"""
Option B — LLM-as-judge grounding check (tech direction Phase 1).

Async escalation path: fires only when BOTH Option A passes fail (first generation
+ one synchronous retry both return validation_status='flagged'). The primary
response is returned immediately; this runs in the background and updates the
audit log when it resolves.

The judge does NOT block the user response. It is an internal quality signal only.

Usage:
    import asyncio
    from validation.grounding_judge import judge_in_background
    judge_in_background(row_id, answer, chunks)
    # Returns immediately; judge runs as a background thread
"""

import json
import os
import threading


_JUDGE_PROMPT = """\
You are a grounding auditor for a South African regulatory AI system.

I will give you:
1. A claim made in a generated answer.
2. The text of the retrieved document chunk cited in support of that claim.

Your task: determine whether the chunk ACTUALLY SUPPORTS the claim.
- "supported" — the chunk directly contains the information asserted in the claim.
- "partial" — the chunk is related but does not fully support the specific claim.
- "unsupported" — the chunk does not support the claim, or the claim goes beyond what the chunk says.

Respond with a JSON object only — no prose:
{"verdict": "supported"|"partial"|"unsupported", "reason": "<one sentence>"}

Claim: {claim}

Chunk text:
{chunk_text}
"""


def _run_judge(row_id: str, flagged_clauses: list[str], chunks: list[dict]) -> None:
    """
    Run the LLM judge for each flagged clause against the most relevant retrieved chunk.
    Updates the audit log row on completion.
    """
    try:
        from agent import _get_llm_client
        from audit.logger import update_judge_result

        client = _get_llm_client()
        chunk_texts = [c.get("text", "") for c in chunks if c.get("text")]

        verdicts = []
        for clause in flagged_clauses[:4]:  # cap at 4 to limit cost
            best_chunk = max(
                chunk_texts,
                key=lambda t: sum(w in t.lower() for w in clause.lower().split()[:6]),
                default="",
            )
            if not best_chunk:
                verdicts.append({"clause": clause, "verdict": "no_chunk", "reason": "No retrieved chunk available"})
                continue

            prompt = _JUDGE_PROMPT.format(claim=clause[:400], chunk_text=best_chunk[:800])
            try:
                _default_judge = (
                    "global.anthropic.claude-haiku-4-5-20251001-v1:0"
                    if os.getenv("LLM_PROVIDER", "anthropic") == "bedrock"
                    else "claude-haiku-4-5-20251001"
                )
                resp = client.messages.create(
                    model=os.getenv("JUDGE_MODEL", _default_judge),
                    max_tokens=128,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.content[0].text.strip()
                try:
                    verdict = json.loads(raw)
                except json.JSONDecodeError:
                    verdict = {"verdict": "parse_error", "reason": raw[:120]}
            except Exception as exc:
                verdict = {"verdict": "error", "reason": str(exc)[:120]}

            verdicts.append({"clause": clause[:200], **verdict})

        update_judge_result(row_id, verdicts)
    except Exception:
        pass  # Judge failure never surfaces to the user


def judge_in_background(
    row_id: str,
    flagged_clauses: list[str],
    chunks: list[dict],
) -> None:
    """
    Fire-and-forget: start Option B judge as a daemon thread.
    Returns immediately; result is written to audit_log.flagged_clauses.
    """
    t = threading.Thread(
        target=_run_judge,
        args=(row_id, flagged_clauses, chunks),
        daemon=True,
        name=f"grounding-judge-{row_id[:8]}",
    )
    t.start()
