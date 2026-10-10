"""Research memory (SPEC §6).

  read    select() is the lesson policy (MEM-1), all code:
            - a lesson without evidence_event_id is never used                         (skipped: no_evidence)
            - setting_mattered lessons apply only to the same paper (arXiv id; Round 0 = round0:matchdg);
              failure_fix, budget and agent_choice lessons carry across projects       (skipped: other_paper)
            - duplicates by kind + tag set keep the most applied one                   (skipped: duplicate)
            - rank by tag overlap (domain tags, capability, error signature), then times_applied
            - at most PER_PLAN (5) in the planner's prompt, PER_TASK (3) in a task's goal (skipped: over_limit)
          Each used lesson gets a lesson_applied event (times_applied += 1); at plan time each tag-matched lesson
          that was left out gets a lesson_skipped event with its reason.
  write   after a project finishes, or a failed step later succeeds (failure then recovery), the Reporter proposes
          at most MAX_LESSONS lessons {text, tags, evidence_event_id, kind}; code keeps one only if its evidence is an
          event of that project and its kind is known.
  seed    ROUND0_LESSONS: the MatchDG audit's findings F1-F8 (baseline/el01-auditor, report.md and DECISIONS.md),
          labelled "Imported from Round 0 audit". The Round 0 audit numbers only F1-F8; there is no F9.
  effect  effect(): run 2 vs run 1 of the same paper on retries before the first successful run, seconds to the
          first result and LLM tokens (R14), all from rows.

  python -m lab.controller.memory import-round0
  python -m lab.controller.memory effect <run1 project id> <run2 project id>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Optional

KINDS = ("failure_fix", "setting_mattered", "budget", "agent_choice")
MAX_LESSONS = 3
PER_TASK = 3          # lessons added to one task's goal
PER_PLAN = 5          # lessons added to the planner's prompt
REPORT = "baseline/el01-auditor/inputs/spike-matchdg/report.md"
DECISIONS = "baseline/el01-auditor/DECISIONS.md"
LABEL = "Imported from Round 0 audit"

ROUND0_LESSONS = [
    {"finding": "F1", "kind": "setting_mattered",
     "tags": ["round0", "matchdg", "data", "missing_domain", "design_experiment", "write_code", "debug"],
     "evidence": f"{REPORT} §B3 (settings diff, F1) and §B1 (run as shipped: Not runnable)",
     "text": "Check that the code generates every domain or setting the paper evaluates: in MatchDG the slab target "
             "domain p = 1.0 was never generated (data_gen_syn.py:42), so the shipped code could not run the paper's "
             "experiment; filling it is a hypothesis branch, not a repair."},
    {"finding": "F2", "kind": "setting_mattered",
     "tags": ["round0", "matchdg", "model_selection", "early_stopping", "design_experiment", "write_code", "compare",
              "explain_diff"],
     "evidence": f"{REPORT} §B3 (F2) and §B5 (branches h1, h1b)",
     "text": "Check the model-selection rule (validation loss vs validation accuracy): in MatchDG the paper says "
             "early stopping on validation loss, the code picks the best validation accuracy; reading it as "
             "cross-entropy moved PerfMatch by -25.8 points and ERM by +4.8."},
    {"finding": "F3", "kind": "setting_mattered",
     "tags": ["round0", "matchdg", "optimizer", "momentum", "budget", "design_experiment", "write_code",
              "explain_diff"],
     "evidence": f"{REPORT} §B3 (F3) and §B5 (branch h2)",
     "text": "Check the optimizer's unstated settings (momentum, Nesterov): MatchDG's code used SGD with momentum 0.9 "
             "and Nesterov where the paper says SGD; with plain SGD for the paper's 100 epochs the oracle lost 28.7 "
             "points, and 1000 epochs recovered it: the momentum acted like a tenfold training budget."},
    {"finding": "F4", "kind": "setting_mattered",
     "tags": ["round0", "matchdg", "schedule", "loss_weight", "design_experiment", "write_code"],
     "evidence": f"{REPORT} §B3 (F4) and §B5 (point 4)",
     "text": "Look for schedules the paper does not state, such as a loss weight ramped up from 0: MatchDG ramps its "
             "matching weight linearly (erm_match.py:109); alone it had no detectable effect, but it mattered "
             "through the model-selection rule."},
    {"finding": "F5", "kind": "setting_mattered",
     "tags": ["round0", "matchdg", "learning_rate", "lr", "design_experiment", "write_code", "explain_diff"],
     "evidence": f"{REPORT} §B3 (F5) and §B5 (branch h6)",
     "text": "Compare each method's learning rate in the code with the paper: DANN and CDANN used 0.01 in MatchDG's "
             "code against 0.1 in the paper; at the paper's rate both stayed at chance, so their gap stayed "
             "unexplained by the tested differences."},
    {"finding": "F6", "kind": "setting_mattered",
     "tags": ["round0", "matchdg", "hyperparameter_tuning", "model_selection", "data_leak", "design_experiment",
              "compare"],
     "evidence": f"{REPORT} §B3 (F6) and §B5 (branch h5)",
     "text": "Check what data hyperparameter tuning reads: MatchDG's tuning script ranked settings by a log line "
             "holding target-domain test accuracy, not source validation; re-tuning on source validation picked the "
             "published lambda = 1.0, so here it did not change the oracle result."},
    {"finding": "F7", "kind": "setting_mattered",
     "tags": ["round0", "matchdg", "augmentation", "checkpoint", "model_selection", "data", "design_experiment",
              "write_code"],
     "evidence": f"{REPORT} §A3 (F7, branch h7)",
     "text": "Trace data augmentation into checkpoint selection, not just training: MatchDG's augmented copy (flip "
             "after rotation) was read only by its contrastive phase's checkpoint choice; tested, the six-domain "
             "effect was -0.04 points (95% CI -0.41 to 0.34) and no verdict changed."},
    {"finding": "F8", "kind": "setting_mattered",
     "tags": ["round0", "matchdg", "margin", "standard_error", "seeds", "compare", "explain_diff"],
     "evidence": f"{DECISIONS} (2026-10-04, F8, team-verified)",
     "text": "Check whether a reported spread is a standard deviation or a standard error before using it as a "
             "margin: robustdg's test.py:399 printed std/sqrt(n) while Table 1's caption says standard deviation."},
]
for _l in ROUND0_LESSONS:
    _l["text"] = f"{LABEL} (MatchDG, {_l['finding']}): {_l['text']}"
    _l["tags"].append(f"round0-{_l['finding'].lower()}")


# ---- read ---------------------------------------------------------------------------------------------------------

def match(lessons: list[dict], tags: list[str], limit: int) -> list[dict]:
    want = set(tags)
    scored = [(len(want & set(l.get("tags") or [])), l) for l in lessons]
    scored = [(n, l) for n, l in scored if n]
    scored.sort(key=lambda x: (-x[0], x[1].get("created_at") or ""))
    return [l for _, l in scored[:limit]]


def task_tags(project: dict, capability: str, error_signature: Optional[str] = None) -> list[str]:
    tags = [str(t).lower() for t in project.get("tags") or []] + [capability]
    if error_signature:
        tags += [error_signature, error_signature.split(":")[0]]
    return list(dict.fromkeys(tags))


def lessons_block(lessons: list[dict]) -> str:
    if not lessons:
        return ""
    return "Lessons from earlier work (apply them where they fit):\n" + "\n".join(
        f"- [{l['id']}] {l['text']}" for l in lessons)


SKIP_REASONS = {"no_evidence": "it has no evidence event",
                "other_paper": "setting_mattered lessons apply only to the paper they came from",
                "duplicate": "a lesson of the same kind and tags was applied more often",
                "over_limit": "the prompt already holds the most relevant ones"}


def paper_key(lesson: dict, arxiv_by_project: dict[str, Optional[str]]) -> Optional[str]:
    if "round0" in (lesson.get("tags") or []):
        return "round0:matchdg"
    return arxiv_by_project.get(lesson.get("project_id") or "")


def select(lessons: list[dict], tags: list[str], project_paper: Optional[str], limit: int):
    """(chosen, skipped [(lesson, reason code, detail)]); lessons carry `paper` (paper_key). Only lessons sharing a
    tag are considered at all."""
    want = set(tags)
    matched = [l for l in lessons if want & set(l.get("tags") or [])]
    skipped, ok = [], []
    for l in matched:
        if not l.get("evidence_event_id"):
            skipped.append((l, "no_evidence", SKIP_REASONS["no_evidence"]))
        elif l.get("kind") == "setting_mattered" and (not project_paper or l.get("paper") != project_paper):
            skipped.append((l, "other_paper", f"{SKIP_REASONS['other_paper']} (lesson: {l.get('paper') or 'unknown'}"
                                              f", this project: {project_paper or 'unknown'})"))
        else:
            ok.append(l)
    rank = lambda l: (-len(want & set(l.get("tags") or [])), -(l.get("times_applied") or 0),  # noqa: E731
                      l.get("created_at") or "")
    best: dict[tuple, dict] = {}
    for l in sorted(ok, key=rank):
        key = (l.get("kind"), frozenset(l.get("tags") or []))
        if key in best:
            skipped.append((l, "duplicate", f"{SKIP_REASONS['duplicate']} ({best[key]['id']})"))
        else:
            best[key] = l
    ranked = sorted(best.values(), key=rank)
    skipped += [(l, "over_limit", SKIP_REASONS["over_limit"]) for l in ranked[limit:]]
    return ranked[:limit], skipped


def choose(db, tags: list[str], project: dict, limit: int):
    """select() over the lessons sharing a tag, with each lesson's paper resolved."""
    if not tags:
        return [], []
    rows = db.table("lessons").select("id,kind,text,tags,created_at,times_applied,project_id,evidence_event_id") \
        .overlaps("tags", tags).limit(500).execute().data
    pids = sorted({r["project_id"] for r in rows if r.get("project_id")})
    arxiv = {p["id"]: p.get("arxiv_id") for p in db.table("projects").select("id,arxiv_id").in_("id", pids)
             .execute().data} if pids else {}
    for r in rows:
        r["paper"] = paper_key(r, arxiv)
    return select(rows, tags, project.get("arxiv_id"), limit)


def relevant(db, tags: list[str], limit: int, project: Optional[dict] = None) -> list[dict]:
    return choose(db, tags, project or {}, limit)[0]


def apply(db, lessons: list[dict], tags: list[str], where: str, *, project_id=None, task_id=None,
          agent_id=None) -> None:
    from lab.db import emit

    for rank, l in enumerate(lessons, 1):
        shared = sorted(set(tags) & set(l.get("tags") or []))
        emit(db, "lesson_applied", f"lesson applied to the {where}: {l['text'][:120]}",
             f"tags matched: {', '.join(shared)}; the lesson was added to the {where} prompt",
             project_id=project_id, task_id=task_id, agent_id=agent_id,
             data={"lesson_id": l["id"], "kind": l.get("kind"), "tags": shared, "where": where, "rank": rank,
                   "overlap": len(shared), "times_applied": (l.get("times_applied") or 0) + 1,
                   "paper": l.get("paper")})
        db.table("lessons").update({"times_applied": (l.get("times_applied") or 0) + 1}).eq("id", l["id"]).execute()


def skip(db, skipped: list, tags: list[str], where: str, *, project_id=None, task_id=None) -> None:
    from lab.db import emit

    for l, code, detail in skipped:
        shared = sorted(set(tags) & set(l.get("tags") or []))
        emit(db, "lesson_skipped", f"lesson not used in the {where}: {l['text'][:120]}", detail,
             project_id=project_id, task_id=task_id,
             data={"lesson_id": l["id"], "reason": code, "detail": detail, "kind": l.get("kind"), "tags": shared,
                   "where": where, "paper": l.get("paper")})


# ---- write --------------------------------------------------------------------------------------------------------

def check_proposals(props: list[dict], event_ids: set[str], existing: list[dict] = ()) -> tuple[list[dict], list[str]]:
    """Kept only with evidence in event_ids; a duplicate (same kind and tag set) of an existing or kept lesson is
    dropped."""
    seen = {(l.get("kind"), frozenset(l.get("tags") or [])): l.get("id") for l in existing}
    kept, dropped = [], []
    for p in props or []:
        text, tags = str(p.get("text") or "").strip(), [str(t) for t in p.get("tags") or [] if str(t).strip()]
        if not text:
            dropped.append("empty text")
        elif p.get("kind") not in KINDS:
            dropped.append(f"{text[:60]}: kind {p.get('kind')!r} is not one of {list(KINDS)}")
        elif p.get("evidence_event_id") not in event_ids:
            dropped.append(f"{text[:60]}: evidence {p.get('evidence_event_id')!r} is not an event of this project")
        elif not tags:
            dropped.append(f"{text[:60]}: no tags")
        elif (p["kind"], frozenset(tags)) in seen:
            dropped.append(f"{text[:60]}: duplicate of lesson {seen[(p['kind'], frozenset(tags))] or 'proposed above'}")
        elif len(kept) >= MAX_LESSONS:
            dropped.append(f"{text[:60]}: more than {MAX_LESSONS} lessons")
        else:
            kept.append({"text": text, "tags": tags, "evidence_event_id": p["evidence_event_id"], "kind": p["kind"]})
            seen[(p["kind"], frozenset(tags))] = None
    return kept, dropped


def recoveries(step_tasks: list[dict]) -> list[tuple[int, str, str]]:
    """(step, failed task id, the later done task id) for each step that failed and then succeeded."""
    out = []
    by_step: dict[int, list[dict]] = {}
    for t in step_tasks:
        by_step.setdefault(int(t["input"]["step"]), []).append(t)
    for step, ts in sorted(by_step.items()):
        ts = sorted(ts, key=lambda t: t.get("created_at") or "")
        failed = [t for t in ts if t["status"] == "failed"]
        done = [t for t in ts if t["status"] == "done"]
        if failed and done and done[-1]["created_at"] > failed[0]["created_at"]:
            out.append((step, failed[0]["id"], done[-1]["id"]))
    return out


PROPOSAL_SCHEMA = {"type": "object", "properties": {"lessons": {"type": "array", "items": {
    "type": "object", "properties": {
        "text": {"type": "string", "description": "one or two sentences a future agent can act on"},
        "tags": {"type": "array", "items": {"type": "string"},
                 "description": "domain (e.g. mnist), capability (e.g. write_code), error signature if any"},
        "evidence_event_id": {"type": "string", "description": "the id of the event that shows it"},
        "kind": {"type": "string", "enum": list(KINDS)}},
    "required": ["text", "tags", "evidence_event_id", "kind"]}}}, "required": ["lessons"]}


def propose(db, llm, project: dict, reporter: dict, trigger: str, focus: str) -> tuple[list[dict], list[str]]:
    """The Reporter proposes lessons from the project's events; code keeps those with real evidence. Returns
    (inserted lessons, dropped reasons)."""
    from lab.db import emit
    from lab.llm import Request

    events = db.table("events").select("id,type,message,reason").eq("project_id", project["id"]) \
        .order("ts", desc=True).limit(80).execute().data
    lines = "\n".join(f"{e['id']} | {e['type']} | {e['message'][:160]} | why: {e['reason'][:200]}"
                      for e in reversed(events))
    prompt = (f"Project: {project.get('title')} (tags: {', '.join(project.get('tags') or []) or 'none'})\n"
              f"What to learn from: {focus}\n\nEvents (id | type | what | why):\n{lines}\n\n"
              f"Propose at most {MAX_LESSONS} lessons that would make the next run of a similar paper faster or "
              f"more correct. Each must cite the id of the event that shows it as evidence_event_id. Kinds: "
              f"failure_fix (an error and what fixed it), setting_mattered (a setting that changed a result), "
              f"budget (time or scale), agent_choice (which agent did well or badly).")
    resp = llm.call(Request(agent=reporter["name"], system=reporter["role_prompt"], prompt=prompt,
                            schema=PROPOSAL_SCHEMA, model="smart"), agent_id=reporter["id"])
    props = (resp.output or {}).get("lessons") if isinstance(resp.output, dict) else []
    existing = db.table("lessons").select("id,kind,tags").limit(1000).execute().data
    kept, dropped = check_proposals(props or [], {e["id"] for e in events}, existing)
    rows = [db.table("lessons").insert({**k, "project_id": project["id"]}).execute().data[0] for k in kept]
    emit(db, "lessons_proposed", f"{reporter['name']} proposed {len(props or [])} lessons, {len(rows)} kept",
         f"{focus}; code kept only lessons whose evidence is an event of this project"
         + (f"; dropped: {'; '.join(dropped)}" if dropped else ""), project_id=project["id"], agent_id=reporter["id"],
         data={"trigger": trigger, "kept": [r["id"] for r in rows], "dropped": dropped, "model": resp.model,
               "mode": resp.mode})
    return rows, dropped


# ---- seed ---------------------------------------------------------------------------------------------------------

def import_round0(db) -> list[str]:
    """Insert F1-F8 once (each with a lesson_imported event as its evidence). Returns the findings inserted."""
    from lab.db import emit

    done = []
    for l in ROUND0_LESSONS:
        key = f"round0-{l['finding'].lower()}"
        if db.table("lessons").select("id").contains("tags", [key]).execute().data:
            continue
        ev = emit(db, "lesson_imported", f"{LABEL}: MatchDG {l['finding']}",
                  f"seed lesson allowed by the organizers (SPEC §6); evidence: {l['evidence']}",
                  data={"finding": l["finding"], "source": l["evidence"]})
        db.table("lessons").insert({"kind": l["kind"], "text": l["text"], "tags": l["tags"],
                                    "evidence_event_id": ev["id"]}).execute()
        done.append(l["finding"])
    return done


# ---- memory effect (R14) ------------------------------------------------------------------------------------------

def _ts(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _one(project: dict, tasks: list[dict], tokens: int) -> dict:
    runs = sorted([t for t in tasks if t.get("capability") == "run"], key=lambda t: t.get("created_at") or "")
    first_ok = next((i for i, t in enumerate(runs) if t["status"] == "done"), None)
    seconds = None
    if first_ok is not None:
        seconds = round((_ts(runs[first_ok]["finished_at"]) - _ts(project["created_at"])).total_seconds(), 1)
    return {"retries_before_first_success": sum(1 for t in runs[:first_ok] if t["status"] == "failed")
            if first_ok is not None else sum(1 for t in runs if t["status"] == "failed"),
            "seconds_to_first_result": seconds, "llm_tokens": int(tokens)}


def effect(p1: dict, tasks1: list[dict], tokens1: int, p2: dict, tasks2: list[dict], tokens2: int) -> dict:
    a, b = _one(p1, tasks1, tokens1), _one(p2, tasks2, tokens2)
    delta = {k: (None if a[k] is None or b[k] is None else round(b[k] - a[k], 1) if isinstance(a[k], float)
                 else b[k] - a[k]) for k in a}
    return {"run1": a, "run2": b, "delta": delta}


def project_effect(db, run1: str, run2: str) -> dict:
    from lab.db import emit

    def load(pid):
        p = db.table("projects").select("id,title,created_at").eq("id", pid).execute().data[0]
        tasks = db.table("tasks").select("id,capability,status,created_at,finished_at").eq("project_id", pid) \
            .execute().data
        ids = [t["id"] for t in tasks]
        calls = db.table("llm_calls").select("tokens_in,tokens_out").in_("task_id", ids).execute().data if ids else []
        return p, tasks, sum((c["tokens_in"] or 0) + (c["tokens_out"] or 0) for c in calls)

    p1, t1, k1 = load(run1)
    p2, t2, k2 = load(run2)
    e = effect(p1, t1, k1, p2, t2, k2)
    applied = db.table("events").select("id").eq("project_id", run2).eq("type", "lesson_applied").execute().data
    e["lessons_applied_in_run2"] = len(applied)
    emit(db, "memory_effect", f"memory effect: run 2 vs run 1 ({p1['title']})",
         f"computed from rows: retries {e['run1']['retries_before_first_success']} → "
         f"{e['run2']['retries_before_first_success']}, seconds to first result "
         f"{e['run1']['seconds_to_first_result']} → {e['run2']['seconds_to_first_result']}, LLM tokens "
         f"{k1} → {k2}; {len(applied)} lessons applied in run 2", project_id=run2,
         data={**e, "run1_project": run1, "run2_project": run2})
    return e


def main(argv=None) -> None:
    from lab.db import client

    ap = argparse.ArgumentParser(description="Research memory tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import-round0", help="seed the MatchDG F1-F8 lessons (idempotent)")
    e = sub.add_parser("effect", help="compare run 2 with run 1 of the same paper (writes a memory_effect event)")
    e.add_argument("run1")
    e.add_argument("run2")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    db = client()
    if a.cmd == "import-round0":
        print("imported:", import_round0(db) or "nothing new")
    else:
        print(json.dumps(project_effect(db, a.run1, a.run2), indent=1))


if __name__ == "__main__":
    main()
