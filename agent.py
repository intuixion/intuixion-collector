"""
intuixion.ai — SA Regulatory RAG Agent

Interactive CLI agent powered by Claude + Qdrant. Retrieves relevant chunks
from the SA regulatory corpus and generates grounded answers with citations.

Install:
    pip install anthropic

Environment (.env):
    ANTHROPIC_API_KEY=sk-ant-...
    OPENAI_API_KEY=sk-...           (for embeddings)
    QDRANT_URL=http://localhost:6333 (omit for in-memory)
    COLLECTION_NAME=intuixion_sa_docs
    AGENT_MODEL=claude-sonnet-4-6   (optional override)

Usage:
    python agent.py                  # interactive chat
    python agent.py --sector healthcare
    python agent.py --query "What is the POPIA definition of personal information?" --no-chat
"""

import argparse
import json
import os
import sys
from typing import Optional

import anthropic
from dotenv import load_dotenv

from query import retrieve

load_dotenv()

MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-6")
MAX_CONTEXT_CHUNKS = 8
CACHE_MIN_TOKENS = 1024  # minimum tokens to make prompt caching worthwhile

# ---------------------------------------------------------------------------
# System prompt  (marked for prompt caching — static across turns)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are the intuixion.ai SA Regulatory Assistant, a specialist AI for South African law, \
regulation, and compliance. You have access to a curated corpus of SA regulatory documents spanning \
healthcare (Medical Schemes Act, PMBs, EML/STGs, NHA), financial services (FICA, NCA, FSRA, SARB \
directives, FSCA, JSE Listings Requirements), labour law (LRA, BCEA, EEA, B-BBEE), and cross-sector \
legislation (POPIA, Companies Act, CPA).

## How you work
1. You call the `retrieve_context` tool to find the most relevant sections from the regulatory corpus.
2. You answer based **only** on what the retrieved documents say, not on general knowledge.
3. Every factual claim must be traceable to a retrieved chunk. Cite the source document name and \
chunk number (e.g. "According to the NCA [nca_national_credit_act_2005, chunk 14]...").
4. If the corpus does not contain enough information to answer, say so clearly rather than guessing.
5. For complex questions, retrieve multiple times with different queries to gather all relevant context.

## Tone and format
- Professional, precise South African English (use "section" not "clause" for statutory references).
- Use numbered lists for multi-part answers (e.g. listing PMB conditions, FICA obligations).
- Flag when a document may be outdated or when the user should verify with a qualified professional.
- Do not answer questions unrelated to SA law, regulation, or compliance.

## Citation format
After each factual statement, add an inline citation: *[Source: {document name}, chunk {n}]*"""

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "retrieve_context",
        "description": (
            "Search the SA regulatory corpus for chunks relevant to a query. "
            "Call this before answering any factual question. "
            "Use `sector` to restrict scope when the topic is clearly sector-specific. "
            "Use `keyword` for exact statutory references (e.g. 'Section 11', 'PMB', 'PAYE')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query optimised for retrieval.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of chunks to retrieve (default 6, max 12).",
                    "default": 6,
                },
                "sector": {
                    "type": "string",
                    "enum": ["cross", "healthcare", "financial", "retail"],
                    "description": "Filter to a specific regulatory sector.",
                },
                "keyword": {
                    "type": "string",
                    "description": "Exact term that must appear in the result (e.g. 'Section 18', 'PMB').",
                },
            },
            "required": ["query"],
        },
    }
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------
def run_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name != "retrieve_context":
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    top_k = min(int(tool_input.get("top_k", 6)), MAX_CONTEXT_CHUNKS)
    chunks = retrieve(
        query=tool_input["query"],
        top_k=top_k,
        sector=tool_input.get("sector"),
        keyword=tool_input.get("keyword"),
    )

    if not chunks:
        return json.dumps({"result": "No relevant documents found for this query."})

    formatted = []
    for i, c in enumerate(chunks, 1):
        formatted.append(
            f"[Chunk {i}] {c['name']} (slug: {c['slug']}, relevance: {c['score']})\n"
            f"{c['text']}"
        )

    return json.dumps({
        "chunks_retrieved": len(chunks),
        "results": formatted,
    })


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
def run_agent(
    user_message: str,
    history: list[dict],
    sector_hint: Optional[str] = None,
    verbose: bool = False,
) -> tuple[str, list[dict]]:
    """
    Single agent turn. Returns (assistant_reply, updated_history).
    Handles multi-step tool use automatically.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Inject sector hint into message if provided
    if sector_hint:
        user_message = f"[Context: focusing on {sector_hint} sector]\n\n{user_message}"

    history = history + [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # prompt cache the system prompt
                }
            ],
            tools=TOOLS,
            messages=history,
        )

        if verbose:
            usage = response.usage
            print(
                f"  [API] stop={response.stop_reason}  "
                f"in={usage.input_tokens} out={usage.output_tokens} "
                f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)} "
                f"cache_write={getattr(usage, 'cache_creation_input_tokens', 0)}",
                file=sys.stderr,
            )

        # Append assistant turn to history
        history = history + [{"role": "assistant", "content": response.content}]

        if response.stop_reason == "end_turn":
            # Extract text reply
            reply = " ".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            return reply, history

        if response.stop_reason == "tool_use":
            # Execute all tool calls and append results
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if verbose:
                    print(f"  [TOOL] {block.name}({json.dumps(block.input)})", file=sys.stderr)
                result = run_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            history = history + [{"role": "user", "content": tool_results}]
            continue

        # Unexpected stop reason
        break

    return "I was unable to complete your request.", history


# ---------------------------------------------------------------------------
# Interactive CLI
# ---------------------------------------------------------------------------
def interactive(sector: Optional[str] = None, verbose: bool = False) -> None:
    print("intuixion.ai — SA Regulatory Assistant")
    print(f"Model: {MODEL} | Corpus: {os.getenv('COLLECTION_NAME', 'intuixion_sa_docs')}")
    if sector:
        print(f"Sector focus: {sector}")
    print("Type 'exit' or Ctrl-C to quit.\n")

    history: list[dict] = []
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "bye"):
            print("Goodbye.")
            break

        reply, history = run_agent(
            user_message=user_input,
            history=history,
            sector_hint=sector,
            verbose=verbose,
        )
        print(f"\nAssistant: {reply}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="intuixion.ai SA Regulatory RAG Agent")
    p.add_argument("--sector", choices=["cross", "healthcare", "financial", "retail"])
    p.add_argument("--query", help="Single query (non-interactive mode)")
    p.add_argument("--no-chat", action="store_true", help="Exit after one response")
    p.add_argument("--verbose", action="store_true", help="Print API usage stats")
    args = p.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set. Add it to .env or the shell.")

    if args.query or args.no_chat:
        query = args.query or input("Query: ").strip()
        reply, _ = run_agent(
            user_message=query,
            history=[],
            sector_hint=args.sector,
            verbose=args.verbose,
        )
        print(reply)
    else:
        interactive(sector=args.sector, verbose=args.verbose)


if __name__ == "__main__":
    main()
