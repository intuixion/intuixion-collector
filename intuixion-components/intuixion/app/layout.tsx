import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "../styles/globals.css";

export const metadata: Metadata = {
  title: "intuixion.ai — Cited Regulatory Intelligence for South Africa",
  description:
    "Get instant, cited answers from SA regulatory documents. POPIA-compliant. Built in South Africa.",
  openGraph: {
    title: "intuixion.ai",
    description: "Cited regulatory intelligence for South African professionals.",
    url: "https://intuixion.ai",
    siteName: "intuixion.ai",
    locale: "en_ZA",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body>{children}</body>
      </html>
    </ClerkProvider>
  );
}
