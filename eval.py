"""
intuixion.ai — RAG Evaluation Suite

Runs a curated set of SA regulatory Q&A pairs against the pipeline.
Measures retrieval recall (did the right document appear in top-K?)
and answer quality (does the answer contain the expected ground truth?).

Usage:
    python eval.py                          # full eval
    python eval.py --sector healthcare      # one sector
    python eval.py --retrieval-only         # skip LLM, test retrieval only
    python eval.py --top-k 5               # stricter retrieval threshold

Results are written to data/eval_results.json.
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from query import retrieve

load_dotenv()

RESULTS_PATH = Path("data/eval_results.json")

# ---------------------------------------------------------------------------
# Eval dataset — ground-truth Q&A pairs
# Format:
#   question:        what the user would ask
#   expected_slug:   the source document that should appear in top-K results
#   ground_truth:    key phrase(s) that must appear in a correct answer
#   sector:          optional sector filter to pass to retrieval
# ---------------------------------------------------------------------------
EVAL_CASES = [
    # ── Cross-sector ────────────────────────────────────────────────────────
    {
        "id": "popia_01",
        "sector_group": "cross",
        "question": "What is the definition of personal information under POPIA?",
        "expected_slug": "popia_act_2013",
        "ground_truth": ["personal information", "data subject", "identifiable"],
    },
    {
        "id": "popia_02",
        "sector_group": "cross",
        "question": "What are the conditions for lawful processing of personal information under POPIA?",
        "expected_slug": "popia_act_2013",
        "ground_truth": ["conditions", "processing", "consent"],
    },
    {
        "id": "companies_01",
        "sector_group": "cross",
        "question": "What are the duties of a company director under the Companies Act?",
        "expected_slug": "companies_act_71_2008",
        "ground_truth": ["director", "fiduciary", "duty"],
    },
    {
        "id": "lra_01",
        "sector_group": "cross",
        "question": "What constitutes an automatically unfair dismissal under the Labour Relations Act?",
        "expected_slug": "lra_labour_relations_act_1995",
        "ground_truth": ["automatically unfair", "dismissal"],
    },
    {
        "id": "bcea_01",
        "sector_group": "cross",
        "question": "What is the maximum ordinary hours of work per week under the BCEA?",
        "expected_slug": "bcea_basic_conditions_employment",
        "ground_truth": ["45", "hours"],
    },
    {
        "id": "cpa_01",
        "sector_group": "cross",
        "question": "What right does a consumer have to return goods under the Consumer Protection Act?",
        "expected_slug": "cpa_consumer_protection_act_2008",
        "ground_truth": ["return", "goods", "cooling"],
    },
    # ── Healthcare ──────────────────────────────────────────────────────────
    {
        "id": "msa_01",
        "sector_group": "healthcare",
        "question": "What is the definition of a medical scheme under the Medical Schemes Act?",
        "expected_slug": "medical_schemes_act_131_1998",
        "ground_truth": ["medical scheme", "member", "contribution"],
    },
    {
        "id": "nha_01",
        "sector_group": "healthcare",
        "question": "What are the rights of healthcare users under the National Health Act?",
        "expected_slug": "national_health_act_61_2003",
        "ground_truth": ["rights", "health care user", "consent"],
    },
    {
        "id": "eml_01",
        "sector_group": "healthcare",
        "question": "What is the first-line treatment for hypertension in primary healthcare?",
        "expected_slug": "eml_essential_medicines_list",
        "ground_truth": ["hypertension", "antihypertensive", "blood pressure"],
    },
    {
        "id": "eml_02",
        "sector_group": "healthcare",
        "question": "What antiretroviral regimen is recommended for HIV positive adults at primary care level?",
        "expected_slug": "eml_essential_medicines_list",
        "ground_truth": ["HIV", "antiretroviral", "regimen"],
    },
    {
        "id": "cms_01",
        "sector_group": "healthcare",
        "question": "What are the prescribed minimum benefits that all medical schemes must cover?",
        "expected_slug": "medical_schemes_act_131_1998",
        "ground_truth": ["prescribed minimum benefit", "PMB", "diagnosis"],
    },
    {
        "id": "discovery_01",
        "sector_group": "healthcare",
        "question": "How many lives does Discovery Health Medical Scheme cover?",
        "expected_slug": "discovery_annual_report",
        "ground_truth": ["members", "lives", "beneficiaries"],
    },
    # ── Financial services ──────────────────────────────────────────────────
    {
        "id": "nca_01",
        "sector_group": "financial",
        "question": "What is reckless credit lending under the National Credit Act?",
        "expected_slug": "nca_national_credit_act_2005",
        "ground_truth": ["reckless", "credit", "affordability"],
    },
    {
        "id": "nca_02",
        "sector_group": "financial",
        "question": "What information must appear in a credit agreement under the NCA?",
        "expected_slug": "nca_national_credit_act_2005",
        "ground_truth": ["credit agreement", "principal debt", "interest"],
    },
    {
        "id": "fica_01",
        "sector_group": "financial",
        "question": "What are the customer due diligence requirements under FICA?",
        "expected_slug": "fica_financial_intelligence_centre_act",
        "ground_truth": ["due diligence", "identify", "verify"],
    },
    {
        "id": "fsra_01",
        "sector_group": "financial",
        "question": "What is the role of the Prudential Authority under the Financial Sector Regulation Act?",
        "expected_slug": "fsra_financial_sector_regulation_act",
        "ground_truth": ["Prudential Authority", "financial institution", "supervision"],
    },
    {
        "id": "jse_01",
        "sector_group": "financial",
        "question": "What are the minimum requirements for a company to list on the JSE Main Board?",
        "expected_slug": "jse_listings_requirements",
        "ground_truth": ["listing", "equity securities", "sponsor"],
    },
    {
        "id": "sars_01",
        "sector_group": "financial",
        "question": "How is capital gains tax calculated on the disposal of an asset?",
        "expected_slug": "sars_tax_guides",
        "ground_truth": ["capital gains", "proceeds", "base cost"],
    },
    {
        "id": "sars_02",
        "sector_group": "financial",
        "question": "What is the VAT rate in South Africa and what supplies are exempt?",
        "expected_slug": "sars_tax_guides",
        "ground_truth": ["VAT", "15%", "exempt"],
    },
    # ── Retail / labour ─────────────────────────────────────────────────────
    {
        "id": "eea_01",
        "sector_group": "retail",
        "question": "Who is a designated employer under the Employment Equity Act?",
        "expected_slug": "employment_equity_act",
        "ground_truth": ["designated employer", "50 employees", "employees"],
    },
    {
        "id": "bbbee_01",
        "sector_group": "retail",
        "question": "What are the five elements of the B-BBEE scorecard?",
        "expected_slug": "bbbee_codes_good_practice",
        "ground_truth": ["ownership", "management", "skills", "enterprise", "socio-economic"],
    },
    {
        "id": "ncr_01",
        "sector_group": "retail",
        "question": "What is the maximum interest rate a credit provider can charge under the NCA?",
        "expected_slug": "ncr_guidelines",
        "ground_truth": ["interest rate", "credit provider", "maximum"],
    },
    {
        "id": "nmw_01",
        "sector_group": "retail",
        "question": "What is the current national minimum wage in South Africa?",
        "expected_slug": "retail_wage_determinations",
        "ground_truth": ["minimum wage", "per hour", "R"],
    },
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class CaseResult:
    id: str
    question: str
    expected_slug: str
    sector_group: str
    retrieval_hit: bool = False          # expected_slug appeared in top-K
    retrieval_rank: Optional[int] = None # rank of first hit (1-indexed)
    retrieval_score: Optional[float] = None
    answer_correct: Optional[bool] = None
    answer_text: Optional[str] = None
    error: Optional[str] = None
    latency_s: float = 0.0


@dataclass
class EvalReport:
    run_at: str
    model: str
    top_k: int
    total: int
    retrieval_hits: int = 0
    answer_correct: int = 0
    answer_evaluated: int = 0
    cases: list[dict] = field(default_factory=list)

    @property
    def retrieval_recall(self) -> float:
        return self.retrieval_hits / self.total if self.total else 0.0

    @property
    def answer_accuracy(self) -> float:
        return self.answer_correct / self.answer_evaluated if self.answer_evaluated else 0.0


# ---------------------------------------------------------------------------
# Evaluation logic
# ---------------------------------------------------------------------------
def eval_retrieval(case: dict, top_k: int) -> CaseResult:
    result = CaseResult(
        id=case["id"],
        question=case["question"],
        expected_slug=case["expected_slug"],
        sector_group=case["sector_group"],
    )
    t0 = time.time()
    try:
        chunks = retrieve(query=case["question"], top_k=top_k)
        result.latency_s = round(time.time() - t0, 2)
        for rank, chunk in enumerate(chunks, 1):
            if chunk.get("slug") == case["expected_slug"]:
                result.retrieval_hit = True
                result.retrieval_rank = rank
                result.retrieval_score = chunk["score"]
                break
    except Exception as exc:
        result.error = str(exc)
        result.latency_s = round(time.time() - t0, 2)
    return result


def eval_answer(case: dict, result: CaseResult, agent_fn) -> None:
    try:
        reply, _ = agent_fn(
            user_message=case["question"],
            history=[],
            sector_hint=case.get("sector_group"),
            verbose=False,
        )
        result.answer_text = reply
        result.answer_correct = any(
            kw.lower() in reply.lower() for kw in case["ground_truth"]
        )
    except Exception as exc:
        result.error = str(exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="intuixion.ai RAG Evaluation")
    p.add_argument("--sector", choices=["cross", "healthcare", "financial", "retail"],
                   help="Evaluate only this sector")
    p.add_argument("--retrieval-only", action="store_true",
                   help="Skip LLM answer evaluation")
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--output", default=str(RESULTS_PATH))
    args = p.parse_args()

    cases = EVAL_CASES
    if args.sector:
        cases = [c for c in cases if c["sector_group"] == args.sector]

    if not args.retrieval_only and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — running retrieval-only eval.", file=sys.stderr)
        args.retrieval_only = True

    agent_fn = None
    if not args.retrieval_only:
        from agent import run_agent
        agent_fn = run_agent

    model = os.getenv("AGENT_MODEL", "claude-sonnet-4-6") if not args.retrieval_only else "retrieval-only"
    report = EvalReport(
        run_at=datetime.now().isoformat(),
        model=model,
        top_k=args.top_k,
        total=len(cases),
    )

    print(f"\nintuixion.ai Evaluation")
    print(f"  Cases    : {len(cases)}")
    print(f"  Top-K    : {args.top_k}")
    print(f"  Mode     : {'retrieval-only' if args.retrieval_only else 'full (retrieval + answer)'}\n")

    for case in cases:
        print(f"  [{case['id']}] {case['question'][:70]}...")
        result = eval_retrieval(case, args.top_k)

        if result.retrieval_hit:
            report.retrieval_hits += 1
            print(f"    retrieval: HIT  rank={result.retrieval_rank}  score={result.retrieval_score}  ({result.latency_s}s)")
        else:
            status = f"MISS  expected={case['expected_slug']}"
            if result.error:
                status += f"  error={result.error}"
            print(f"    retrieval: {status}  ({result.latency_s}s)")

        if not args.retrieval_only and agent_fn:
            report.answer_evaluated += 1
            eval_answer(case, result, agent_fn)
            if result.answer_correct:
                report.answer_correct += 1
            verdict = "CORRECT" if result.answer_correct else "WRONG"
            print(f"    answer  : {verdict}")

        report.cases.append(asdict(result))

    print(f"\n{'='*50}")
    print(f"Retrieval recall @{args.top_k}: {report.retrieval_hits}/{report.total} "
          f"({report.retrieval_recall:.0%})")
    if not args.retrieval_only:
        print(f"Answer accuracy          : {report.answer_correct}/{report.answer_evaluated} "
              f"({report.answer_accuracy:.0%})")
    print(f"{'='*50}")

    out = Path(args.output)
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
