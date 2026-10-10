import type { Metadata, Viewport } from "next";
import { LiveHeader } from "@/components/live-header";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ClaimTrace Lab", template: "ClaimTrace Lab · %s" },
  description: "An evolving team of AI agents reproduces a paper's key result and explains why results differ.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <LiveHeader />
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-4">{children}</main>
      </body>
    </html>
  );
}
