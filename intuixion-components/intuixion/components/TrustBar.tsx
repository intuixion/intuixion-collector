export default function TrustBar() {
  const logos = ["CERN", "IBM", "AWS Summit Africa", "Wits University", "York University"];

  return (
    <div style={s.wrapper}>
      <p style={s.label}>Research & industry experience from</p>
      <div style={s.logos}>
        {logos.map((name) => (
          <span key={name} style={s.logo}>
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  wrapper: {
    borderTop: "0.5px solid var(--border)",
    borderBottom: "0.5px solid var(--border)",
    background: "var(--surface-card)",
    padding: "1.75rem 2.5rem",
    textAlign: "center",
  },
  label: {
    fontSize: 11,
    letterSpacing: "0.12em",
    textTransform: "uppercase",
    color: "var(--ink-faint)",
    marginBottom: "1.25rem",
  },
  logos: {
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    gap: "3rem",
    flexWrap: "wrap",
  },
  logo: {
    fontSize: 13,
    fontWeight: 500,
    color: "var(--ink-muted)",
    opacity: 0.55,
    letterSpacing: "0.04em",
  },
};
