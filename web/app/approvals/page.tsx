import type { Metadata } from "next";
import { ApprovalsView } from "./approvals-view";

export const metadata: Metadata = {
  title: "Approvals",
  description: "Approve, reject or redirect the tasks that wait for a researcher, and rate finished work.",
};

export default function ApprovalsPage() {
  return (
    <>
      <h1 className="mb-4 text-lg font-semibold">Approvals</h1>
      <ApprovalsView />
    </>
  );
}
