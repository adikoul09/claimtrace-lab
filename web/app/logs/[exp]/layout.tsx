// Static title and description for the run log viewer; the page itself (A2) stays untouched.
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Run log",
  description: "The full log of one experiment run, with every METRIC line the stored numbers come from.",
};

export default function LogLayout({ children }: LayoutProps<"/logs/[exp]">) {
  return children;
}
