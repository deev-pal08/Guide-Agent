"""Planner agent — generates the daily plan after the user confirms a direction.

Workflow:
  1. Load the phase's SKILL.md body and the intelligent_research SKILL.md body
  2. Build user context (bug class, progress, consumed resources, mastered classes,
     user notes, recent feedback)
  3. Run a multi-turn tool loop:
       - newsletter_query, search_consumed_resources, web_search (parallel)
       - verify_url on candidates
       - read_skill_reference if model needs methodology depth
  4. Final turn: model emits the Plan JSON
  5. We persist the plan + tasks, mark resources consumed, return Plan
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from guide_agent.agent.base import BaseBrain, GuideParseError
from guide_agent.agent.tools import (
    BLOG_FEED_SEARCH_TOOL_DEF,
    CODEREVIEWLAB_SEARCH_TOOL_DEF,
    CTFSEARCH_SEARCH_TOOL_DEF,
    CTFTIME_EVENTS_TOOL_DEF,
    GITHUB_REPO_SEARCH_TOOL_DEF,
    GITHUB_REPOS_BY_STARS_TOOL_DEF,
    HACKERONE_HACKTIVITY_SEARCH_TOOL_DEF,
    NEWSLETTER_QUERY_TOOL_DEF,
    PENTESTERLAND_SEARCH_TOOL_DEF,
    PREFETCHED_RESOURCE_SEARCH_TOOL_DEF,
    SEARCH_CONSUMED_TOOL_DEF,
    SITEMAP_SEARCH_TOOL_DEF,
    VERIFY_URL_TOOL_DEF,
    WEB_SEARCH_TOOL_DEF,
    Tools,
    serialize_tool_result,
)
from guide_agent.config import AppConfig
from guide_agent.models import Phase, Plan, ResearchMode, Resource, Task
from guide_agent.skills.loader import (
    READ_SKILL_REFERENCE_TOOL_DEF,
    SkillLoader,
)
from guide_agent.sources.hardcoded import render_hardcoded_pool
from guide_agent.sources.web import render_web_search_availability
from guide_agent.state.store import StateStore

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_TEMPLATE = """\
You are the Planner agent for the Guide — a hyper-specific security bug-class \
mastery tool. The user has just confirmed they want a {phase} session for \
bug class '{bug_class}'. Your job: generate ONE day's plan as JSON.

## ACTIVE SKILL (level 2 — full instructions)
{phase_skill_body}

## INTELLIGENT RESEARCH (cross-cutting workflow)
{intelligent_research_body}

## HARDCODED SOURCES (read-only context)
{hardcoded_pool}

{web_search_availability}

## YOUR TOOL BUDGET (max ~6 turns, batch aggressively)
- Turn 1: ALWAYS call `prefetched_resource_search(bug_class, bug_class_id)` \
FIRST. This is an instant SQLite query over already-fetched resources \
(Pentester Land + blog feeds + sitemaps + reddelexc archive). Pair it with \
`search_consumed_resources` for any URLs you already know exist.
- Turn 1-2 (LIVE FALLBACK — only if needed): if the prefetched search \
returned too few results for the user's target_hours, OR the user context \
contains `FRESH_FETCH=true`, fan out to live tools: newsletter_query + \
web_search + github_repo_search + hackerone_hacktivity_search + \
pentesterland_search + blog_feed_search + sitemap_search + ctfsearch_search \
(batch all in one turn).
- Turn 3: verify_url on the candidate URLs (batch all calls in one turn)
- Turn 4 (optional): read_skill_reference if you need deeper methodology
- Final turn: output the final Plan JSON

NEVER spread the same tool across multiple turns when you could batch — wastes \
tokens. NEVER skip the prefetched_resource_search call — the user has \
already paid the fetch cost; reusing that data is free. NEVER fabricate \
URLs — every URL in `primary_resource_url` or `resources` MUST come from \
prefetched_resource_search, web_search, github_repo_search, \
hackerone_hacktivity_search, pentesterland_search, blog_feed_search, \
sitemap_search, ctfsearch_search, newsletter_query, or a hardcoded source \
you can name.

## github_repo_search — USE for GitHub-hosted hardcoded sources
Search engines (Brave/Tavily/Exa) rarely index GitHub subdirectory READMEs. \
When a hardcoded source is `github.com/<owner>/<repo>` (e.g. PayloadsAllTheThings, \
crApi, Juice Shop, *-Goat repos), bare `site:` search returns only the repo \
homepage and you miss the bug-class-specific content.

WHENEVER you see a hardcoded source URL whose host is github.com, prefer calling \
`github_repo_search(repo_url=..., bug_class=...)` over web_search for THAT URL. \
The tool walks the repo's file tree and returns ranked paths matching the bug \
class (top-level dirs + README.md prioritised). For example, calling it on \
PayloadsAllTheThings with bug_class='xss' returns `XSS Injection/README.md` \
and related files — content you'd otherwise miss completely. \
Batch these calls with your web_search calls in the same turn.

## hackerone_hacktivity_search — USE for the examples phase
HackerOne hacktivity has 2000+ disclosed XSS reports, 500+ SSRF, etc. — but \
Brave `site:hackerone.com/reports` only surfaces ~10 reports. The dedicated \
tool queries HackerOne's GraphQL search directly with structured severity + \
bounty filters, then sorts by severity DESC then bounty DESC so the \
highest-impact paid reports come first.

WHENEVER the phase is `examples` and you need disclosed real-world reports for \
a bug class, call `hackerone_hacktivity_search(bug_class='<class>', \
min_severity='high', min_bounty=0, limit=15)` BEFORE falling back to web_search. \
For very common bug classes (XSS, SSRF) you can raise `min_bounty=500` to filter \
out noise. Returns structured `[{url, title, team_handle, severity, bounty, \
cwe, votes, ...}]` — use the `url` as the resource URL and surface severity + \
bounty + CWE in the resource `note` field so the user knows the impact at a \
glance. Batch with your other discovery calls in the same turn.

### Drain-in-waves pattern (high-volume classes)
1. First run: `min_severity='high', min_bounty=0, limit=20` — top tier.
2. ALWAYS pass returned URLs through `search_consumed_resources` to drop \
ones the user has already drained.
3. If too many dupes vs the consumed ledger, re-run with \
`exclude_report_ids=[<ids>]` (bare numeric IDs) to skip them server-side, OR \
lower the bar (`min_severity='medium'`) to unlock the next tier, OR raise \
`limit` (capped at 200).
4. For technique classes (postmessage, prototype pollution) the universe is \
small (~20-50 total) — drain in one or two runs, don't keep firing.

## pentesterland_search — USE for the examples phase (complements H1)
Pentester Land curates 6400+ bug-bounty writeups from Medium / personal blogs / \
Sonar / includesecurity / hashnode / infosecwriteups — sources NOT on HackerOne. \
The data is a structured JSON (~1100 XSS, ~280 SSRF, ~33 postMessage entries) \
with direct external URLs, titles, authors, programs, bug tags, bounty, dates.

WHENEVER the phase is `examples`, call BOTH \
`hackerone_hacktivity_search` AND `pentesterland_search` for the same bug \
class in your first discovery turn — they cover different universes (H1 \
disclosed reports vs blog/Medium writeups). Default usage: \
`pentesterland_search(bug_class='<class>', min_bounty=0, limit=15)`. \
For high-volume classes use `min_bounty=500` to filter to paid findings. \
Pass `exclude_urls=[<urls>]` on follow-up runs to skip consumed writeups.

## blog_feed_search — USE for research-blog hardcoded sources
Brave `site:` searches cap at ~10 results, but research blogs have far more \
posts (Orange Tsai = 100, Embrace The Red = 224, PentesterLab = 186, \
PortSwigger Research = 40+). When a hardcoded source has a `feed_url` \
configured (look for it in the Sources block), prefer \
`blog_feed_search(feed_url=..., bug_class=...)` over `site:` web_search for \
THAT blog — it fetches the full feed and substring-matches against entry \
title + summary, so you get every relevant post, not just the 10 Brave \
indexed. Use '|' to OR synonyms in bug_class: \
`'postmessage|cross-window|window.opener'`. Batch with your other discovery \
calls in the same turn.

## sitemap_search — USE for blogs with NO feed but a sitemap
Some sites (e.g. Sonar Research Blog) have no RSS/Atom feed but expose a \
sitemap.xml with all blog posts (538 Sonar posts vs 10 via Brave). When a \
hardcoded source has a `sitemap_url` configured, call \
`sitemap_search(sitemap_url=..., bug_class=..., url_prefix=<blog root>)`. \
Match is URL-slug only (lossier than feed body matching), so use generous \
OR synonyms: `'xss|cross-site'`, `'rce|code-execution|remote-code'`. The \
`url_prefix` filter is critical — without it, sitemap_search returns \
unrelated product/translated/marketing URLs alongside blog posts.

### feed_url + sitemap_url both present (e.g. PortSwigger, Intigriti)
Sources with both endpoints are fully covered by the prefetch fan-out — \
both `blog_feed_search` and `sitemap_search` fire during population, \
results dedup by URL. You don't need to choose; just query the DB and \
the union of both is already there.

## ctfsearch_search — USE for the examples phase (CTF complement)
CTFsearch indexes 35,800+ CTF writeups (TryHackMe / HackTheBox / OffSec / \
general CTF) with full-text search across title + content. CTF writeups \
often have MORE technical depth than terse bug-bounty reports (full \
exploitation chains, step-by-step payloads). Use ALONGSIDE \
hackerone_hacktivity_search + pentesterland_search to cover three \
distinct universes: H1 disclosed reports, blog writeups, and CTF \
walkthroughs. Default: `ctfsearch_search(bug_class='<class>', limit=15)`.

## AMBITION RULE (HARD)
The user explicitly wants ambitious depth-drilling tasks, NOT micro-tasks.
ONE task = drain an entire topic or batch many related resources together.
Bad: "Read HackTricks postMessage page (0.5h)".
Good: "Drain ALL of HackTricks postMessage + OWASP postMessage cheat sheet + \
PortSwigger postMessage theory pages — single sitting (3h)".

If a single resource would take less than 20 minutes, you MUST batch it with \
related resources into one comprehensive task. Aim for 1-3 substantive tasks \
totaling roughly the target_hours value (going up to 1.3x is fine).

## TASK-TYPE-BY-PHASE (HARD MAPPING)
- learn → read, course, research (NO labs)
- examples → read, research (NO labs)
- practice → lab, ctf, code_review (NO theory reading)
- execute → bug_bounty, build, write
- research → research, write

## FINAL OUTPUT — JSON ONLY, NO MARKDOWN FENCE
{{
  "bug_class": "{bug_class}",
  "phase": "{phase}",
  "research_mode": null,
  "date": "{date}",
  "target_hours": {target_hours},
  "rationale": "1-3 sentences: why this plan, tied to user state",
  "tasks": [
    {{
      "title": "Comprehensive depth-drilling task title",
      "description": "2-4 sentences: what to do, in what order, what to focus on. DO NOT cram URLs into prose — put them in the `resources` array.",
      "task_type": "read|course|research|lab|ctf|code_review|bug_bounty|build|write",
      "priority": "critical|high|medium|low",
      "estimated_hours": 2.5,
      "primary_resource_url": "https://verified-anchor-url",
      "primary_resource_name": "Page title of the primary URL",
      "resources": [
        {{
          "url": "https://verified-url-1",
          "name": "Display name from verify_url",
          "note": "One-line context: '$3000 bounty', 'most severe', etc."
        }},
        {{"url": "https://verified-url-2", "name": "...", "note": "..."}}
      ],
      "why": "Why THIS bundle of resources — what makes it the right call"
    }}
  ],
  "tools_section": [
    {{
      "url": "https://github.com/<repo>",
      "name": "Tool name — one-phrase descriptor",
      "note": "What the tool does, key features, limitations"
    }}
  ]
}}

## tools_section — REQUIRED for execute phase, EMPTY ([]) for all other phases
The `tools_section` field is a SEPARATE list of openly-available tools the user can DOWNLOAD and USE for hunting (NOT tools to build). Populate with 5-10 entries in the execute phase. For learn/examples/practice/research phases, leave it as `[]`.

## resources LIST — MANDATORY when a task has 2+ URLs
Whenever your task references more than one URL (which is almost always — \
the AMBITION RULE says batch many resources into one task), every URL MUST \
appear as its own entry in the `resources` array. Each entry needs:
  - `url`: the verified URL (came from web_search + verify_url)
  - `name`: the page title from verify_url (or descriptor if not retrievable)
  - `note`: ONE LINE of context — bounty, severity, what makes it distinctive
NEVER name URLs inline in `description` and leave them out of `resources`. \
The renderer ONLY shows what's in `resources` as clickable links — anything \
in prose is unclickable and forces the user to search for it manually.

`primary_resource_url` is the anchor — typically the first resource OR an \
index page (e.g. TOPXSS.md) when the bundle is many disclosures. If the task \
has only 1 URL, set primary_* and leave resources as `[]` (or repeat the one \
URL in resources for consistency — either is fine).

Use null for research_mode unless phase == research. The "tasks" array MUST \
have at least 1 entry and at most 5.
"""


class PlannerBrain(BaseBrain):
    brain_name = "planner"

    MAX_ITERATIONS = 8
    PACING_SECONDS = 15

    def __init__(
        self,
        config: AppConfig,
        state: StateStore,
        skill_loader: SkillLoader,
    ):
        super().__init__(config, state)
        self.skill_loader = skill_loader
        self.tools = Tools(config, state, skill_loader)

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------

    def plan(
        self,
        bug_class_id: int,
        bug_class_name: str,
        phase: Phase,
        target_hours: float,
        date: str | None = None,
        research_mode: ResearchMode | None = None,
        skill_override: str | None = None,
        fresh_fetch: bool = False,
    ) -> Plan:
        """Generate, persist, and return a Plan for the given bug class + phase.

        skill_override lets the researcher reuse this loop with the 'research'
        skill loaded explicitly.

        fresh_fetch=True signals the planner to bypass prefetched DB and run
        live fetchers (--fresh CLI flag).
        """
        date = date or datetime.now(UTC).strftime("%Y-%m-%d")
        skill_name = skill_override or phase.value
        phase_skill = self.skill_loader.load(skill_name)
        ir_skill = self.skill_loader.load("intelligent_research")

        system = SYSTEM_PROMPT_TEMPLATE.format(
            bug_class=bug_class_name,
            phase=phase.value,
            phase_skill_body=phase_skill.body,
            intelligent_research_body=ir_skill.body,
            hardcoded_pool=render_hardcoded_pool(
                self.config.sources, phase.value, bug_class_name,
            ) or "(no hardcoded pool for this phase — discovery only)",
            web_search_availability=render_web_search_availability(self.config.search),
            date=date,
            target_hours=target_hours,
        )

        user_msg = self._build_user_context(
            bug_class_id=bug_class_id,
            bug_class_name=bug_class_name,
            phase=phase,
            target_hours=target_hours,
            date=date,
            fresh_fetch=fresh_fetch,
        )

        plan_dict = self._run_loop(system=system, user_message=user_msg)

        # Normalise + persist
        plan = self._materialise_plan(
            plan_dict=plan_dict,
            bug_class_id=bug_class_id,
            bug_class_name=bug_class_name,
            phase=phase,
            research_mode=research_mode,
            date=date,
            target_hours=target_hours,
        )
        return plan

    # ------------------------------------------------------------------
    # Context builders
    # ------------------------------------------------------------------

    def _build_user_context(
        self,
        bug_class_id: int,
        bug_class_name: str,
        phase: Phase,
        target_hours: float,
        date: str,
        fresh_fetch: bool = False,
    ) -> str:
        progress = self.state.get_all_phase_progress(bug_class_id)
        consumed_count = self.state.get_consumed_count(bug_class_id)
        recent_completed = self.state.get_recent_completed_tasks(
            bug_class_id, limit=15,
        )
        recent_feedback = self.state.get_recent_feedback(bug_class_id, limit=10)
        user_notes = self.state.get_user_notes(limit=15)
        mastered = self.state.get_all_mastered()

        sections = [
            f"## REQUEST\nbug_class={bug_class_name}, bug_class_id={bug_class_id}, "
            f"phase={phase.value}, target_hours={target_hours}, date={date}, "
            f"FRESH_FETCH={'true' if fresh_fetch else 'false'}",
        ]

        # Phase progress
        progress_lines = [
            f"- {p['phase']}: {p['resources_consumed']} consumed, "
            f"last_run={(p.get('last_run') or 'never')[:10]}"
            for p in progress
        ] or ["- (no prior phase progress)"]
        sections.append("## PHASE PROGRESS\n" + "\n".join(progress_lines))

        sections.append(
            f"## CONSUMED RESOURCES TOTAL\n"
            f"{consumed_count} URLs already covered for this bug class. "
            f"Use search_consumed_resources before assigning to avoid repeats."
        )

        if mastered:
            sections.append(
                "## MASTERED BUG CLASSES (cross-reference — user already knows)\n"
                + ", ".join(m["name"] for m in mastered)
            )

        if user_notes:
            lines = ["## USER NOTES (persistent, treat as ground truth)"]
            for n in user_notes[:15]:
                date_str = (n.get("received_at") or "")[:10]
                lines.append(f"- ({date_str}) {n['note']}")
            sections.append("\n".join(lines))

        if recent_completed:
            lines = ["## RECENTLY COMPLETED TASKS for this bug class"]
            for t in recent_completed[:15]:
                hours = t.get("actual_hours") or t.get("estimated_hours")
                lines.append(
                    f"- [{t['phase']}] {t['title']} ({hours}h) — "
                    f"{(t.get('learnings') or '')[:120]}"
                )
            sections.append("\n".join(lines))

        if recent_feedback:
            lines = ["## RECENT FEEDBACK NOTES"]
            for f in recent_feedback[:10]:
                hours = f.get("actual_hours")
                hours_str = f" [{hours}h]" if hours is not None else ""
                content = (f.get("notes") or f.get("learnings") or "").strip()
                lines.append(
                    f"- [{f.get('phase', '')}]{hours_str} \"{content}\" "
                    f"(task: {f.get('title', '')})"
                )
            sections.append("\n".join(lines))

        sections.append(
            "## INSTRUCTION\n"
            "Run the tool loop now. Batch queries. Verify URLs. Output the "
            "final JSON plan."
        )
        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Tool loop
    # ------------------------------------------------------------------

    def _run_loop(self, system: str, user_message: str) -> dict[str, Any]:
        model = self.config.llm.planner_model
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_message},
        ]
        tool_defs = [
            WEB_SEARCH_TOOL_DEF,
            VERIFY_URL_TOOL_DEF,
            NEWSLETTER_QUERY_TOOL_DEF,
            SEARCH_CONSUMED_TOOL_DEF,
            PREFETCHED_RESOURCE_SEARCH_TOOL_DEF,
            GITHUB_REPO_SEARCH_TOOL_DEF,
            GITHUB_REPOS_BY_STARS_TOOL_DEF,
            HACKERONE_HACKTIVITY_SEARCH_TOOL_DEF,
            PENTESTERLAND_SEARCH_TOOL_DEF,
            CODEREVIEWLAB_SEARCH_TOOL_DEF,
            BLOG_FEED_SEARCH_TOOL_DEF,
            SITEMAP_SEARCH_TOOL_DEF,
            CTFSEARCH_SEARCH_TOOL_DEF,
            CTFTIME_EVENTS_TOOL_DEF,
            READ_SKILL_REFERENCE_TOOL_DEF,
        ]
        last_call = 0.0
        response = None

        for iteration in range(self.MAX_ITERATIONS):
            # Pacing
            elapsed = time.monotonic() - last_call
            if last_call and elapsed < self.PACING_SECONDS:
                time.sleep(self.PACING_SECONDS - elapsed)
            last_call = time.monotonic()

            # On the final iteration, drop tools to force JSON emission
            tools_for_turn = (
                tool_defs if iteration < self.MAX_ITERATIONS - 1 else None
            )
            if iteration == self.MAX_ITERATIONS - 1:
                messages.append({
                    "role": "user",
                    "content": (
                        "Your tool budget is exhausted. Output the final Plan "
                        "JSON now using whatever you have. No more tool calls."
                    ),
                })

            # The Anthropic API rejects `tools=None` — must omit the field
            # entirely on turns where tools aren't offered.
            call_kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": self.config.llm.max_tokens,
                "system": system,
                "messages": messages,
            }
            if tools_for_turn is not None:
                call_kwargs["tools"] = tools_for_turn

            response = self._call_claude(**call_kwargs)
            self._log_usage(response, model)

            if response.stop_reason == "end_turn":
                text = next(
                    (b.text for b in response.content if b.type == "text"),
                    "",
                )
                return self._parse_json_response(text)

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = self.tools.dispatch(block.name, dict(block.input))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": serialize_tool_result(result),
                        })
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                continue

            # Unknown stop reason — bail with whatever text we have
            text = next(
                (b.text for b in response.content if hasattr(b, "text")),
                "",
            )
            return self._parse_json_response(text)

        # Should be unreachable given the forced final-turn logic
        if response is None:
            raise GuideParseError("planner loop produced no response")
        text = next(
            (b.text for b in response.content if hasattr(b, "text")),
            "{}",
        )
        return self._parse_json_response(text)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _materialise_plan(
        self,
        plan_dict: dict[str, Any],
        bug_class_id: int,
        bug_class_name: str,
        phase: Phase,
        research_mode: ResearchMode | None,
        date: str,
        target_hours: float,
    ) -> Plan:
        plan_dict.setdefault("bug_class", bug_class_name)
        plan_dict.setdefault("phase", phase.value)
        plan_dict.setdefault("date", date)
        plan_dict.setdefault("target_hours", target_hours)
        plan_dict.setdefault("rationale", "")
        plan_dict.setdefault("tasks", [])
        plan_dict.setdefault("tools_section", [])

        if research_mode is not None:
            plan_dict["research_mode"] = research_mode.value

        # Validate tools_section entries (drop any malformed ones)
        tools_section_data = plan_dict.get("tools_section", []) or []
        validated_tools: list[Resource] = []
        for t_dict in tools_section_data:
            try:
                validated_tools.append(Resource.model_validate(t_dict))
            except Exception as e:
                logger.warning("Skipping invalid tool entry: %s — %s", t_dict, e)

        # Build the Pydantic Plan to validate shape
        plan = Plan(
            bug_class_id=bug_class_id,
            bug_class_name=bug_class_name,
            phase=phase,
            research_mode=research_mode,
            date=date,
            target_hours=target_hours,
            rationale=plan_dict.get("rationale", ""),
            tasks=[],
            tools_section=validated_tools,
            confirmed_at=datetime.now(UTC),
        )
        for t_dict in plan_dict.get("tasks", []):
            try:
                task = Task.model_validate({
                    **t_dict,
                    "bug_class_id": bug_class_id,
                    "bug_class_name": bug_class_name,
                    "phase": phase,
                })
            except Exception as e:
                logger.warning("Skipping invalid task: %s — %s", t_dict, e)
                continue
            plan.tasks.append(task)

        # Persist the plan + tasks
        plan_id = self.state.create_plan(
            bug_class_id=bug_class_id,
            phase=phase.value,
            date=date,
            target_hours=target_hours,
            plan_dict=plan_dict,
            rationale=plan.rationale,
            research_mode=research_mode.value if research_mode else None,
            status="confirmed",
            tools_section=[t.model_dump() for t in validated_tools],
        )
        plan.id = plan_id

        for task in plan.tasks:
            task_id = self.state.create_task(
                plan_id=plan_id,
                bug_class_id=bug_class_id,
                phase=phase.value,
                title=task.title,
                description=task.description,
                task_type=task.task_type.value,
                priority=task.priority.value,
                estimated_hours=task.estimated_hours,
                resource_url=task.primary_resource_url,
                resource_name=task.primary_resource_name,
                resources=[r.model_dump() for r in task.resources],
                why=task.why,
            )
            task.id = task_id

            # Mark EVERY URL consumed so we never re-suggest any of them.
            # Includes the primary anchor plus every resource in the bundle,
            # deduplicated.
            consumed_urls: set[str] = set()
            if task.primary_resource_url:
                consumed_urls.add(task.primary_resource_url)
                self.state.mark_consumed(
                    bug_class_id=bug_class_id,
                    url=task.primary_resource_url,
                    phase=phase.value,
                    title=task.primary_resource_name or task.title,
                    source_type="web",
                )
            for res in task.resources:
                if res.url and res.url not in consumed_urls:
                    consumed_urls.add(res.url)
                    self.state.mark_consumed(
                        bug_class_id=bug_class_id,
                        url=res.url,
                        phase=phase.value,
                        title=res.name or task.title,
                        source_type="web",
                    )

        # Mark tools_section URLs as consumed too (don't re-suggest tools)
        tool_consumed: set[str] = set()
        for tool in plan.tools_section:
            if tool.url and tool.url not in tool_consumed:
                tool_consumed.add(tool.url)
                self.state.mark_consumed(
                    bug_class_id=bug_class_id,
                    url=tool.url,
                    phase=phase.value,
                    title=tool.name or "tool",
                    source_type="web",
                )

        # Bump phase progress
        self.state.bump_phase_progress(
            bug_class_id=bug_class_id,
            phase=phase.value,
            resources_added=len(plan.tasks) + len(plan.tools_section),
        )

        logger.info(
            "Plan persisted: id=%d, bug_class=%s, phase=%s, %d tasks",
            plan_id, bug_class_name, phase.value, len(plan.tasks),
        )
        return plan
