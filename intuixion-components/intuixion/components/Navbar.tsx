"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { SignedIn, SignedOut, UserButton } from "@clerk/nextjs";

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav style={styles.nav(scrolled)}>
      <div style={styles.inner}>
        {/* Logo */}
        <Link href="/" style={styles.logo}>
          intuix<span style={styles.logoAccent}>ion</span>.ai
        </Link>

        {/* Marketing nav links — hidden when on /ask */}
        <ul style={styles.links}>
          {["Product", "Sectors", "Pricing", "About"].map((label) => (
            <li key={label}>
              <Link href={`#${label.toLowerCase()}`} style={styles.link}>
                {label}
              </Link>
            </li>
          ))}
        </ul>

        {/* Actions */}
        <div style={styles.actions}>
          <SignedOut>
            <Link href="/sign-in" style={styles.signIn}>
              Sign in
            </Link>
            <Link href="#early-access" style={styles.cta}>
              Get early access
            </Link>
          </SignedOut>

          <SignedIn>
            <Link href="/ask" style={styles.cta}>
              Ask →
            </Link>
            <UserButton afterSignOutUrl="/" />
          </SignedIn>
        </div>
      </div>
    </nav>
  );
}

const styles = {
  nav: (scrolled: boolean): React.CSSProperties => ({
    position: "sticky",
    top: 0,
    zIndex: 100,
    background: scrolled
      ? "rgba(247, 245, 240, 0.95)"
      : "rgba(247, 245, 240, 0.80)",
    backdropFilter: "blur(14px)",
    WebkitBackdropFilter: "blur(14px)",
    borderBottom: scrolled
      ? "0.5px solid rgba(0,0,0,0.10)"
      : "0.5px solid transparent",
    transition: "all 0.25s ease",
  }),

  inner: {
    maxWidth: 1080,
    margin: "0 auto",
    padding: "0 2.5rem",
    height: 62,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "2rem",
  } as React.CSSProperties,

  logo: {
    fontFamily: "'DM Serif Display', serif",
    fontSize: 20,
    color: "var(--ink)",
    letterSpacing: "-0.3px",
    flexShrink: 0,
  } as React.CSSProperties,

  logoAccent: {
    color: "var(--accent)",
  } as React.CSSProperties,

  links: {
    display: "flex",
    gap: "2rem",
    listStyle: "none",
    flex: 1,
    justifyContent: "center",
  } as React.CSSProperties,

  link: {
    fontSize: 14,
    color: "var(--ink-muted)",
    fontWeight: 400,
    transition: "color 0.15s",
  } as React.CSSProperties,

  actions: {
    display: "flex",
    alignItems: "center",
    gap: "1.25rem",
    flexShrink: 0,
  } as React.CSSProperties,

  signIn: {
    fontSize: 14,
    color: "var(--ink-muted)",
    fontWeight: 400,
    transition: "color 0.15s",
  } as React.CSSProperties,

  cta: {
    background: "var(--ink)",
    color: "#fff",
    padding: "8px 20px",
    borderRadius: "var(--radius-sm)",
    fontSize: 13,
    fontWeight: 500,
    flexShrink: 0,
    transition: "background 0.2s",
  } as React.CSSProperties,
};
