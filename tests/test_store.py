"""Tests for the SQLite state store."""

from __future__ import annotations

import pytest

from guide_agent.state.store import StateStore


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path)


# ---------------------------------------------------------------------------
# Bug classes
# ---------------------------------------------------------------------------


def test_upsert_bug_class_creates_and_returns_id(store):
    bid = store.upsert_bug_class("postmessage")
    assert bid > 0
    bc = store.get_bug_class(bid)
    assert bc is not None
    assert bc["name"] == "postmessage"
    assert bc["status"] == "in_progress"


def test_upsert_bug_class_idempotent(store):
    bid1 = store.upsert_bug_class("postmessage")
    bid2 = store.upsert_bug_class("PostMessage")  # case + whitespace normalized
    assert bid1 == bid2


def test_get_bug_class_by_name_and_id(store):
    bid = store.upsert_bug_class("ssrf")
    by_id = store.get_bug_class(bid)
    by_name = store.get_bug_class("ssrf")
    assert by_id is not None and by_name is not None
    assert by_id["id"] == by_name["id"]


def test_parent_child_hierarchy(store):
    parent_id = store.upsert_bug_class("client-side web bugs", is_leaf=False)
    child_id = store.upsert_bug_class("postmessage", parent_id=parent_id)
    children = store.get_children(parent_id)
    assert len(children) == 1
    assert children[0]["id"] == child_id


def test_mark_mastered_and_resume(store):
    bid = store.upsert_bug_class("idor")
    store.mark_mastered(bid)
    assert store.get_bug_class(bid)["status"] == "mastered"
    assert store.get_bug_class(bid)["mastered_at"] is not None

    store.mark_in_progress(bid)
    bc = store.get_bug_class(bid)
    assert bc["status"] == "in_progress"
    assert bc["mastered_at"] is None


def test_get_all_in_progress_and_mastered(store):
    a = store.upsert_bug_class("a")
    b = store.upsert_bug_class("b")
    c = store.upsert_bug_class("c")
    store.mark_mastered(b)
    in_progress = store.get_all_in_progress()
    mastered = store.get_all_mastered()
    in_progress_ids = {bc["id"] for bc in in_progress}
    mastered_ids = {bc["id"] for bc in mastered}
    assert in_progress_ids == {a, c}
    assert mastered_ids == {b}


# ---------------------------------------------------------------------------
# Phase progress
# ---------------------------------------------------------------------------


def test_bump_phase_progress_creates_then_increments(store):
    bid = store.upsert_bug_class("postmessage")
    store.bump_phase_progress(bid, "learn", resources_added=5)
    pp = store.get_phase_progress(bid, "learn")
    assert pp["resources_consumed"] == 5
    assert pp["last_run"] is not None

    store.bump_phase_progress(bid, "learn", resources_added=3)
    pp = store.get_phase_progress(bid, "learn")
    assert pp["resources_consumed"] == 8


def test_phase_progress_notes_preserved_on_bump(store):
    bid = store.upsert_bug_class("ssrf")
    store.bump_phase_progress(bid, "learn", resources_added=1, notes="initial")
    store.bump_phase_progress(bid, "learn", resources_added=1)
    pp = store.get_phase_progress(bid, "learn")
    assert pp["notes"] == "initial"


def test_get_all_phase_progress(store):
    bid = store.upsert_bug_class("postmessage")
    store.bump_phase_progress(bid, "learn", resources_added=10)
    store.bump_phase_progress(bid, "examples", resources_added=20)
    all_pp = store.get_all_phase_progress(bid)
    phases = {p["phase"] for p in all_pp}
    assert phases == {"learn", "examples"}


# ---------------------------------------------------------------------------
# Plans + tasks
# ---------------------------------------------------------------------------


def test_create_plan_and_attach_tasks(store):
    bid = store.upsert_bug_class("postmessage")
    plan_id = store.create_plan(
        bug_class_id=bid,
        phase="learn",
        date="2026-06-06",
        target_hours=3.0,
        plan_dict={"meta": "test"},
        rationale="testing",
    )
    assert plan_id > 0

    t1 = store.create_task(
        plan_id=plan_id, bug_class_id=bid, phase="learn",
        title="Drain HackTricks postMessage", description="Read it all",
        task_type="read", estimated_hours=2.0,
    )
    t2 = store.create_task(
        plan_id=plan_id, bug_class_id=bid, phase="learn",
        title="OWASP postMessage cheat sheet", description="Cover-to-cover",
        task_type="read", estimated_hours=1.0,
    )

    tasks = store.get_tasks_for_plan(plan_id)
    assert len(tasks) == 2
    assert {t["id"] for t in tasks} == {t1, t2}


def test_update_task_status_done_sets_completed_date(store):
    bid = store.upsert_bug_class("postmessage")
    plan_id = store.create_plan(
        bug_class_id=bid, phase="learn", date="2026-06-06",
        target_hours=1.0, plan_dict={},
    )
    task_id = store.create_task(
        plan_id=plan_id, bug_class_id=bid, phase="learn",
        title="x", description="y",
    )
    store.update_task_status(
        task_id, status="done", actual_hours=1.5, learnings="learned X",
    )
    t = store.get_task(task_id)
    assert t["status"] == "done"
    assert t["actual_hours"] == 1.5
    assert t["learnings"] == "learned X"
    assert t["completed_date"] is not None


def test_update_task_status_skipped_leaves_completed_date_null(store):
    bid = store.upsert_bug_class("postmessage")
    plan_id = store.create_plan(
        bug_class_id=bid, phase="learn", date="2026-06-06",
        target_hours=1.0, plan_dict={},
    )
    task_id = store.create_task(
        plan_id=plan_id, bug_class_id=bid, phase="learn",
        title="x", description="y",
    )
    store.update_task_status(task_id, status="skipped", learnings="too easy")
    t = store.get_task(task_id)
    assert t["status"] == "skipped"
    assert t["completed_date"] is None


def test_get_pending_tasks_filters_by_bug_class(store):
    a = store.upsert_bug_class("a")
    b = store.upsert_bug_class("b")
    p1 = store.create_plan(
        bug_class_id=a, phase="learn", date="2026-06-06",
        target_hours=1.0, plan_dict={},
    )
    p2 = store.create_plan(
        bug_class_id=b, phase="learn", date="2026-06-06",
        target_hours=1.0, plan_dict={},
    )
    store.create_task(plan_id=p1, bug_class_id=a, phase="learn", title="x", description="")
    store.create_task(plan_id=p2, bug_class_id=b, phase="learn", title="y", description="")

    assert len(store.get_pending_tasks()) == 2
    assert len(store.get_pending_tasks(a)) == 1


# ---------------------------------------------------------------------------
# Consumed resources
# ---------------------------------------------------------------------------


def test_mark_consumed_is_idempotent(store):
    bid = store.upsert_bug_class("postmessage")
    store.mark_consumed(bid, "https://example.com/a", "learn", title="A")
    store.mark_consumed(bid, "https://example.com/a", "learn", title="A")
    urls = store.get_consumed_urls(bid)
    assert urls == {"https://example.com/a"}


def test_get_consumed_count_with_and_without_phase_filter(store):
    bid = store.upsert_bug_class("postmessage")
    store.mark_consumed(bid, "https://example.com/a", "learn")
    store.mark_consumed(bid, "https://example.com/b", "learn")
    store.mark_consumed(bid, "https://example.com/c", "examples")
    assert store.get_consumed_count(bid) == 3
    assert store.get_consumed_count(bid, "learn") == 2
    assert store.get_consumed_count(bid, "examples") == 1


def test_consumed_resources_scoped_per_bug_class(store):
    a = store.upsert_bug_class("a")
    b = store.upsert_bug_class("b")
    store.mark_consumed(a, "https://example.com/shared", "learn")
    assert store.get_consumed_urls(a) == {"https://example.com/shared"}
    assert store.get_consumed_urls(b) == set()


# ---------------------------------------------------------------------------
# Feedback + user notes
# ---------------------------------------------------------------------------


def test_log_feedback_and_recent(store):
    bid = store.upsert_bug_class("postmessage")
    plan_id = store.create_plan(
        bug_class_id=bid, phase="learn", date="2026-06-06",
        target_hours=1.0, plan_dict={},
    )
    task_id = store.create_task(
        plan_id=plan_id, bug_class_id=bid, phase="learn",
        title="HackTricks", description="x",
    )
    store.log_feedback(
        task_id, status="done", actual_hours=2.0,
        notes="great", learnings="x", source="email",
    )
    recent = store.get_recent_feedback(bid)
    assert len(recent) == 1
    assert recent[0]["title"] == "HackTricks"
    assert recent[0]["actual_hours"] == 2.0


def test_user_notes_append_and_list(store):
    store.append_user_note("registered for CTF")
    store.append_user_note("done with HackTricks")
    notes = store.get_user_notes()
    assert len(notes) == 2
    # Most recent first
    assert notes[0]["note"] == "done with HackTricks"


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


def test_meta_set_and_get(store):
    store.set_meta("foo", "bar")
    assert store.get_meta("foo") == "bar"
    store.set_meta("foo", "baz")
    assert store.get_meta("foo") == "baz"
    assert store.get_meta("missing") is None


# ---------------------------------------------------------------------------
# resources_json (multi-URL bundles per task)
# ---------------------------------------------------------------------------


def test_create_task_persists_resources_list(store):
    bid = store.upsert_bug_class("postmessage")
    plan_id = store.create_plan(
        bug_class_id=bid, phase="examples", date="2026-06-06",
        target_hours=1.5, plan_dict={},
    )
    task_id = store.create_task(
        plan_id=plan_id, bug_class_id=bid, phase="examples",
        title="Drain 3 reports", description="batch read",
        resource_url="https://hackerone.com/reports/231053",
        resource_name="Shopify",
        resources=[
            {"url": "https://hackerone.com/reports/231053", "name": "Shopify", "note": "$3000"},
            {"url": "https://hackerone.com/reports/603764", "name": "Upserve", "note": "$2500"},
            {"url": "https://hackerone.com/reports/900619", "name": "PlayStation", "note": "$1000"},
        ],
    )
    task = store.get_task(task_id)
    assert task is not None
    assert task["resources"] == [
        {"url": "https://hackerone.com/reports/231053", "name": "Shopify", "note": "$3000"},
        {"url": "https://hackerone.com/reports/603764", "name": "Upserve", "note": "$2500"},
        {"url": "https://hackerone.com/reports/900619", "name": "PlayStation", "note": "$1000"},
    ]
    # Legacy fields still surface via primary_*
    assert task["primary_resource_url"] == "https://hackerone.com/reports/231053"
    assert task["primary_resource_name"] == "Shopify"


def test_create_task_defaults_to_empty_resources(store):
    bid = store.upsert_bug_class("postmessage")
    plan_id = store.create_plan(
        bug_class_id=bid, phase="learn", date="2026-06-06",
        target_hours=1.0, plan_dict={},
    )
    task_id = store.create_task(
        plan_id=plan_id, bug_class_id=bid, phase="learn",
        title="solo task", description="x",
        resource_url="https://example.com",
    )
    task = store.get_task(task_id)
    assert task["resources"] == []
    assert task["primary_resource_url"] == "https://example.com"


def test_get_tasks_for_plan_hydrates_resources(store):
    bid = store.upsert_bug_class("postmessage")
    plan_id = store.create_plan(
        bug_class_id=bid, phase="examples", date="2026-06-06",
        target_hours=1.0, plan_dict={},
    )
    store.create_task(
        plan_id=plan_id, bug_class_id=bid, phase="examples",
        title="t1", description="d",
        resources=[{"url": "https://a.com", "name": "A", "note": ""}],
    )
    store.create_task(
        plan_id=plan_id, bug_class_id=bid, phase="examples",
        title="t2", description="d",
        resources=[],
    )
    tasks = store.get_tasks_for_plan(plan_id)
    assert len(tasks) == 2
    assert tasks[0]["resources"] == [{"url": "https://a.com", "name": "A", "note": ""}]
    assert tasks[1]["resources"] == []


# ---------------------------------------------------------------------------
# tools_section on plans
# ---------------------------------------------------------------------------


def test_create_plan_persists_tools_section(store):
    bid = store.upsert_bug_class("postmessage")
    plan_id = store.create_plan(
        bug_class_id=bid, phase="execute", date="2026-06-06",
        target_hours=3.0, plan_dict={},
        tools_section=[
            {"url": "https://github.com/x/frogpost", "name": "FrogPost", "note": "Chrome ext"},
            {"url": "https://github.com/x/postscanner", "name": "PostScanner", "note": ""},
        ],
    )
    plan = store.get_plan(plan_id)
    assert plan is not None
    assert plan["tools_section"] == [
        {"url": "https://github.com/x/frogpost", "name": "FrogPost", "note": "Chrome ext"},
        {"url": "https://github.com/x/postscanner", "name": "PostScanner", "note": ""},
    ]


def test_create_plan_defaults_to_empty_tools_section(store):
    bid = store.upsert_bug_class("postmessage")
    plan_id = store.create_plan(
        bug_class_id=bid, phase="learn", date="2026-06-06",
        target_hours=1.0, plan_dict={},
    )
    plan = store.get_plan(plan_id)
    assert plan["tools_section"] == []


def test_get_latest_plan_hydrates_tools_section(store):
    bid = store.upsert_bug_class("postmessage")
    store.create_plan(
        bug_class_id=bid, phase="execute", date="2026-06-06",
        target_hours=3.0, plan_dict={},
        tools_section=[{"url": "https://example.com/tool", "name": "X", "note": ""}],
    )
    plan = store.get_latest_plan_for_bug_class(bid)
    assert plan["tools_section"] == [
        {"url": "https://example.com/tool", "name": "X", "note": ""},
    ]
