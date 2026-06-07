"""Click-based CLI for the Guide Agent.

Top-level entry: `guide`. Subcommands:
  guide <bug-class>                      — propose options (cheap, no tools)
  guide <bug-class> --learn              — skip propose, go to learn phase
  guide <bug-class> --examples
  guide <bug-class> --practice
  guide <bug-class> --execute
  guide <bug-class> --research
  guide <bug-class> --done               — mark mastered
  guide <bug-class> --resume             — un-master
  guide status                           — all bug classes + phases
  guide complete <task_id>               — mark task done via CLI
  guide skip <task_id> -r "reason"
  guide process-replies                  — parse email replies, update state
  guide init                             — first-run wizard
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from guide_agent.agent.conversation import (
    ConfirmationDecision,
    ConversationBrain,
    parse_confirmation,
)
from guide_agent.agent.feedback import FeedbackParser, apply_feedback
from guide_agent.agent.planner import PlannerBrain
from guide_agent.agent.researcher import ResearcherBrain
from guide_agent.config import AppConfig, load_config
from guide_agent.email.receiver import EmailReceiver
from guide_agent.email.sender import EmailSender
from guide_agent.models import Phase, ResearchMode
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


CONFIG_PATH = Path("config.yaml")


def _ctx_objects(
    config_path: Path = CONFIG_PATH,
) -> tuple[AppConfig, StateStore, SkillLoader]:
    config = load_config(config_path)
    state = StateStore(config.state_dir)
    loader = SkillLoader(config.skills_dir)
    return config, state, loader


# ---------------------------------------------------------------------------
# Top-level group — supports both `guide <bug>` and `guide <subcommand>`
# ---------------------------------------------------------------------------


class DefaultGroup(click.Group):
    """Click group where a bug-class name (any unknown command) routes to `drill`."""

    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            # Unknown subcommand — treat first arg as bug class name
            return "drill", drill, args


@click.group(cls=DefaultGroup)
@click.version_option(version="0.1.0", prog_name="guide")
def cli() -> None:
    """Hyper-specific bug-class mastery agent."""


# ---------------------------------------------------------------------------
# drill — the main entry point for working on a bug class
# ---------------------------------------------------------------------------


@cli.command(hidden=True)
@click.argument("bug_class", required=True)
@click.option("--learn", "phase_flag", flag_value="learn", default=None)
@click.option("--examples", "phase_flag", flag_value="examples")
@click.option("--practice", "phase_flag", flag_value="practice")
@click.option("--execute", "phase_flag", flag_value="execute")
@click.option("--research", "phase_flag", flag_value="research")
@click.option("--done", "mark_done", is_flag=True, help="Mark as mastered")
@click.option("--resume", "resume_flag", is_flag=True, help="Un-master to revisit")
@click.option(
    "--research-mode",
    type=click.Choice(["gap_analysis", "bypass_hunting", "draft_generation"]),
    default=None,
    help="Research sub-mode (only with --research)",
)
@click.option(
    "--hours",
    type=float,
    default=None,
    help="Target hours for the plan (default: 3.0, or prompt during confirmation)",
)
@click.option("--no-email", is_flag=True, help="Skip sending the plan email")
@click.option(
    "--fresh", "fresh_fetch", is_flag=True,
    help="Bypass prefetched DB and force the planner to run live fetchers.",
)
def drill(
    bug_class: str,
    phase_flag: str | None,
    mark_done: bool,
    resume_flag: bool,
    research_mode: str | None,
    hours: float | None,
    no_email: bool,
    fresh_fetch: bool,
) -> None:
    """Work on a bug class — the main entry point."""
    config, state, loader = _ctx_objects()

    # --done and --resume shortcut: no LLM calls
    if mark_done or resume_flag:
        bc = state.get_bug_class(bug_class)
        if not bc:
            click.echo(f"Bug class '{bug_class}' not found. Nothing to update.")
            sys.exit(1)
        if mark_done:
            state.mark_mastered(bc["id"])
            click.echo(f"Marked '{bc['name']}' as mastered.")
        else:
            state.mark_in_progress(bc["id"])
            click.echo(f"Marked '{bc['name']}' as in_progress (resumed).")
        return

    # Make sure the bug class exists
    bc_id = state.upsert_bug_class(bug_class)
    bc = state.get_bug_class(bc_id)
    assert bc is not None
    click.echo(f"\nGuide — {bc['name']}\n" + "=" * 60)

    convo = ConversationBrain(config, state, loader)

    forced_phase = Phase(phase_flag) if phase_flag else None

    # Conversation loop
    iteration_history: list[str] = []
    proposal = convo.propose(
        bug_class_name=bc["name"],
        force_phase=forced_phase,
    )

    decision: ConfirmationDecision | None = None
    while decision is None or decision.action == "iterate":
        _print_proposal(proposal)
        if no_email:
            click.echo("(--no-email set — plan will print to terminal only)")
        reply = click.prompt(
            "\nYour reply (number, free text, or 'q' to quit)",
            type=str, default="", show_default=False,
        ).strip()
        if not reply:
            click.echo("Empty reply — aborting.")
            return
        decision = parse_confirmation(convo, proposal, reply)
        if decision.action == "abort":
            click.echo("Aborted.")
            return
        if decision.action == "iterate":
            click.echo(f"\nIterating — feedback: {decision.iteration_feedback}")
            iteration_history.append(f"User feedback: {decision.iteration_feedback}")
            proposal = convo.propose(
                bug_class_name=bc["name"],
                iteration_history=iteration_history,
                force_phase=forced_phase,
            )

    # Confirmation reached — fire the planner
    assert decision.action == "confirm" and decision.phase is not None
    target_hours = hours if hours is not None else decision.target_hours
    phase = decision.phase

    # Resolve research_mode: --research-mode flag wins, else use conversation decision
    mode_override: ResearchMode | None = None
    if research_mode:
        mode_override = ResearchMode(research_mode)
    elif decision.research_mode:
        mode_override = decision.research_mode
    elif phase == Phase.RESEARCH:
        mode_override = ResearchMode.GAP_ANALYSIS  # sensible default

    click.echo(
        f"\nConfirmed: {phase.value} phase, target {target_hours}h. "
        f"Firing planner..."
    )

    # Auto-trigger: populate the DB for this bug class if it's empty for the
    # user, or if --fresh was passed. Skipped for the 'research' phase (which
    # is discovery-only and doesn't use the prefetched-resources path).
    if phase != Phase.RESEARCH:
        from guide_agent.agent.expansion import (
            build_search_query,
            ensure_expansion,
        )
        from guide_agent.agent.tools import Tools
        from guide_agent.refresh import populate_if_empty

        tools = Tools(config, state, loader)
        # Pay one ~$0.0003 Haiku call (once per class lifetime) to get a
        # synonym list — boosts recall for technique classes like postmessage
        # / request smuggling where the literal name isn't in titles.
        terms = ensure_expansion(config, state, loader, bc["name"])
        expanded_query = build_search_query(terms)
        if len(terms) > 1:
            click.echo(
                f"Search expansion for {bc['name']}: {len(terms)} terms "
                f"({', '.join(terms[1:6])}{'...' if len(terms) > 6 else ''})"
            )

        did_fetch, fetch_report = populate_if_empty(
            config=config,
            state=state,
            tools=tools,
            bug_class=bc["name"],
            bug_class_id=bc["id"],
            phase=phase.value,
            force=fresh_fetch,
            expanded_query=expanded_query,
        )
        if did_fetch:
            click.echo("\nPopulating local DB for this bug class:")
            for sid, counts in fetch_report.items():
                click.echo(
                    f"  {sid:35s}  fetched={counts.get('fetched', 0):>4d}  "
                    f"inserted={counts.get('inserted', 0):>4d}  "
                    f"tagged={counts.get('tagged', 0):>4d}"
                )
            total = state.unread_count_for_bug_class(bc["name"], bc["id"])
            click.echo(f"  Total unread for {bc['name']}: {total}")
        else:
            unread = state.unread_count_for_bug_class(bc["name"], bc["id"])
            click.echo(
                f"DB has {unread} unread resources for {bc['name']} — using cache.",
            )

    try:
        if phase == Phase.RESEARCH:
            researcher = ResearcherBrain(config, state, loader)
            plan = researcher.research(
                bug_class_id=bc["id"],
                bug_class_name=bc["name"],
                research_mode=mode_override or ResearchMode.GAP_ANALYSIS,
                target_hours=target_hours,
                fresh_fetch=fresh_fetch,
            )
        else:
            planner = PlannerBrain(config, state, loader)
            plan = planner.plan(
                bug_class_id=bc["id"],
                bug_class_name=bc["name"],
                phase=phase,
                target_hours=target_hours,
                research_mode=mode_override,
                fresh_fetch=fresh_fetch,
            )
    except Exception as e:
        logger.exception("Plan generation failed")
        click.echo(f"\nPlan generation failed: {e}")
        if not no_email:
            sender = EmailSender(config.email)
            sender.send_failure_notification(str(e), bc["name"])
        sys.exit(1)

    click.echo(f"\nPlan persisted (id={plan.id}) with {len(plan.tasks)} tasks.")

    if no_email:
        _print_plan(plan)
        return

    sender = EmailSender(config.email)
    mid = sender.send_plan(plan)
    if mid:
        state.mark_plan_sent(plan.id or 0)
        click.echo(f"Plan email sent (message_id={mid}).")
    else:
        click.echo("Email not sent — printing to terminal instead.")
        _print_plan(plan)


# ---------------------------------------------------------------------------
# status — show all bug classes with phase progress
# ---------------------------------------------------------------------------


@cli.command()
def status() -> None:
    """Show all bug classes with phase progress + token usage."""
    config, state, _ = _ctx_objects()

    in_progress = state.get_all_in_progress()
    mastered = state.get_all_mastered()

    click.echo("\n=== IN PROGRESS ===\n")
    if not in_progress:
        click.echo("  (none yet — run `guide <bug-class>` to start)")
    for bc in in_progress:
        click.echo(f"  • {bc['name']}")
        progress = state.get_all_phase_progress(bc["id"])
        for p in progress:
            last = (p.get("last_run") or "never")[:10]
            click.echo(
                f"      {p['phase']:9s} — {p['resources_consumed']} consumed, "
                f"last {last}"
            )

    click.echo("\n=== MASTERED ===\n")
    if not mastered:
        click.echo("  (none yet)")
    for bc in mastered:
        when = (bc.get("mastered_at") or "")[:10]
        click.echo(f"  ✓ {bc['name']} (mastered {when})")

    # Token usage
    click.echo("\n=== TOKEN USAGE ===\n")
    for brain in ("conversation", "planner", "researcher", "feedback_parser"):
        raw = state.get_meta(f"tokens_{brain}")
        if raw:
            import json
            data = json.loads(raw)
            click.echo(
                f"  {brain:18s} in={data.get('input', 0):>8}  "
                f"out={data.get('output', 0):>8}  "
                f"calls={data.get('calls', 0):>4}"
            )


# ---------------------------------------------------------------------------
# complete / skip — mark tasks via CLI
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("task_id", type=int)
@click.option("--hours", "-h", type=float, default=None)
@click.option("--learnings", "-l", default="")
def complete(task_id: int, hours: float | None, learnings: str) -> None:
    """Mark a task as done via the CLI."""
    _, state, _ = _ctx_objects()
    task = state.get_task(task_id)
    if not task:
        click.echo(f"Task #{task_id} not found.")
        sys.exit(1)
    state.update_task_status(
        task_id=task_id, status="done",
        actual_hours=hours, learnings=learnings,
    )
    state.log_feedback(
        task_id=task_id, status="done",
        actual_hours=hours, learnings=learnings, source="cli",
    )
    click.echo(f"Marked task #{task_id} '{task['title']}' as done.")


@cli.command()
@click.argument("task_id", type=int)
@click.option("--reason", "-r", default="")
def skip(task_id: int, reason: str) -> None:
    """Skip a task via the CLI."""
    _, state, _ = _ctx_objects()
    task = state.get_task(task_id)
    if not task:
        click.echo(f"Task #{task_id} not found.")
        sys.exit(1)
    state.update_task_status(task_id=task_id, status="skipped", learnings=reason)
    state.log_feedback(
        task_id=task_id, status="skipped",
        notes=reason, source="cli",
    )
    click.echo(f"Skipped task #{task_id}.")


# ---------------------------------------------------------------------------
# process-replies — IMAP poll + feedback parse + state update
# ---------------------------------------------------------------------------


@cli.command("process-replies")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def process_replies(yes: bool) -> None:
    """Fetch email replies via IMAP, parse them, and update state."""
    config, state, _ = _ctx_objects()

    receiver = EmailReceiver(config.imap)
    replies = receiver.fetch_replies(from_address=config.email.from_address)
    if not replies:
        click.echo("No Guide reply emails found.")
        return

    combined_body = "\n\n---\n\n".join(r["body"] for r in replies)
    click.echo(f"Fetched {len(replies)} reply email(s).")

    # Find the most recent plan to scope task IDs
    # We use the latest plan globally — fine because all replies should be
    # to the most recent plan email.
    # NOTE: in a multi-bug-class workflow we may want smarter matching.
    latest_plan_row = state._conn.execute(
        "SELECT * FROM plans ORDER BY id DESC LIMIT 1",
    ).fetchone()
    if not latest_plan_row:
        click.echo("No plan found in state — nothing to apply feedback to.")
        return

    plan_tasks = state.get_tasks_for_plan(latest_plan_row["id"])
    parser = FeedbackParser(config, state)
    feedback = parser.parse(combined_body, task_count=len(plan_tasks))

    click.echo("\nParsed feedback:")
    click.echo("-" * 50)
    for entry in feedback.task_updates:
        title = (
            plan_tasks[entry.task_id - 1]["title"]
            if 0 < entry.task_id <= len(plan_tasks) else "?"
        )
        hours_str = f"{entry.actual_hours}h" if entry.actual_hours else "—"
        click.echo(
            f"  #{entry.task_id} {title}\n"
            f"     Status: {entry.status} | Hours: {hours_str}"
        )
        if entry.notes or entry.learnings:
            click.echo(f"     Notes: {entry.notes or entry.learnings}")
    if feedback.general_notes:
        click.echo(f"\n  General notes: {feedback.general_notes}")
    click.echo("-" * 50)

    if not yes and not click.confirm("Apply these updates?"):
        click.echo("Aborted.")
        return

    updated = apply_feedback(state, feedback, plan_tasks)
    click.echo(f"Applied {updated} task update(s).")


# ---------------------------------------------------------------------------
# init — first-run wizard
# ---------------------------------------------------------------------------


@cli.command("populate")
@click.argument("bug_class", required=True)
@click.option(
    "--phase", "phase_name",
    type=click.Choice(["learn", "examples", "practice", "execute"]),
    default="examples",
    help="Which phase's hardcoded sources to fan out across (default: examples)",
)
def populate(bug_class: str, phase_name: str) -> None:
    """Manually populate the prefetch DB for one bug class across all sources.

    Normally this fires automatically when you run `guide drill <class>` for
    a class with zero unread rows. Use this command to pre-warm a class
    without firing the planner (useful for batch overnight populates).
    """
    from guide_agent.agent.expansion import build_search_query, ensure_expansion
    from guide_agent.agent.tools import Tools
    from guide_agent.refresh import populate_for_bug_class

    config, state, loader = _ctx_objects()
    bc_id = state.upsert_bug_class(bug_class)
    bc = state.get_bug_class(bc_id)
    assert bc is not None

    terms = ensure_expansion(config, state, loader, bc["name"])
    expanded_query = build_search_query(terms)
    if len(terms) > 1:
        click.echo(
            f"Search expansion: {len(terms)} terms — "
            f"{', '.join(terms[1:6])}{'...' if len(terms) > 6 else ''}"
        )

    click.echo(
        f"Fanning out for {bc['name']} across {phase_name} sources..."
    )
    tools = Tools(config, state, loader)
    report = populate_for_bug_class(
        config=config, state=state, tools=tools,
        bug_class=bc["name"], phase=phase_name,
        expanded_query=expanded_query,
    )

    if not report:
        click.echo("No sources matched.")
        return

    click.echo(
        f"\n{'source':40s}  {'fetched':>8s}  {'inserted':>9s}  {'tagged':>7s}"
    )
    click.echo("-" * 70)
    for sid, counts in report.items():
        click.echo(
            f"{sid:40s}  {counts.get('fetched', 0):>8d}  "
            f"{counts.get('inserted', 0):>9d}  {counts.get('tagged', 0):>7d}"
        )
    total = state.tagged_count_for_bug_class(bc["name"])
    unread = state.unread_count_for_bug_class(bc["name"], bc["id"])
    click.echo(f"\nTotal tagged for {bc['name']}: {total}  (unread: {unread})")


@cli.command("expansions")
@click.argument("bug_class", required=True)
@click.option("--refresh", is_flag=True, help="Force regeneration via Haiku call.")
@click.option(
    "--edit", "edit_terms", default=None,
    help="Comma-separated list of terms — replaces the cached expansion.",
)
def expansions(bug_class: str, refresh: bool, edit_terms: str | None) -> None:
    """Show, refresh, or override the synonym expansion for a bug class."""
    from guide_agent.agent.expansion import ensure_expansion

    config, state, loader = _ctx_objects()
    bc_norm = bug_class.strip().lower()

    if edit_terms is not None:
        manual = [t.strip().lower() for t in edit_terms.split(",") if t.strip()]
        if bc_norm not in manual:
            manual.insert(0, bc_norm)
        state.set_expansion(bc_norm, manual)
        click.echo(f"Set expansion for {bc_norm}: {manual}")
        return

    if refresh:
        state.delete_expansion(bc_norm)
        click.echo(f"Cleared cached expansion for {bc_norm}.")

    terms = ensure_expansion(config, state, loader, bc_norm, force=refresh)
    click.echo(f"\nExpansion for {bc_norm} ({len(terms)} terms):")
    for t in terms:
        click.echo(f"  - {t}")


@cli.command()
def init() -> None:
    """First-run wizard: copy example config files and prompt for setup."""
    if not CONFIG_PATH.exists():
        example = Path("config.example.yaml")
        if example.exists():
            CONFIG_PATH.write_text(example.read_text())
            click.echo(f"✓ Created {CONFIG_PATH} from example. Edit it before running.")
        else:
            click.echo(f"⚠ {example} not found — create {CONFIG_PATH} manually.")

    env_path = Path(".env")
    if not env_path.exists():
        env_example = Path(".env.example")
        if env_example.exists():
            env_path.write_text(env_example.read_text())
            click.echo("✓ Created .env from example. Fill in API keys.")

    aboutme = Path("AboutMe.md")
    if not aboutme.exists():
        # Try to symlink from planner agent
        planner_aboutme = Path(
            "~/Desktop/personal/planner-agent/AboutMe.md"
        ).expanduser()
        if planner_aboutme.exists():
            try:
                aboutme.symlink_to(planner_aboutme)
                click.echo("✓ Symlinked AboutMe.md from planner-agent.")
            except OSError:
                aboutme.write_text(planner_aboutme.read_text())
                click.echo("✓ Copied AboutMe.md from planner-agent.")
        else:
            aboutme.write_text("# About Me\n\n(Write your profile here.)\n")
            click.echo("✓ Created blank AboutMe.md — fill it in.")

    click.echo("\nNext steps:")
    click.echo("  1. Edit config.yaml (email, IMAP, newsletter path)")
    click.echo("  2. Edit .env (API keys)")
    click.echo("  3. Run: guide <bug-class>")


# ---------------------------------------------------------------------------
# Pretty-printers
# ---------------------------------------------------------------------------


def _print_proposal(proposal) -> None:  # type: ignore[no-untyped-def]
    click.echo(f"\n{proposal.context_summary}\n")
    click.echo("Options:")
    for i, opt in enumerate(proposal.options, 1):
        phase_str = f"[{opt.phase.value}] " if opt.phase else "[free] "
        click.echo(f"  {i}. {phase_str}{opt.label}")
        click.echo(f"      {opt.description}")
        if opt.rationale:
            click.echo(click.style(f"      Why: {opt.rationale}", dim=True))
    click.echo(f"\n{proposal.free_text_invitation}")


def _print_plan(plan) -> None:  # type: ignore[no-untyped-def]
    click.echo(
        f"\n=== PLAN — {plan.bug_class_name} · {plan.phase.value.upper()} ==="
    )
    if plan.rationale:
        click.echo(f"\nWhy: {plan.rationale}")
    click.echo(f"\nTasks ({len(plan.tasks)}):")
    for i, t in enumerate(plan.tasks, 1):
        click.echo(f"\n  #{i} [{t.task_type.value}] {t.title} ({t.estimated_hours}h)")
        click.echo(f"      {t.description}")
        if t.primary_resource_url:
            anchor = t.primary_resource_name or t.primary_resource_url
            click.echo(click.style(f"      → {anchor}", fg="cyan"))
            click.echo(click.style(f"        {t.primary_resource_url}", dim=True))
        if t.resources:
            click.echo(click.style(
                f"      Resources ({len(t.resources)}):",
                fg="bright_black",
            ))
            for r in t.resources:
                name = r.name or r.url
                tail = f"  — {r.note}" if r.note else ""
                click.echo(click.style(f"        • {name}{tail}", fg="cyan"))
                click.echo(click.style(f"          {r.url}", dim=True))
        if t.why:
            click.echo(click.style(f"      Why: {t.why}", dim=True))

    if plan.tools_section:
        click.echo(click.style(
            f"\nTools for Hunting ({len(plan.tools_section)}):",
            fg="green", bold=True,
        ))
        for tool in plan.tools_section:
            name = tool.name or tool.url
            click.echo(click.style(f"  • {name}", fg="green"))
            if tool.note:
                click.echo(click.style(f"    {tool.note}", dim=True))
            click.echo(click.style(f"    {tool.url}", dim=True))


if __name__ == "__main__":
    cli()
