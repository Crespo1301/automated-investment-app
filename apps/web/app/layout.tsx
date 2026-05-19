import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Autonomous Trading Control Room",
  description: "Dashboard shell for an AI-assisted autonomous investment platform.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      {/* suppressHydrationWarning: browser extensions (Grammarly, etc.) inject
          attributes like data-gr-ext-installed onto <body> before React
          hydrates. This silences that benign mismatch only — element-level,
          not subtree-wide, so genuine markup drift is still reported. */}
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}

