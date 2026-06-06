"""Core data models for the Guide Agent."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class Phase(StrEnum):
    """The 5 mastery phases — user-invoked, agent-suggested."""

    LEARN = "learn"
    EXAMPLES = "examples"
    PRACTICE = "practice"
    EXECUTE = "execute"
    RESEARCH = "research"


class BugClassStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    MASTERED = "mastered"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"


class TaskType(StrEnum):
    """Task types — strictly mapped per phase by skill prompts."""

    READ = "read"
    COURSE = "course"
    RESEARCH = "research"
    LAB = "lab"
    CTF = "ctf"
    CODE_REVIEW = "code_review"
    BUG_BOUNTY = "bug_bounty"
    BUILD = "build"
    WRITE = "write"
    OTHER = "other"


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SENT = "sent"
    SUPERSEDED = "superseded"


class ResearchMode(StrEnum):
    """Sub-modes available in the research phase."""

    GAP_ANALYSIS = "gap_analysis"
    BYPASS_HUNTING = "bypass_hunting"
    DRAFT_GENERATION = "draft_generation"


class SourceType(StrEnum):
    """Where a consumed resource came from."""

    HARDCODED = "hardcoded"
    NEWSLETTER = "newsletter"
    WEB = "web"


# ---------------------------------------------------------------------------
# Bug class hierarchy
# ---------------------------------------------------------------------------


class BugClass(BaseModel):
    """A bug class node — leaf or parent in the hierarchy."""

    id: int | None = None
    name: str = Field(..., description="Canonical name, e.g. 'postmessage'")
    parent_id: int | None = None
    is_leaf: bool = True
    status: BugClassStatus = BugClassStatus.IN_PROGRESS
    mastered_at: datetime | None = None
    created_at: datetime | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        return v.strip().lower() if isinstance(v, str) else v


class PhaseProgress(BaseModel):
    """Per-(bug_class, phase) progress ledger."""

    bug_class_id: int
    phase: Phase
    resources_consumed: int = 0
    last_run: datetime | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Conversation / proposal (pre-confirmation, cheap)
# ---------------------------------------------------------------------------


class ProposalOption(BaseModel):
    """A single option presented to the user in the propose phase."""

    label: str = Field(..., description="Short label for the option")
    phase: Phase | None = Field(
        None, description="The phase this option triggers (if applicable)"
    )
    description: str = Field(..., description="What this option will do")
    rationale: str = Field("", description="Why agent suggests this")


class Proposal(BaseModel):
    """Output of the conversation agent — options for the user to pick."""

    bug_class: str
    context_summary: str = Field(
        ...,
        description=(
            "One-paragraph human-readable summary of where the user stands "
            "with this bug class (resources consumed, phases run, mastery)"
        ),
    )
    options: list[ProposalOption] = Field(default_factory=list)
    free_text_invitation: str = Field(
        "Or describe what you want to do.",
        description="Prompt encouraging free-form override",
    )


# ---------------------------------------------------------------------------
# Plan + tasks (post-confirmation, the actual day's work)
# ---------------------------------------------------------------------------


class Resource(BaseModel):
    """A single concrete resource a task asks the user to consume.

    Tasks frequently bundle multiple resources (e.g. "read 8 disclosed
    reports"). Each one gets its own Resource entry so the renderer can
    show a clickable list instead of cramming URLs into prose.
    """

    url: str
    name: str = Field("", description="Display name — page title or descriptor")
    note: str = Field(
        "",
        description=(
            "One-line context about THIS resource within the batch — "
            "e.g. '$3000 bounty', 'most severe', 'covers regex bypasses'"
        ),
    )

    @field_validator("url", mode="before")
    @classmethod
    def coerce_url(cls, v: object) -> object:
        # Tolerate the model returning a string instead of a dict
        if isinstance(v, str):
            return v.strip()
        return v


class Task(BaseModel):
    """A single task in a day's plan."""

    id: int | None = None
    plan_id: int | None = None
    bug_class_id: int | None = None
    bug_class_name: str = ""
    phase: Phase
    title: str
    description: str
    task_type: TaskType = TaskType.READ
    priority: Priority = Priority.HIGH
    estimated_hours: float = 1.0

    # Primary anchor for the task — the entry-point URL the model considers
    # most central. Always set if there is at least one resource.
    primary_resource_url: str = ""
    primary_resource_name: str = ""

    # Full list of resources this task asks the user to consume. Renderer
    # treats this as the source of truth — primary_resource_url is just
    # the anchor / entry point for navigation.
    resources: list[Resource] = Field(default_factory=list)

    why: str = Field("", description="Why this specific resource over alternatives")
    status: TaskStatus = TaskStatus.PENDING
    actual_hours: float | None = None
    learnings: str = ""
    assigned_date: datetime | None = None
    completed_date: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise_legacy_fields(cls, data: object) -> object:
        """Accept old-shape input from LLM / persisted DB rows.

        Old shape: {resource_url, resource_name} as top-level fields.
        New shape: {primary_resource_url, primary_resource_name, resources}.

        If old keys are present and new keys are not, map them. Also auto-
        derive primary_* from resources[0] when the model emits a resources
        list but forgets to set the primary anchor.
        """
        if not isinstance(data, dict):
            return data
        # Map legacy field names
        if "resource_url" in data and "primary_resource_url" not in data:
            data["primary_resource_url"] = data.pop("resource_url")
        if "resource_name" in data and "primary_resource_name" not in data:
            data["primary_resource_name"] = data.pop("resource_name")
        # If resources list exists but primary not set, default to first
        resources = data.get("resources")
        if (
            resources
            and isinstance(resources, list)
            and not data.get("primary_resource_url")
        ):
            first = resources[0]
            if isinstance(first, dict):
                data["primary_resource_url"] = first.get("url", "")
                data["primary_resource_name"] = first.get("name", "")
        return data

    @field_validator("task_type", mode="before")
    @classmethod
    def coerce_task_type(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                return TaskType(v.lower())
            except ValueError:
                return TaskType.OTHER
        return v

    @field_validator("priority", mode="before")
    @classmethod
    def coerce_priority(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                return Priority(v.lower())
            except ValueError:
                return Priority.MEDIUM
        return v

    @field_validator("phase", mode="before")
    @classmethod
    def coerce_phase(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                return Phase(v.lower())
            except ValueError as e:
                raise ValueError(f"Invalid phase: {v}") from e
        return v


class Plan(BaseModel):
    """A confirmed day's plan for a single bug class + phase."""

    id: int | None = None
    bug_class_id: int | None = None
    bug_class_name: str = ""
    phase: Phase
    research_mode: ResearchMode | None = Field(
        None, description="Only set when phase == research"
    )
    date: str = Field(..., description="YYYY-MM-DD")
    target_hours: float
    tasks: list[Task] = Field(default_factory=list)
    rationale: str = Field(
        "", description="Why this plan: ties tasks to user state and confirmed direction"
    )
    # Optional reference section — used by the execute phase to list
    # openly-available tools the user can use for hunting (NOT to build).
    # Empty for other phases by default; renderers hide the block when empty.
    tools_section: list[Resource] = Field(default_factory=list)
    proposed_at: datetime | None = None
    confirmed_at: datetime | None = None
    status: PlanStatus = PlanStatus.DRAFT

    @property
    def total_hours(self) -> float:
        return sum(t.estimated_hours for t in self.tasks)


# ---------------------------------------------------------------------------
# Feedback (email reply + CLI marks)
# ---------------------------------------------------------------------------


class TaskUpdate(BaseModel):
    """One task's status update parsed from an email reply."""

    task_id: int
    status: TaskStatus
    actual_hours: float | None = None
    notes: str = ""
    learnings: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def coerce_status(cls, v: object) -> object:
        if isinstance(v, str):
            v_lower = v.lower().strip()
            try:
                return TaskStatus(v_lower)
            except ValueError:
                if v_lower in ("complete", "completed", "finished"):
                    return TaskStatus.DONE
                if v_lower in ("skipped", "skip"):
                    return TaskStatus.SKIPPED
                return TaskStatus.PENDING
        return v


class EmailFeedback(BaseModel):
    """Parsed email reply — multiple task updates + general notes."""

    task_updates: list[TaskUpdate] = Field(default_factory=list)
    general_notes: str = ""
    total_hours_reported: float | None = None


# ---------------------------------------------------------------------------
# Consumed resource ledger
# ---------------------------------------------------------------------------


class ConsumedResource(BaseModel):
    """A resource (URL) already covered for a bug class."""

    bug_class_id: int
    url: str
    title: str = ""
    phase: Phase
    source_type: SourceType = SourceType.WEB
    consumed_at: datetime | None = None


class UserNote(BaseModel):
    """A persistent general note from an email reply."""

    id: int | None = None
    note: str
    received_at: datetime | None = None
