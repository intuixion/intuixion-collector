"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useAuth, UserButton } from "@clerk/nextjs";
import Link from "next/link";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "https://intuixion-api.fly.dev";

const SECTORS = [
  { label: "All sectors", value: null },
  { label: "Cross-sector", value: "cross" },
  { label: "Healthcare", value: "healthcare" },
  { label: "Financial", value: "financial" },
  { label: "Labour & Retail", value: "labour" },
];

interface SourceItem {
  slug: string;
  name: string;
  sector: string;
  chunks: number;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
  error?: boolean;
}

export default function DemoPage() {
  const { getToken } = useAuth();
  const [sector, setSector] = useState<string | null>(null);
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const totalChunks = sources.reduce((s, x) => s + x.chunks, 0);

  useEffect(() => {
    (async () => {
      try {
        const token = await getToken();
        const res = await fetch(`${API_URL}/v1/sources`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (res.ok) setSources(await res.json());
      } catch {
        // non-fatal — sidebar stats stay at 0
      }
    })();
  }, [getToken]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    const q = input.trim();
    if (!q || busy) return;

    setInput("");
    setBusy(true);

    const userMsg: Message = { id: crypto.randomUUID(), role: "user", text: q };
    const botId = crypto.randomUUID();
    setMessages((m) => [...m, userMsg, { id: botId, role: "assistant", text: "", streaming: true }]);

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const token = await getToken();
      if (!token) throw new Error("Please sign in to use the demo.");

      const res = await fetch(`${API_URL}/v1/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question: q, top_k: 12, sector: sector ?? undefined }),
        signal: ctrl.signal,
      });

      if (res.status === 401) throw new Error("Session expired — please refresh and sign in again.");
      if (res.status === 429) throw new Error("Rate limit reached. Please wait a moment before asking again.");
      if (!res.ok) throw new Error(`Server error (${res.status}). Please try again.`);

      const reader = res.body!.getReader();
      const dec = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop()!;

        for (const part of parts) {
          if (!part.startsWith("data: ")) continue;
          let evt: Record<string, unknown>;
          try { evt = JSON.parse(part.slice(6)); } catch { continue; }

          if (evt.type === "token") {
            setMessages((m) =>
              m.map((x) => x.id === botId ? { ...x, text: x.text + (evt.content as string) } : x)
            );
          } else if (evt.type === "done") {
            setMessages((m) =>
              m.map((x) => x.id === botId ? { ...x, streaming: false } : x)
            );
          } else if (evt.type === "error") {
            setMessages((m) =>
              m.map((x) => x.id === botId
                ? { ...x, text: (evt.detail as string) ?? "An error occurred.", streaming: false, error: true }
                : x)
            );
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name === "AbortError") return;
      const msg = err instanceof Error ? err.message : "Request failed.";
      setMessages((m) =>
        m.map((x) => x.id === botId ? { ...x, text: msg, streaming: false, error: true } : x)
      );
    } finally {
      setBusy(false);
    }
  }, [input, busy, sector, getToken]);

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
  };

  return (
    <div style={css.root}>
      {/* ── Sidebar ── */}
      <aside style={css.sidebar}>
        <div style={css.sidebarLogo}>
          <div style={css.logoMark}>i</div>
          <span style={css.logoText}>intuixion<span style={css.logoDot}>.ai</span></span>
        </div>

        {/* Knowledge base stats */}
        <div style={css.sidebarSection}>
          <p style={css.sidebarLabel}>Knowledge Base</p>
          <div style={css.statsRow}>
            <div style={css.statBox}>
              <span style={css.statNum}>{totalChunks > 0 ? totalChunks.toLocaleString() : "—"}</span>
              <span style={css.statSub}>passages</span>
            </div>
            <div style={css.statBox}>
              <span style={css.statNum}>{sources.length > 0 ? sources.length : "—"}</span>
              <span style={css.statSub}>sources</span>
            </div>
          </div>
        </div>

        {/* Sector filter */}
        <div style={css.sidebarSection}>
          <p style={css.sidebarLabel}>Filter by Sector</p>
          <ul style={css.filterList}>
            {SECTORS.map((s) => (
              <li
                key={s.label}
                style={{ ...css.filterItem, ...(sector === s.value ? css.filterActive : {}) }}
                onClick={() => setSector(s.value)}
              >
                {s.label}
              </li>
            ))}
          </ul>
        </div>

        {/* Document upload placeholder */}
        <div style={css.sidebarSection}>
          <p style={css.sidebarLabel}>Your Documents</p>
          <label style={css.uploadZone}>
            <svg style={css.uploadIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
            <span style={css.uploadText}>
              Drop a PDF here, or <span style={css.uploadLink}>browse</span>
            </span>
            <span style={css.uploadSub}>Ask questions about any SA regulatory document</span>
            <input type="file" accept=".pdf" style={{ display: "none" }} />
          </label>
        </div>
      </aside>

      {/* ── Main area ── */}
      <div style={css.main}>
        {/* Top bar */}
        <header style={css.topbar}>
          <div style={css.trustBadge}>
            <span style={css.flagZA}>ZA</span>
            Hosted in South Africa · POPIA-compliant
          </div>
          <div style={css.topbarRight}>
            <span style={css.trialBadge}>Trial</span>
            <Link href="#upgrade" style={css.upgradeBtn}>⚡ Upgrade</Link>
            <UserButton afterSignOutUrl="/" />
          </div>
        </header>

        {/* Chat */}
        <div style={css.chat}>
          {messages.length === 0 && (
            <div style={css.empty}>
              <p style={css.emptyHint}>
                Ask a question about South African regulation — answers cite exact statutory provisions.
              </p>
              <div style={css.suggestions}>
                {[
                  "What are the lawful grounds for processing personal information under POPIA?",
                  "What are the overtime rules under the BCEA?",
                  "When must an accountable institution conduct customer due diligence under FICA?",
                ].map((s) => (
                  <button key={s} style={css.suggBtn} onClick={() => { setInput(s); inputRef.current?.focus(); }}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div key={m.id} style={m.role === "user" ? css.userRow : css.botRow}>
              {m.role === "assistant" && <div style={css.botAvatar}>i</div>}
              <div
                style={{
                  ...css.bubble,
                  ...(m.role === "user" ? css.userBubble : css.botBubble),
                  ...(m.error ? css.errorBubble : {}),
                }}
              >
                {m.text || (m.streaming ? <span style={css.cursor}>▌</span> : null)}
                {m.streaming && m.text && <span style={css.cursor}>▌</span>}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div style={css.inputArea}>
          <div style={css.inputBox}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKey}
              placeholder="Ask a regulatory question… (⌘↵ to submit)"
              style={css.textarea}
              rows={2}
              disabled={busy}
            />
            <button
              onClick={send}
              disabled={busy || !input.trim()}
              style={{
                ...css.sendBtn,
                opacity: busy || !input.trim() ? 0.4 : 1,
                cursor: busy || !input.trim() ? "not-allowed" : "pointer",
              }}
            >
              {busy ? "…" : "↑"}
            </button>
          </div>
          <p style={css.inputHint}>⌘↵ to submit · answers cite SA statutory provisions</p>
        </div>
      </div>
    </div>
  );
}

/* ── Styles ── */
const css: Record<string, React.CSSProperties> = {
  root: {
    display: "flex",
    height: "100vh",
    overflow: "hidden",
    fontFamily: "var(--font-body)",
    background: "var(--surface)",
  },

  /* Sidebar */
  sidebar: {
    width: 220,
    flexShrink: 0,
    background: "#1a1f2e",
    display: "flex",
    flexDirection: "column",
    padding: "1.25rem 0",
    overflowY: "auto",
  },
  sidebarLogo: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    padding: "0 1.25rem 1.25rem",
    borderBottom: "1px solid rgba(255,255,255,0.08)",
    marginBottom: "0.5rem",
  },
  logoMark: {
    width: 28,
    height: 28,
    borderRadius: 7,
    background: "linear-gradient(135deg, #6366f1, #3b82f6)",
    color: "#fff",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontWeight: 700,
    fontSize: 16,
    fontFamily: "var(--font-display)",
  },
  logoText: {
    color: "#fff",
    fontFamily: "var(--font-display)",
    fontWeight: 600,
    fontSize: 15,
    letterSpacing: "-0.02em",
  },
  logoDot: { color: "#6366f1" },
  sidebarSection: {
    padding: "1rem 1.25rem",
    borderBottom: "1px solid rgba(255,255,255,0.06)",
  },
  sidebarLabel: {
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: "0.1em",
    textTransform: "uppercase",
    color: "rgba(255,255,255,0.4)",
    marginBottom: "0.75rem",
  },
  statsRow: {
    display: "flex",
    gap: "0.75rem",
  },
  statBox: {
    flex: 1,
    background: "rgba(255,255,255,0.06)",
    borderRadius: 8,
    padding: "0.625rem 0.75rem",
    display: "flex",
    flexDirection: "column",
  },
  statNum: {
    fontSize: 20,
    fontWeight: 700,
    color: "#fff",
    lineHeight: 1,
    fontFamily: "var(--font-display)",
  },
  statSub: {
    fontSize: 10,
    color: "rgba(255,255,255,0.4)",
    marginTop: 2,
  },
  filterList: {
    listStyle: "none",
    padding: 0,
    margin: 0,
    display: "flex",
    flexDirection: "column",
    gap: 2,
  },
  filterItem: {
    padding: "0.45rem 0.75rem",
    borderRadius: 6,
    fontSize: 13,
    color: "rgba(255,255,255,0.55)",
    cursor: "pointer",
    transition: "background 0.15s, color 0.15s",
  },
  filterActive: {
    background: "rgba(255,255,255,0.1)",
    color: "#fff",
    fontWeight: 500,
  },
  uploadZone: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: "0.4rem",
    border: "1.5px dashed rgba(255,255,255,0.15)",
    borderRadius: 10,
    padding: "1.25rem 0.75rem",
    cursor: "pointer",
    textAlign: "center",
  },
  uploadIcon: {
    width: 24,
    height: 24,
    color: "rgba(255,255,255,0.3)",
    marginBottom: 2,
  },
  uploadText: {
    fontSize: 12,
    color: "rgba(255,255,255,0.5)",
  },
  uploadLink: {
    color: "#6366f1",
    textDecoration: "underline",
  },
  uploadSub: {
    fontSize: 10,
    color: "rgba(255,255,255,0.3)",
    lineHeight: 1.4,
  },

  /* Main */
  main: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  topbar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0.75rem 1.5rem",
    borderBottom: "0.5px solid var(--border)",
    background: "var(--surface-card)",
    flexShrink: 0,
  },
  trustBadge: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    fontSize: 12,
    color: "#16a34a",
    background: "#f0fdf4",
    border: "0.5px solid #bbf7d0",
    borderRadius: 20,
    padding: "0.35rem 0.9rem",
    fontWeight: 500,
  },
  flagZA: {
    background: "#16a34a",
    color: "#fff",
    borderRadius: 4,
    padding: "1px 5px",
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: "0.05em",
  },
  topbarRight: {
    display: "flex",
    alignItems: "center",
    gap: "0.75rem",
  },
  trialBadge: {
    fontSize: 12,
    color: "var(--ink-faint)",
    background: "rgba(0,0,0,0.05)",
    borderRadius: 20,
    padding: "0.3rem 0.75rem",
  },
  upgradeBtn: {
    fontSize: 12,
    fontWeight: 600,
    color: "#fff",
    background: "#f59e0b",
    borderRadius: 20,
    padding: "0.35rem 0.9rem",
    textDecoration: "none",
  },

  /* Chat */
  chat: {
    flex: 1,
    overflowY: "auto",
    padding: "1.5rem 2rem",
    display: "flex",
    flexDirection: "column",
    gap: "1.25rem",
  },
  empty: {
    margin: "auto",
    textAlign: "center",
    maxWidth: 540,
  },
  emptyHint: {
    fontSize: 15,
    color: "var(--ink-muted)",
    lineHeight: 1.6,
    marginBottom: "1.5rem",
  },
  suggestions: {
    display: "flex",
    flexDirection: "column",
    gap: "0.5rem",
  },
  suggBtn: {
    textAlign: "left",
    padding: "0.75rem 1rem",
    background: "var(--surface-card)",
    border: "0.5px solid var(--border)",
    borderRadius: "var(--radius-md)",
    fontSize: 13,
    color: "var(--ink-muted)",
    cursor: "pointer",
    lineHeight: 1.5,
    fontFamily: "var(--font-body)",
  },

  userRow: {
    display: "flex",
    justifyContent: "flex-end",
  },
  botRow: {
    display: "flex",
    gap: "0.75rem",
    alignItems: "flex-start",
  },
  botAvatar: {
    width: 32,
    height: 32,
    flexShrink: 0,
    borderRadius: 8,
    background: "linear-gradient(135deg, #6366f1, #3b82f6)",
    color: "#fff",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontWeight: 700,
    fontSize: 16,
    fontFamily: "var(--font-display)",
  },
  bubble: {
    maxWidth: "75%",
    padding: "0.75rem 1rem",
    borderRadius: "var(--radius-md)",
    fontSize: 14,
    lineHeight: 1.7,
    whiteSpace: "pre-wrap",
  },
  userBubble: {
    background: "var(--ink)",
    color: "#fff",
    borderBottomRightRadius: 4,
  },
  botBubble: {
    background: "var(--surface-card)",
    border: "0.5px solid var(--border)",
    color: "var(--ink-muted)",
    borderTopLeftRadius: 4,
  },
  errorBubble: {
    background: "#fef2f2",
    border: "0.5px solid rgba(220,38,38,0.25)",
    color: "#dc2626",
  },
  cursor: {
    display: "inline-block",
    animation: "pulse 1s ease-in-out infinite",
    color: "var(--accent)",
  },

  /* Input */
  inputArea: {
    padding: "1rem 2rem 1.25rem",
    borderTop: "0.5px solid var(--border)",
    background: "var(--surface-card)",
    flexShrink: 0,
  },
  inputBox: {
    display: "flex",
    gap: "0.5rem",
    alignItems: "flex-end",
    background: "var(--surface)",
    border: "0.5px solid var(--border-strong)",
    borderRadius: "var(--radius-lg)",
    padding: "0.75rem 0.75rem 0.75rem 1.25rem",
    boxShadow: "0 2px 8px rgba(0,0,0,0.04)",
  },
  textarea: {
    flex: 1,
    border: "none",
    outline: "none",
    resize: "none",
    background: "transparent",
    fontSize: 14,
    fontFamily: "var(--font-body)",
    color: "var(--ink)",
    lineHeight: 1.6,
  },
  sendBtn: {
    width: 36,
    height: 36,
    flexShrink: 0,
    borderRadius: "var(--radius-sm)",
    background: "var(--ink)",
    color: "#fff",
    border: "none",
    fontSize: 18,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontFamily: "var(--font-body)",
  },
  inputHint: {
    fontSize: 11,
    color: "var(--ink-faint)",
    marginTop: "0.5rem",
    textAlign: "center",
  },
};
