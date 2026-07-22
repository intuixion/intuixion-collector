"use client";

import { useState, useEffect } from "react";

/* ─── Animated typing demo ─── */
const DEMO_QUERY = "What are the penalty clauses if the buyer defaults?";
const DEMO_ANSWER =
  "Clause 14.2 states the seller may retain the deposit (10% of purchase price) as a pre-estimated penalty. Clause 14.4 allows cancellation with 7 days' written notice.";
const DEMO_SOURCE = "Source: pages 28–29";

function useTypingEffect(text: string, speed = 28, startDelay = 800) {
  const [displayed, setDisplayed] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    let i = 0;
    setDisplayed("");
    setDone(false);
    const timeout = setTimeout(() => {
      const interval = setInterval(() => {
        i++;
        setDisplayed(text.slice(0, i));
        if (i >= text.length) {
          clearInterval(interval);
          setDone(true);
        }
      }, speed);
      return () => clearInterval(interval);
    }, startDelay);
    return () => clearTimeout(timeout);
  }, [text, speed, startDelay]);

  return { displayed, done };
}

/* ─── Document preview card ─── */
function DocumentCard() {
  return (
    <div style={s.docCard}>
      <div style={s.docHeader}>
        <div style={{ ...s.docIcon, background: "#e8eeff" }}>📄</div>
        <div>
          <p style={s.docName}>Sale_Agreement_v3.pdf</p>
          <p style={s.docMeta}>Legal · 47 pages · Uploaded just now</p>
        </div>
        <span style={s.docBadge}>Ready</span>
      </div>
      <div style={s.bars}>
        {[80, 60, 95, 45].map((w, i) => (
          <div key={i} style={{ ...s.bar, width: `${w}%`, animationDelay: `${i * 0.15}s` }} />
        ))}
      </div>
    </div>
  );
}

/* ─── Chat demo ─── */
function ChatDemo() {
  const [phase, setPhase] = useState<"idle" | "query" | "thinking" | "answer">("idle");
  const { displayed: answerText, done: answerDone } = useTypingEffect(
    DEMO_ANSWER,
    18,
    phase === "answer" ? 0 : 9999999
  );

  useEffect(() => {
    const t1 = setTimeout(() => setPhase("query"), 600);
    const t2 = setTimeout(() => setPhase("thinking"), 1800);
    const t3 = setTimeout(() => setPhase("answer"), 3200);
    return () => [t1, t2, t3].forEach(clearTimeout);
  }, []);

  return (
    <div style={s.chat}>
      {/* User query bubble */}
      <div
        style={{
          ...s.queryBubble,
          opacity: phase !== "idle" ? 1 : 0,
          transform: phase !== "idle" ? "translateY(0)" : "translateY(8px)",
          transition: "all 0.4s ease",
        }}
      >
        {DEMO_QUERY}
      </div>

      {/* Thinking dots */}
      {phase === "thinking" && (
        <div style={s.thinkingRow}>
          <div style={s.thinkingDots}>
            {[0, 1, 2].map((i) => (
              <span key={i} style={{ ...s.dot, animationDelay: `${i * 0.2}s` }} />
            ))}
          </div>
        </div>
      )}

      {/* Answer bubble */}
      {phase === "answer" && (
        <div
          style={{
            ...s.answerBubble,
            opacity: 1,
            transition: "opacity 0.3s ease",
          }}
        >
          <p style={{ marginBottom: answerDone ? 8 : 0 }}>{answerText}</p>
          {answerDone && (
            <p style={s.sourceTag}>
              <span style={s.sourceIcon}>↗</span> {DEMO_SOURCE}
            </p>
          )}
        </div>
      )}

      {/* POPIA badge */}
      {answerDone && (
        <div style={s.popiaBadge}>
          <span style={{ color: "var(--success)" }}>✓</span>
          POPIA compliant · Data stays in South Africa
        </div>
      )}
    </div>
  );
}

/* ─── Hero ─── */
export default function Hero() {
  return (
    <section style={s.section}>
      <div style={s.container}>
        {/* Left column */}
        <div style={s.left}>
          <div style={s.eyebrow}>
            <span style={s.eyebrowDot} />
            POPIA-compliant · Built in South Africa
          </div>

          <h1 style={s.heading}>
            Your documents,{" "}
            <em style={s.headingItalic}>intelligently</em>{" "}
            understood.
          </h1>

          <p style={s.subheading}>
            DocuRAG gives South African legal, medical, and financial
            professionals instant, cited answers from their own documents —
            no data leaving the country.
          </p>

          <div style={s.actions}>
            <button
              style={s.btnPrimary}
              onMouseEnter={(e) =>
                ((e.target as HTMLElement).style.background = "var(--accent)")
              }
              onMouseLeave={(e) =>
                ((e.target as HTMLElement).style.background = "var(--ink)")
              }
            >
              Start free trial
            </button>
            <button
              style={s.btnSecondary}
              onMouseEnter={(e) =>
                ((e.target as HTMLElement).style.borderColor = "rgba(0,0,0,0.3)")
              }
              onMouseLeave={(e) =>
                ((e.target as HTMLElement).style.borderColor = "var(--border-strong)")
              }
            >
              Watch a demo →
            </button>
          </div>

          <div style={s.socialProof}>
            <div style={s.avatars}>
              {["L", "M", "K"].map((initial, i) => (
                <div
                  key={i}
                  style={{
                    ...s.avatar,
                    background: ["#e8eeff", "#e1f5ee", "#fdf3e0"][i],
                    color: ["var(--accent)", "var(--success)", "var(--gold)"][i],
                    marginLeft: i > 0 ? -10 : 0,
                  }}
                >
                  {initial}
                </div>
              ))}
            </div>
            <p style={s.proofText}>
              Join 40+ professionals on the early access waitlist
            </p>
          </div>
        </div>

        {/* Right column — interactive demo */}
        <div style={s.right}>
          <div style={s.demoCard}>
            <DocumentCard />
            <ChatDemo />
          </div>
        </div>
      </div>

      {/* Decorative background shape */}
      <div style={s.bgShape} aria-hidden />
    </section>
  );
}

/* ─── Styles ─── */
const s: Record<string, React.CSSProperties> = {
  section: {
    position: "relative",
    overflow: "hidden",
    padding: "7rem 0 5rem",
  },

  container: {
    maxWidth: 1080,
    margin: "0 auto",
    padding: "0 2.5rem",
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "4rem",
    alignItems: "center",
    position: "relative",
    zIndex: 1,
  },

  left: {
    display: "flex",
    flexDirection: "column",
    gap: 0,
  },

  eyebrow: {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    background: "var(--accent-light)",
    color: "var(--accent)",
    fontSize: 11,
    fontWeight: 500,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    padding: "5px 13px",
    borderRadius: 20,
    marginBottom: "1.5rem",
    width: "fit-content",
  },

  eyebrowDot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "var(--accent)",
    flexShrink: 0,
    display: "inline-block",
  },

  heading: {
    fontFamily: "'DM Serif Display', serif",
    fontSize: "clamp(2.4rem, 5vw, 3.4rem)",
    lineHeight: 1.08,
    letterSpacing: "-0.04em",
    color: "var(--ink)",
    marginBottom: "1.25rem",
  },

  headingItalic: {
    fontStyle: "italic",
    color: "var(--accent)",
  },

  subheading: {
    fontSize: 17,
    color: "var(--ink-muted)",
    lineHeight: 1.7,
    fontWeight: 300,
    marginBottom: "2rem",
    maxWidth: 440,
  },

  actions: {
    display: "flex",
    gap: 12,
    alignItems: "center",
    marginBottom: "2rem",
    flexWrap: "wrap",
  },

  btnPrimary: {
    background: "var(--ink)",
    color: "#fff",
    padding: "13px 28px",
    borderRadius: 8,
    fontSize: 15,
    fontWeight: 500,
    border: "none",
    cursor: "pointer",
    transition: "background 0.2s",
    fontFamily: "'DM Sans', sans-serif",
  },

  btnSecondary: {
    background: "transparent",
    color: "var(--ink)",
    padding: "12px 24px",
    borderRadius: 8,
    fontSize: 15,
    fontWeight: 400,
    border: "0.5px solid var(--border-strong)",
    cursor: "pointer",
    transition: "border-color 0.2s",
    fontFamily: "'DM Sans', sans-serif",
  },

  socialProof: {
    display: "flex",
    alignItems: "center",
    gap: 10,
  },

  avatars: {
    display: "flex",
  },

  avatar: {
    width: 28,
    height: 28,
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 11,
    fontWeight: 500,
    border: "2px solid var(--surface)",
  },

  proofText: {
    fontSize: 13,
    color: "var(--ink-faint)",
    fontWeight: 300,
  },

  right: {
    display: "flex",
    justifyContent: "center",
  },

  demoCard: {
    background: "var(--surface-card)",
    borderRadius: 16,
    border: "0.5px solid var(--border)",
    padding: "1.5rem",
    width: "100%",
    maxWidth: 420,
    boxShadow: "0 2px 24px rgba(0,0,0,0.06)",
  },

  docCard: {
    background: "var(--surface)",
    borderRadius: 10,
    padding: "1rem 1.25rem",
    border: "0.5px solid var(--border)",
    marginBottom: "1rem",
  },

  docHeader: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: "0.75rem",
  },

  docIcon: {
    width: 34,
    height: 34,
    borderRadius: 7,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 17,
    flexShrink: 0,
  },

  docName: {
    fontSize: 13,
    fontWeight: 500,
    color: "var(--ink)",
    lineHeight: 1.3,
  },

  docMeta: {
    fontSize: 11,
    color: "var(--ink-faint)",
  },

  docBadge: {
    marginLeft: "auto",
    background: "var(--success-light)",
    color: "var(--success)",
    fontSize: 11,
    fontWeight: 500,
    padding: "3px 10px",
    borderRadius: 20,
    flexShrink: 0,
  },

  bars: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },

  bar: {
    height: 5,
    borderRadius: 3,
    background: "rgba(0,0,0,0.08)",
  },

  chat: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },

  queryBubble: {
    background: "var(--accent-light)",
    color: "var(--ink)",
    borderRadius: "10px 10px 10px 2px",
    padding: "10px 14px",
    fontSize: 13,
    lineHeight: 1.5,
    alignSelf: "flex-start",
    maxWidth: "90%",
  },

  thinkingRow: {
    display: "flex",
    justifyContent: "flex-end",
  },

  thinkingDots: {
    display: "flex",
    gap: 5,
    alignItems: "center",
    padding: "10px 14px",
    background: "#fff",
    borderRadius: "10px 10px 2px 10px",
    border: "0.5px solid var(--border)",
  },

  dot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "var(--ink-faint)",
    display: "inline-block",
    animation: "pulse 1.2s ease-in-out infinite",
  },

  answerBubble: {
    background: "#fff",
    border: "0.5px solid var(--border)",
    borderRadius: "10px 10px 2px 10px",
    padding: "10px 14px",
    fontSize: 13,
    color: "var(--ink-muted)",
    lineHeight: 1.6,
    alignSelf: "flex-end",
    maxWidth: "95%",
  },

  sourceTag: {
    fontSize: 11,
    fontWeight: 500,
    color: "var(--accent)",
    marginTop: 6,
    display: "flex",
    alignItems: "center",
    gap: 4,
  },

  sourceIcon: {
    fontSize: 10,
  },

  popiaBadge: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    background: "var(--success-light)",
    color: "var(--success)",
    fontSize: 11,
    fontWeight: 500,
    padding: "5px 12px",
    borderRadius: 20,
    alignSelf: "flex-start",
  },

  bgShape: {
    position: "absolute",
    top: -200,
    right: -300,
    width: 700,
    height: 700,
    borderRadius: "50%",
    background:
      "radial-gradient(circle, rgba(26,79,214,0.04) 0%, transparent 70%)",
    pointerEvents: "none",
    zIndex: 0,
  },
};
