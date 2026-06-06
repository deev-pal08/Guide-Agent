"""Tests for the HTML email template rendering."""

from __future__ import annotations

from guide_agent.email.templates import render_plan_email, render_text_fallback
from guide_agent.models import (
    Phase,
    Plan,
    Priority,
    ResearchMode,
    Resource,
    Task,
    TaskType,
)


def _sample_plan(**overrides) -> Plan:
    base = Plan(
        bug_class_name="postmessage",
        phase=Phase.LEARN,
        date="2026-06-06",
        target_hours=3.0,
        rationale="Fresh start on postMessage — drain foundational theory.",
        tasks=[
            Task(
                bug_class_name="postmessage",
                phase=Phase.LEARN,
                title="Drain ALL HackTricks + OWASP postMessage theory",
                description=(
                    "Read HackTricks postMessage page in full, then OWASP "
                    "postMessage cheat sheet, then MDN postMessage reference."
                ),
                task_type=TaskType.READ,
                priority=Priority.CRITICAL,
                estimated_hours=2.5,
                primary_resource_url="https://book.hacktricks.wiki/postmessage",
                primary_resource_name="postMessage — HackTricks",
                why="The canonical security framing for postMessage.",
            ),
            Task(
                bug_class_name="postmessage",
                phase=Phase.LEARN,
                title="Read HTML Living Standard cross-document messaging",
                description="The authoritative spec.",
                task_type=TaskType.READ,
                priority=Priority.HIGH,
                estimated_hours=0.5,
                primary_resource_url="https://html.spec.whatwg.org/multipage/web-messaging.html",
                primary_resource_name="Web messaging — HTML Living Standard",
                why="Ground truth for implementation behavior.",
            ),
        ],
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------


def test_render_plan_email_contains_bug_class():
    html = render_plan_email(_sample_plan())
    assert "postmessage" in html.lower()


def test_render_plan_email_includes_all_tasks():
    plan = _sample_plan()
    html = render_plan_email(plan)
    for task in plan.tasks:
        assert task.title in html
        assert task.primary_resource_url in html


def test_render_plan_email_shows_phase_uppercase():
    html = render_plan_email(_sample_plan())
    assert "LEARN" in html


def test_render_plan_email_includes_research_mode_in_header():
    plan = _sample_plan(
        phase=Phase.RESEARCH,
        research_mode=ResearchMode.GAP_ANALYSIS,
    )
    html = render_plan_email(plan)
    assert "RESEARCH" in html
    assert "Gap Analysis" in html


def test_render_plan_email_skips_rationale_block_when_empty():
    html = render_plan_email(_sample_plan(rationale=""))
    assert "Why this plan" not in html


def test_render_plan_email_priority_colors():
    plan = _sample_plan()
    plan.tasks[0].priority = Priority.CRITICAL
    plan.tasks[1].priority = Priority.LOW
    html = render_plan_email(plan)
    # CRITICAL = red
    assert "#ef4444" in html
    # LOW = gray
    assert "#6b7280" in html


def test_render_plan_email_escapes_html_in_user_content():
    plan = _sample_plan()
    plan.tasks[0].title = "<script>alert(1)</script>"
    html = render_plan_email(plan)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_plan_email_long_resource_name_truncates():
    plan = _sample_plan()
    plan.tasks[0].primary_resource_name = "a" * 200
    html = render_plan_email(plan)
    assert "a" * 200 not in html  # truncated
    assert "..." in html


def test_render_plan_email_reply_format_visible():
    html = render_plan_email(_sample_plan())
    # Reply hint should always be present
    assert "How to reply" in html
    assert "1: done" in html


# ---------------------------------------------------------------------------
# Text fallback
# ---------------------------------------------------------------------------


def test_render_text_fallback_includes_all_tasks():
    plan = _sample_plan()
    text = render_text_fallback(plan)
    for task in plan.tasks:
        assert task.title in text


def test_render_text_fallback_includes_resource_urls():
    plan = _sample_plan()
    text = render_text_fallback(plan)
    for task in plan.tasks:
        assert task.primary_resource_url in text


def test_render_text_fallback_shows_phase_uppercase():
    text = render_text_fallback(_sample_plan())
    assert "LEARN" in text


def test_render_text_fallback_includes_reply_hint():
    text = render_text_fallback(_sample_plan())
    assert "Reply with" in text


# ---------------------------------------------------------------------------
# Resources list rendering — the new shape
# ---------------------------------------------------------------------------


def _plan_with_resources_bundle() -> Plan:
    return Plan(
        bug_class_name="postmessage",
        phase=Phase.EXAMPLES,
        date="2026-06-06",
        target_hours=1.5,
        rationale="Examples phase — drain real HackerOne postMessage reports.",
        tasks=[
            Task(
                bug_class_name="postmessage",
                phase=Phase.EXAMPLES,
                title="Drain 4 HackerOne postMessage reports",
                description="Read all four reports, group by failure mode.",
                task_type=TaskType.RESEARCH,
                priority=Priority.CRITICAL,
                estimated_hours=1.5,
                primary_resource_url="https://hackerone.com/reports/231053",
                primary_resource_name="Shopify structured-clone bypass",
                resources=[
                    Resource(
                        url="https://hackerone.com/reports/231053",
                        name="Shopify — Structured-clone abuse",
                        note="$3000 — most severe",
                    ),
                    Resource(
                        url="https://hackerone.com/reports/603764",
                        name="Upserve — DOM XSS via postMessage",
                        note="$2500",
                    ),
                    Resource(
                        url="https://hackerone.com/reports/900619",
                        name="PlayStation — Reflected XSS from opener",
                        note="$1000",
                    ),
                    Resource(
                        url="https://hackerone.com/reports/2371019",
                        name="Automattic — DOM XSS via postMessages",
                        note="",
                    ),
                ],
                why="Spans 4 distinct failure modes across major brands.",
            ),
        ],
    )


def test_html_renders_every_resource_url_in_bundle():
    plan = _plan_with_resources_bundle()
    html = render_plan_email(plan)
    for r in plan.tasks[0].resources:
        assert r.url in html


def test_html_renders_resource_names_and_notes():
    plan = _plan_with_resources_bundle()
    html = render_plan_email(plan)
    assert "Shopify — Structured-clone abuse" in html
    assert "Upserve — DOM XSS via postMessage" in html
    # Notes appear with em-dash separator
    assert "$3000 — most severe" in html
    assert "$2500" in html


def test_html_shows_resources_count_label():
    plan = _plan_with_resources_bundle()
    html = render_plan_email(plan)
    # Bundle has 4 resources total — render ALL of them, not deduplicated
    assert "Resources (4)" in html


def test_html_skips_resources_block_when_only_primary_anchor():
    """If resources list is empty, no 'Resources (N)' block is rendered."""
    plan = _sample_plan()
    html = render_plan_email(plan)
    assert "Resources (" not in html


def test_html_renders_primary_twice_when_it_is_also_in_resources_list():
    """Primary URL listed in resources[0] appears in BOTH the anchor and the
    resources list — by design. Anchor is for quick navigation, list is for
    actionable consumption + per-resource notes."""
    plan = _plan_with_resources_bundle()
    html = render_plan_email(plan)
    primary = plan.tasks[0].primary_resource_url
    # Appears once as anchor href, once as resources[0] href
    assert html.count(f'href="{primary}"') == 2


def test_text_fallback_includes_every_resource_url():
    plan = _plan_with_resources_bundle()
    text = render_text_fallback(plan)
    for r in plan.tasks[0].resources:
        assert r.url in text


def test_text_fallback_includes_resource_notes():
    plan = _plan_with_resources_bundle()
    text = render_text_fallback(plan)
    assert "$3000 — most severe" in text


# ---------------------------------------------------------------------------
# Legacy field name compatibility
# ---------------------------------------------------------------------------


def test_old_resource_url_kwarg_still_works():
    """Constructor accepts old `resource_url` / `resource_name` kwargs."""
    t = Task(
        phase=Phase.LEARN,
        title="x",
        description="y",
        resource_url="https://example.com/legacy",
        resource_name="Legacy name",
    )
    assert t.primary_resource_url == "https://example.com/legacy"
    assert t.primary_resource_name == "Legacy name"
    assert t.resources == []


def test_primary_auto_derives_from_resources_when_unset():
    """If resources is set but primary_resource_url isn't, derive from [0]."""
    t = Task(
        phase=Phase.LEARN,
        title="x",
        description="y",
        resources=[
            {"url": "https://example.com/a", "name": "A"},
            {"url": "https://example.com/b", "name": "B"},
        ],
    )
    assert t.primary_resource_url == "https://example.com/a"
    assert t.primary_resource_name == "A"
    assert len(t.resources) == 2


# ---------------------------------------------------------------------------
# tools_section rendering (execute phase)
# ---------------------------------------------------------------------------


def _plan_with_tools_section() -> Plan:
    return Plan(
        bug_class_name="postmessage",
        phase=Phase.EXECUTE,
        date="2026-06-06",
        target_hours=3.0,
        rationale="Execute phase — hunt postMessage on real targets.",
        tasks=[
            Task(
                bug_class_name="postmessage",
                phase=Phase.EXECUTE,
                title="Hunt postMessage on a live bug bounty program",
                description="Pick ONE program below. Recon + hunt.",
                task_type=TaskType.BUG_BOUNTY,
                priority=Priority.HIGH,
                estimated_hours=1.5,
                resources=[
                    Resource(
                        url="https://hackerone.com/shopify",
                        name="Shopify",
                        note="$3000 bounty history",
                    ),
                ],
            ),
        ],
        tools_section=[
            Resource(
                url="https://github.com/thisis0xczar/FrogPost",
                name="FrogPost",
                note="Chrome extension — runtime postMessage interception",
            ),
            Resource(
                url="https://portswigger.net/burp/extensions/dom-invader",
                name="DOM Invader (Burp)",
                note="Burp extension — auto-detects postMessage sinks",
            ),
        ],
    )


def test_html_renders_tools_section_block_when_non_empty():
    plan = _plan_with_tools_section()
    html_out = render_plan_email(plan)
    assert "Tools for Hunting (2)" in html_out
    assert "FrogPost" in html_out
    assert "DOM Invader (Burp)" in html_out
    assert "https://github.com/thisis0xczar/FrogPost" in html_out


def test_html_omits_tools_section_when_empty():
    plan = _plan_with_resources_bundle()  # no tools_section set
    html_out = render_plan_email(plan)
    assert "Tools for Hunting" not in html_out


def test_html_renders_tool_notes():
    plan = _plan_with_tools_section()
    html_out = render_plan_email(plan)
    assert "Chrome extension — runtime postMessage interception" in html_out


def test_text_fallback_includes_tools_section():
    plan = _plan_with_tools_section()
    text = render_text_fallback(plan)
    assert "Tools for Hunting (2):" in text
    for tool in plan.tools_section:
        assert tool.url in text
        assert tool.name in text


def test_text_fallback_omits_tools_section_when_empty():
    plan = _plan_with_resources_bundle()  # no tools_section set
    text = render_text_fallback(plan)
    assert "Tools for Hunting" not in text
