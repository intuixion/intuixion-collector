import Navbar from "@/components/Navbar";
import QueryInterface from "@/components/QueryInterface";

export const metadata = {
  title: "Ask — intuixion.ai",
  description: "Ask questions about South African regulation and get cited answers.",
};

export default function AskPage() {
  return (
    <>
      <Navbar />
      <main>
        <div style={header}>
          <h1 style={h1}>Ask a regulatory question</h1>
          <p style={sub}>
            Cited answers from 146 SA regulatory documents across POPIA, NCA, FICA,
            BCEA, MSA, Companies Act, and more.
          </p>
        </div>
        <QueryInterface />
      </main>
    </>
  );
}

const header: React.CSSProperties = {
  maxWidth: 1080,
  margin: "0 auto",
  padding: "2.5rem 2.5rem 1.5rem",
};

const h1: React.CSSProperties = {
  fontFamily: "var(--font-display)",
  fontSize: "clamp(1.6rem, 3vw, 2.2rem)",
  letterSpacing: "-0.03em",
  color: "var(--ink)",
  marginBottom: "0.5rem",
};

const sub: React.CSSProperties = {
  fontSize: 15,
  color: "var(--ink-muted)",
  fontWeight: 300,
  lineHeight: 1.6,
};
