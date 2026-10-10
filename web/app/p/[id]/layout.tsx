// Static title and description for every project tab; the header refines the title per tab (?tab=) on the client.
// A layout so the project page itself (A2) stays untouched; it renders its children unchanged.
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Project",
  description: "One paper's reproduction: live events, the agent team, experiments, the report and journal emails.",
};

export default function ProjectLayout({ children }: LayoutProps<"/p/[id]">) {
  return children;
}
