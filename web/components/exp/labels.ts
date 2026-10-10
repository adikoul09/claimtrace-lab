// Plain words for codes the runs print: METRIC names and CONFIG keys (statuses and capabilities use A1's
// components/live/labels.ts). The raw code stays available in a title tooltip where it is shown.

const KEYS: Record<string, string> = {
  lr: "learning rate",
  learning_rate: "learning rate",
  T: "temperature",
  batch: "batch size",
  bs: "batch size",
  wd: "weight decay",
};

const words = (s: string) => s.replace(/[_.]+/g, " ").trim();
const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** "final_teacher_wall_s" → "Teacher wall time (s)"; "final_student_hard_test_errors" → "Student hard test errors". */
export function metricLabel(name: string): string {
  const base = name.replace(/^final_/, "").replace(/_wall_s$/, "_wall time (s)");
  return cap(words(base));
}

/** "lr" → "learning rate"; "teacher.lr" → "teacher learning rate"; "student.grad_clip" → "student grad clip". */
export function configKeyLabel(key: string): string {
  return key
    .split(".")
    .map((part) => KEYS[part] ?? words(part))
    .join(" ");
}
