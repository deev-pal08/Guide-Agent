"""Tests for the feedback parser + apply_feedback logic.

The parser itself depends on Claude — we mock the parent _single_turn
to return synthetic JSON. This tests the orchestration around it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from guide_agent.agent.feedback import FeedbackParser, apply_feedback
from guide_agent.config import AppConfig, LLMConfig
from guide_agent.models import EmailFeedback, TaskStatus, TaskUpdate
from guide_agent.state.store import StateStore


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path)


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key")
    return AppConfig(llm=LLMConfig())


def _seed_plan(state: StateStore, task_titles: list[str]) -> tuple[int, list[int]]:
    """Create a bug class, plan, and N tasks. Returns (plan_id, task_ids)."""
    bid = state.upsert_bug_class("postmessage")
    plan_id = state.create_plan(
        bug_class_id=bid, phase="learn", date="2026-06-06",
        target_hours=3.0, plan_dict={},
    )
    task_ids = [
        state.create_task(
            plan_id=plan_id, bug_class_id=bid, phase="learn",
            title=title, description="",
        )
        for title in task_titles
    ]
    return plan_id, task_ids


# ---------------------------------------------------------------------------
# Parser orchestration (mocked LLM)
# ---------------------------------------------------------------------------


def test_parser_returns_email_feedback(config, state):
    parser = FeedbackParser(config, state)
    mock_response = (
        '{"task_updates": ['
        '{"task_id": 1, "status": "done", "actual_hours": 2.5, "notes": "great", "learnings": "x"}'
        '], "general_notes": "", "total_hours_reported": 2.5}'
    )
    with patch.object(parser, "_single_turn", return_value=mock_response):
        feedback = parser.parse("1: done 2.5h — great", task_count=1)
    assert isinstance(feedback, EmailFeedback)
    assert len(feedback.task_updates) == 1
    assert feedback.task_updates[0].status == TaskStatus.DONE
    assert feedback.task_updates[0].actual_hours == 2.5


def test_parser_handles_skipped_task(config, state):
    parser = FeedbackParser(config, state)
    mock_response = (
        '{"task_updates": ['
        '{"task_id": 2, "status": "skipped", "notes": "too easy", "learnings": ""}'
        '], "general_notes": "", "total_hours_reported": null}'
    )
    with patch.object(parser, "_single_turn", return_value=mock_response):
        feedback = parser.parse("2: skip — too easy", task_count=2)
    assert feedback.task_updates[0].status == TaskStatus.SKIPPED


def test_parser_extracts_general_notes(config, state):
    parser = FeedbackParser(config, state)
    mock_response = (
        '{"task_updates": [], '
        '"general_notes": "Today felt rushed, want lighter load tomorrow.", '
        '"total_hours_reported": 0}'
    )
    with patch.object(parser, "_single_turn", return_value=mock_response):
        feedback = parser.parse("Today felt rushed", task_count=3)
    assert "rushed" in feedback.general_notes


# ---------------------------------------------------------------------------
# apply_feedback — pure state machinery
# ---------------------------------------------------------------------------


def test_apply_feedback_marks_task_done(state):
    _, task_ids = _seed_plan(state, ["one", "two"])
    plan_tasks = [state.get_task(t) for t in task_ids]
    feedback = EmailFeedback(task_updates=[
        TaskUpdate(task_id=1, status=TaskStatus.DONE, actual_hours=1.5),
    ])
    updated = apply_feedback(state, feedback, plan_tasks)
    assert updated == 1
    t = state.get_task(task_ids[0])
    assert t["status"] == "done"
    assert t["actual_hours"] == 1.5


def test_apply_feedback_logs_into_feedback_log(state):
    _, task_ids = _seed_plan(state, ["one"])
    plan_tasks = [state.get_task(t) for t in task_ids]
    feedback = EmailFeedback(task_updates=[
        TaskUpdate(task_id=1, status=TaskStatus.DONE,
                   actual_hours=2.0, notes="great", learnings="x"),
    ])
    apply_feedback(state, feedback, plan_tasks)

    bid = state.get_bug_class("postmessage")["id"]
    recent = state.get_recent_feedback(bid)
    assert len(recent) == 1
    assert recent[0]["actual_hours"] == 2.0
    assert recent[0]["notes"] == "great"


def test_apply_feedback_persists_general_notes(state):
    _, task_ids = _seed_plan(state, ["one"])
    plan_tasks = [state.get_task(t) for t in task_ids]
    feedback = EmailFeedback(
        task_updates=[],
        general_notes="want harder tasks next time",
    )
    apply_feedback(state, feedback, plan_tasks)

    notes = state.get_user_notes()
    assert len(notes) == 1
    assert "harder" in notes[0]["note"]


def test_apply_feedback_skips_out_of_range_task_id(state):
    _, task_ids = _seed_plan(state, ["one"])
    plan_tasks = [state.get_task(t) for t in task_ids]
    feedback = EmailFeedback(task_updates=[
        TaskUpdate(task_id=99, status=TaskStatus.DONE),
    ])
    updated = apply_feedback(state, feedback, plan_tasks)
    assert updated == 0


def test_apply_feedback_multiple_tasks(state):
    _, task_ids = _seed_plan(state, ["one", "two", "three"])
    plan_tasks = [state.get_task(t) for t in task_ids]
    feedback = EmailFeedback(task_updates=[
        TaskUpdate(task_id=1, status=TaskStatus.DONE, actual_hours=1.0),
        TaskUpdate(task_id=2, status=TaskStatus.SKIPPED, notes="too easy"),
        TaskUpdate(task_id=3, status=TaskStatus.DONE, actual_hours=2.0),
    ])
    updated = apply_feedback(state, feedback, plan_tasks)
    assert updated == 3
    assert state.get_task(task_ids[0])["status"] == "done"
    assert state.get_task(task_ids[1])["status"] == "skipped"
    assert state.get_task(task_ids[2])["status"] == "done"
