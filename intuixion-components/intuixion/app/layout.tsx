import type { Metadata } from "next";
import "../styles/globals.css";

export const metadata: Metadata = {
  title: "intuixion.ai — Document Intelligence for South African Professionals",
  description:
    "DocuRAG gives legal, medical, and financial professionals instant, cited answers from their own documents. POPIA-compliant. Built in South Africa.",
  openGraph: {
    title: "intuixion.ai",
    description: "Intelligent document analysis. POPIA-compliant.",
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
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
