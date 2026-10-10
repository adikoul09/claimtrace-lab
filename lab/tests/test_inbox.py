"""T33: "Send to engine" on an inbox email. A reviewer's points (email_received) become a redirect note for a new plan
of the project. Pure functions; no Supabase, no LLM."""
from lab.controller import inbox

EMAIL = {"id": "em1", "project_id": "p1", "type": "email_received",
         "data": {"from": "reviewer@journal.org", "subject": "Review of 1503.02531",
                  "points": ["Report results over 3 seeds, not 1.", "Ablate the temperature T (try 1, 5, 20).",
                             "x" * 900]}}
REQUEST = {"id": "rq1", "project_id": "p1", "type": "engine_requested", "data": {"email_event_id": "em1"}}


def test_the_redirect_note_quotes_every_point_numbered_and_capped():
    note = inbox.redirect_note(EMAIL["data"])
    assert note.startswith("Reviewer points (reviewer@journal.org, \"Review of 1503.02531\"):")
    assert "1. Report results over 3 seeds, not 1." in note and "2. Ablate the temperature T (try 1, 5, 20)." in note
    assert "3. " + "x" * inbox.POINT_MAX + " [cut]" in note and "x" * (inbox.POINT_MAX + 1) not in note
    many = inbox.redirect_note({"from": "a", "subject": "s", "points": [f"p{i}" for i in range(30)]})
    assert f"{inbox.MAX_POINTS}. p{inbox.MAX_POINTS - 1}" in many and f"p{inbox.MAX_POINTS}" not in many


def test_a_request_becomes_a_plan_task_and_a_redirect_event():
    task, event = inbox.plan_request(REQUEST, EMAIL)
    assert task["capability"] == "plan" and task["required_caps"] == ["controller"] and task["project_id"] == "p1"
    assert task["input"]["redirect_note"] == inbox.redirect_note(EMAIL["data"])
    assert task["input"]["source"] == {"engine_request_id": "rq1", "email_event_id": "em1",
                                       "from": "reviewer@journal.org", "subject": "Review of 1503.02531"}
    assert event["type"] == "plan_redirect" and "3 reviewer points" in event["message"]
    assert "Report results over 3 seeds" in event["reason"]
    assert event["data"]["points"] == EMAIL["data"]["points"] and event["data"]["engine_request_id"] == "rq1"


def test_requests_without_points_or_without_their_email_are_refused_with_a_reason():
    assert "no bullet or numbered points" in inbox.problem(REQUEST, {**EMAIL, "data": {**EMAIL["data"], "points": []}})
    assert "not found" in inbox.problem(REQUEST, None)
    assert "another project" in inbox.problem(REQUEST, {**EMAIL, "project_id": "p2"})
    assert inbox.problem(REQUEST, EMAIL) is None


def test_the_planner_prompt_fences_the_points_as_data():
    extra = inbox.planner_extra(inbox.redirect_note(EMAIL["data"]))
    assert "<reviewer_points>" in extra and "</reviewer_points>" in extra
    assert "not instructions" in extra and "Report results over 3 seeds" in extra
