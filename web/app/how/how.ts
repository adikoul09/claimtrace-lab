// The /how page's steps and whether each one is live, decided by code from what has actually happened here:
// a step is "live" once the database shows it worked at least once, otherwise "next".

export type Evidence = {
  projects: number; // projects created
  readerDone: number; // finished read_paper / extract_claims tasks
  designerDone: number; // finished design_experiment tasks
  implementerDone: number; // finished write_code tasks
  runsDone: number; // finished run tasks
  graded: number; // experiments with the Analyst's verdicts
  rewards: number; // reward events
  evolved: number; // agent_refined + agent_spawned + agent_retired events
  lessons: number; // saved lessons
  emails: number; // email_received events
};
export const NO_EVIDENCE: Evidence = {
  projects: 0,
  readerDone: 0,
  designerDone: 0,
  implementerDone: 0,
  runsDone: 0,
  graded: 0,
  rewards: 0,
  evolved: 0,
  lessons: 0,
  emails: 0,
};

export type HowStep = { id: string; title: string; text: string; live: boolean; proof: string | null };

const times = (n: number) => (n === 1 ? "done once here" : `done ${n} times here`);

function step(id: string, title: string, text: string, count: number | null): HowStep {
  // count null: no evidence source exists yet, so the step is "next" whatever the data says.
  const live = count !== null && count > 0;
  return { id, title, text, live, proof: live ? times(count) : null };
}

export function howSteps(e: Evidence): HowStep[] {
  return [
    step("paper", "Paper in", "You give the lab a paper from arXiv.", e.projects),
    step(
      "reader",
      "Reader",
      "An AI agent reads the paper and lists each result it claims, with the exact sentence and page.",
      e.readerDone,
    ),
    step(
      "designer",
      "Designer",
      "An AI agent plans a small version of the experiment that fits on a laptop, and says in advance how close counts as a match.",
      e.designerDone,
    ),
    step("implementer", "Implementer", "An AI agent writes the code for that experiment.", e.implementerDone),
    step(
      "worker",
      "Laptop worker runs it",
      "A laptop runs the code. Every number it prints is saved together with its line in the log.",
      e.runsDone,
    ),
    step(
      "grading",
      "Code grades every number",
      "Plain code, not AI, compares each of our numbers with the paper's: reproduced, partly reproduced, or not.",
      e.graded,
    ),
    step(
      "report",
      "Report with proof",
      "Each claim sits next to our number, and every number links to the log line that printed it.",
      e.graded,
    ),
    step("scores", "Scoring", "After each step, the lab scores the agent that did it.", e.rewards),
    step(
      "evolve",
      "Improve, add, retire",
      "Agents that keep failing are rewritten or retired; a new specialist is added when a job needs one.",
      e.evolved,
    ),
    step("lessons", "Lessons", "What worked or went wrong is saved as a lesson for the next run.", e.lessons),
    step("email", "Journal email", "A reviewer's email arrives in the project's Inbox.", e.emails),
    step("engine", "Send to engine", "The lab acts on the email's requests by itself.", null),
  ];
}
