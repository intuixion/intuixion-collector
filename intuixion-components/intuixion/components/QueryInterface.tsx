"use client";

import { useState, useRef, useCallback } from "react";

interface CitationItem {
  slug: string;
  name: string;
  sector: string;
  chunk_idx: number;
  chunk_count: number;
  score: number;
  text: string;
  source_url: string;
  source_type: string;
}

type Phase = "idle" | "loading" | "streaming" | "done" | "error";

interface QueryState {
  phase: Phase;
  answer: string;
  citations: CitationItem[];
  confidenceTier: string;
  hasConflict: boolean;
  conflictFamilies: string[];
  validationStatus: string;
  totalMs: number;
  error: string | null;
}

const INITIAL: QueryState = {
  phase: "idle",
  answer: "",
  citations: [],
  confidenceTier: "",
  hasConflict: false,
  conflictFamilies: [],
  validationStatus: "",
  totalMs: 0,
  error: null,
};

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "https://intuixion-api.fly.dev";

export default function QueryInterface() {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<QueryState>(INITIAL);
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = useCallback(async () => {
    const q = question.trim();
    if (!q || state.phase === "loading" || state.phase === "streaming") return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState({ ...INITIAL, phase: "loading" });

    try {
      const res = await fetch(`${API_URL}/v1/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, top_k: 12 }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop()!;

        for (const part of parts) {
          if (!part.startsWith("data: ")) continue;
          let evt: Record<string, unknown>;
          try {
            evt = JSON.parse(part.slice(6));
          } catch {
            continue;
          }

          if (evt.type === "citations") {
            setState((s) => ({
              ...s,
              phase: "streaming",
              citations: (evt.citations as CitationItem[]) ?? [],
              confidenceTier: (evt.confidence_tier as string) ?? "",
              hasConflict: (evt.has_conflict as boolean) ?? false,
              conflictFamilies: (evt.conflict_families as string[]) ?? [],
            }));
          } else if (evt.type === "token") {
            setState((s) => ({
              ...s,
              answer: s.answer + (evt.content as string),
            }));
          } else if (evt.type === "done") {
            setState((s) => ({
              ...s,
              phase: "done",
              validationStatus: (evt.validation_status as string) ?? "",
              totalMs: (evt.total_ms as number) ?? 0,
            }));
          } else if (evt.type === "error") {
            setState((s) => ({
              ...s,
              phase: "error",
              error: (evt.detail as string) ?? "Unknown error",
            }));
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name === "AbortError") return;
      setState((s) => ({
        ...s,
        phase: "error",
        error: err instanceof Error ? err.message : "Request failed",
      }));
    }
  }, [question, state.phase]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  };

  const { phase, answer, citations, confidenceTier, hasConflict, conflictFamilies, validationStatus, totalMs, error } = state;
  const isActive = phase === "loading" || phase === "streaming";
  const hasResults = citations.length > 0 || answer;

  return (
    <div style={s.wrapper}>
      {/* Input */}
      <div style={s.inputCard}>
        <textarea
          ref={textareaRef}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question about South African regulation… (⌘↵ or Ctrl↵ to submit)"
          style={s.textarea}
          rows={3}
          disabled={isActive}
        />
        <div style={s.inputFooter}>
          <span style={s.hint}>⌘↵ to submit · Answers cite exact statutory provisions</span>
          <button
            onClick={submit}
            disabled={isActive || !question.trim()}
            style={{
              ...s.submitBtn,
              opacity: isActive || !question.trim() ? 0.45 : 1,
              cursor: isActive || !question.trim() ? "not-allowed" : "pointer",
            }}
          >
            {isActive ? "Thinking…" : "Ask →"}
          </button>
        </div>
      </div>

      {/* Conflict banner */}
      {hasConflict && conflictFamilies.length > 0 && (
        <div style={s.conflictBanner}>
          <span style={s.conflictIcon}>⚠</span>
          <span>
            This question draws on <strong>{conflictFamilies.length} statutes</strong>:{" "}
            {conflictFamilies.slice(0, 6).join(", ")}.
            Review the reconciliation note in the answer before relying on it.
          </span>
        </div>
      )}

      {/* Loading dots */}
      {phase === "loading" && (
        <div style={s.loadingRow}>
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              style={{ ...s.dot, animationDelay: `${i * 0.2}s` }}
            />
          ))}
          <span style={s.loadingText}>Retrieving relevant provisions…</span>
        </div>
      )}

      {/* Error */}
      {phase === "error" && error && (
        <div style={s.errorBanner}>
          <strong>Error: </strong>{error}
        </div>
      )}

      {/* Results */}
      {hasResults && (
        <div style={s.results}>
          {/* Citations */}
          {citations.length > 0 && (
            <aside style={s.citationsPanel}>
              <p style={s.panelLabel}>Sources ({citations.length})</p>
              <div style={s.citationsList}>
                {citations.map((c, i) => (
                  <div key={i} style={s.citationCard}>
                    <div style={s.citationHeader}>
                      <span style={s.citationSlug}>{c.slug}</span>
                      <span style={s.citationScore}>
                        {(c.score * 100).toFixed(0)}%
                      </span>
                    </div>
                    <p style={s.citationName}>{c.name}</p>
                    <p style={s.citationText}>
                      {c.text.length > 160
                        ? c.text.slice(0, 160) + "…"
                        : c.text}
                    </p>
                    {c.source_url && (
                      <a
                        href={c.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={s.citationLink}
                      >
                        View source ↗
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </aside>
          )}

          {/* Answer */}
          {answer && (
            <article style={s.answerPanel}>
              <div style={s.answerHeader}>
                <p style={s.panelLabel}>Answer</p>
                {phase === "done" && (
                  <div style={s.metaRow}>
                    <ValidationBadge status={validationStatus} />
                    {confidenceTier && <ConfidenceBadge tier={confidenceTier} />}
                    <span style={s.latency}>{(totalMs / 1000).toFixed(1)}s</span>
                  </div>
                )}
              </div>
              <div style={s.answerText}>{answer}</div>
              {phase === "streaming" && (
                <span style={s.cursor} aria-hidden>▌</span>
              )}
            </article>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── Badge helpers ─── */

const BADGE_BASE: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 500,
  padding: "3px 10px",
  borderRadius: 20,
  display: "inline-block",
  fontFamily: "var(--font-body)",
};

function ValidationBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; bg: string; color: string }> = {
    grounded: { label: "Grounded ✓", bg: "var(--success-light)", color: "var(--success)" },
    flagged: { label: "Flagged ⚠", bg: "var(--gold-light)", color: "var(--gold)" },
    not_validated: { label: "Unverified", bg: "rgba(0,0,0,0.05)", color: "var(--ink-faint)" },
  };
  const cfg = map[status] ?? { label: status, bg: "rgba(0,0,0,0.05)", color: "var(--ink-faint)" };
  return (
    <span style={{ ...BADGE_BASE, background: cfg.bg, color: cfg.color }}>
      {cfg.label}
    </span>
  );
}

function ConfidenceBadge({ tier }: { tier: string }) {
  const map: Record<string, { label: string; bg: string; color: string }> = {
    high: { label: "High confidence", bg: "var(--success-light)", color: "var(--success)" },
    medium: { label: "Medium confidence", bg: "var(--gold-light)", color: "var(--gold)" },
    low: { label: "Low confidence", bg: "rgba(0,0,0,0.05)", color: "var(--ink-faint)" },
  };
  const cfg = map[tier] ?? { label: tier, bg: "rgba(0,0,0,0.05)", color: "var(--ink-faint)" };
  return (
    <span style={{ ...BADGE_BASE, background: cfg.bg, color: cfg.color }}>
      {cfg.label}
    </span>
  );
}

/* ─── Styles ─── */
const s: Record<string, React.CSSProperties> = {
  wrapper: {
    maxWidth: 1080,
    margin: "0 auto",
    padding: "0 2.5rem 4rem",
    display: "flex",
    flexDirection: "column",
    gap: "1.25rem",
  },

  inputCard: {
    background: "var(--surface-card)",
    border: "0.5px solid var(--border-strong)",
    borderRadius: "var(--radius-lg)",
    overflow: "hidden",
    boxShadow: "0 2px 12px rgba(0,0,0,0.05)",
  },

  textarea: {
    width: "100%",
    padding: "1.25rem 1.5rem",
    border: "none",
    outline: "none",
    resize: "none",
    fontSize: 16,
    fontFamily: "var(--font-body)",
    color: "var(--ink)",
    background: "transparent",
    lineHeight: 1.6,
  },

  inputFooter: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "0.75rem 1.5rem",
    borderTop: "0.5px solid var(--border)",
    background: "rgba(247,245,240,0.6)",
  },

  hint: {
    fontSize: 12,
    color: "var(--ink-faint)",
  },

  submitBtn: {
    background: "var(--ink)",
    color: "#fff",
    padding: "9px 22px",
    borderRadius: "var(--radius-sm)",
    fontSize: 14,
    fontWeight: 500,
    border: "none",
    fontFamily: "var(--font-body)",
    transition: "background 0.2s",
  },

  conflictBanner: {
    display: "flex",
    gap: "0.75rem",
    alignItems: "flex-start",
    background: "var(--gold-light)",
    border: "0.5px solid rgba(201,146,42,0.3)",
    borderRadius: "var(--radius-md)",
    padding: "0.875rem 1.25rem",
    fontSize: 13,
    color: "var(--gold)",
    lineHeight: 1.55,
  },

  conflictIcon: { flexShrink: 0 },

  loadingRow: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    padding: "0.5rem 0",
  },

  dot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "var(--ink-faint)",
    display: "inline-block",
    animation: "pulse 1.4s ease-in-out infinite",
  },

  loadingText: {
    fontSize: 13,
    color: "var(--ink-faint)",
    marginLeft: "0.25rem",
  },

  errorBanner: {
    background: "#fef2f2",
    border: "0.5px solid rgba(220,38,38,0.2)",
    borderRadius: "var(--radius-md)",
    padding: "0.875rem 1.25rem",
    fontSize: 13,
    color: "#dc2626",
  },

  results: {
    display: "grid",
    gridTemplateColumns: "300px 1fr",
    gap: "1.5rem",
    alignItems: "start",
  },

  citationsPanel: {
    background: "var(--surface-card)",
    border: "0.5px solid var(--border)",
    borderRadius: "var(--radius-lg)",
    padding: "1.25rem",
    overflow: "hidden",
  },

  panelLabel: {
    fontSize: 11,
    fontFamily: "var(--font-body)",
    fontWeight: 500,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    color: "var(--ink-faint)",
    marginBottom: "1rem",
  },

  citationsList: {
    display: "flex",
    flexDirection: "column",
    gap: "0.625rem",
  },

  citationCard: {
    padding: "0.75rem 0.875rem",
    background: "var(--surface)",
    borderRadius: "var(--radius-sm)",
    border: "0.5px solid var(--border)",
  },

  citationHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "0.25rem",
    gap: "0.5rem",
  },

  citationSlug: {
    fontSize: 10,
    fontFamily: "monospace",
    color: "var(--accent)",
    letterSpacing: "0.02em",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    flex: 1,
  },

  citationScore: {
    fontSize: 11,
    color: "var(--ink-faint)",
    fontWeight: 500,
    flexShrink: 0,
  },

  citationName: {
    fontSize: 12,
    fontWeight: 500,
    color: "var(--ink)",
    lineHeight: 1.35,
    marginBottom: "0.4rem",
  },

  citationText: {
    fontSize: 11,
    color: "var(--ink-muted)",
    lineHeight: 1.55,
    marginBottom: "0.4rem",
  },

  citationLink: {
    fontSize: 11,
    color: "var(--accent)",
    fontWeight: 500,
  },

  answerPanel: {
    background: "var(--surface-card)",
    border: "0.5px solid var(--border)",
    borderRadius: "var(--radius-lg)",
    padding: "1.5rem",
  },

  answerHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "1rem",
    flexWrap: "wrap",
    gap: "0.5rem",
  },

  metaRow: {
    display: "flex",
    gap: "0.5rem",
    alignItems: "center",
    flexWrap: "wrap",
  },

  latency: {
    fontSize: 11,
    color: "var(--ink-faint)",
  },

  answerText: {
    fontSize: 15,
    color: "var(--ink-muted)",
    lineHeight: 1.75,
    whiteSpace: "pre-wrap",
    fontWeight: 300,
  },

  cursor: {
    display: "inline-block",
    animation: "pulse 1s ease-in-out infinite",
    color: "var(--accent)",
    marginLeft: 1,
  },
};
