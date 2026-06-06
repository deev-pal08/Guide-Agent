"""Skill loader — file-based SKILL.md bundles with progressive disclosure.

Each phase + the intelligent_research module live as a directory under
`src/guide_agent/skills/<name>/` containing:
  - SKILL.md (required) — frontmatter (name, description) + body instructions
  - REFERENCES.md / GAP_ANALYSIS.md / etc. (optional) — deeper reference docs

Loading model — modeled on Anthropic's Skills design but local + file-based:
  Level 1 (always loaded): Frontmatter metadata, ~100 tokens. Used in the
                           initial system prompt so the model knows what
                           skills exist.
  Level 2 (on activation): SKILL.md body. Loaded into the system prompt
                           when a phase fires.
  Level 3 (on demand):     Reference files. Pulled in only when the model
                           invokes the read_skill_reference tool.

This file is the only one that touches the filesystem for skills — the
rest of the codebase uses SkillLoader.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Recognised "always pull frontmatter from disk" skill names.
# Phases plus the shared research module.
KNOWN_SKILLS = (
    "learn",
    "examples",
    "practice",
    "execute",
    "research",
    "intelligent_research",
)


@dataclass(frozen=True)
class SkillMeta:
    """Level-1 metadata for a skill — small, always loaded."""

    name: str
    description: str
    skill_dir: Path
    references: tuple[str, ...]  # filenames of available reference docs


@dataclass(frozen=True)
class SkillBundle:
    """Level-2 — full SKILL.md body + meta + reference index."""

    meta: SkillMeta
    body: str


class SkillNotFoundError(LookupError):
    pass


class SkillParseError(ValueError):
    pass


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse simple YAML-style frontmatter delimited by --- lines.

    Returns (frontmatter_dict, body). Frontmatter is a minimal key: value
    parser (no nested structures, no lists) — enough for `name` and
    `description`.

    If no frontmatter is found, returns ({}, full_text).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    frontmatter: dict[str, str] = {}
    body_start = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = i + 1
            break
        if ":" in line:
            key, _, value = line.partition(":")
            frontmatter[key.strip()] = value.strip().strip('"').strip("'")

    if body_start == -1:
        raise SkillParseError("Unterminated frontmatter block (missing closing ---)")

    body = "\n".join(lines[body_start:]).strip()
    return frontmatter, body


class SkillLoader:
    """Load SKILL.md bundles from a skills directory."""

    def __init__(self, skills_dir: str | Path):
        self.dir = Path(skills_dir).expanduser()
        if not self.dir.exists():
            raise FileNotFoundError(f"Skills directory not found: {self.dir}")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_skills(self) -> list[str]:
        """Return names of all skills present on disk (in load order)."""
        present = []
        for name in KNOWN_SKILLS:
            if (self.dir / name / "SKILL.md").exists():
                present.append(name)
        return present

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_meta(self, name: str) -> SkillMeta:
        """Level 1 — just the frontmatter + reference index. Cheap."""
        skill_dir = self._resolve(name)
        skill_md = skill_dir / "SKILL.md"
        text = skill_md.read_text()
        frontmatter, _body = _parse_frontmatter(text)

        skill_name = frontmatter.get("name", name)
        description = frontmatter.get("description", "")

        if not description:
            raise SkillParseError(
                f"Skill {name} is missing the 'description' frontmatter field"
            )

        refs = tuple(sorted(
            p.name for p in skill_dir.iterdir()
            if p.is_file() and p.name != "SKILL.md" and p.suffix.lower() == ".md"
        ))

        return SkillMeta(
            name=skill_name,
            description=description,
            skill_dir=skill_dir,
            references=refs,
        )

    def load(self, name: str) -> SkillBundle:
        """Level 2 — full SKILL.md body + meta."""
        meta = self.load_meta(name)
        text = (meta.skill_dir / "SKILL.md").read_text()
        _frontmatter, body = _parse_frontmatter(text)
        return SkillBundle(meta=meta, body=body)

    def read_reference(self, skill_name: str, filename: str) -> str:
        """Level 3 — read a specific reference doc for a skill.

        Used by the read_skill_reference tool. Validates the filename
        actually belongs to the named skill (no path traversal).
        """
        skill_dir = self._resolve(skill_name)
        # Strict containment — no `..`, no absolute paths
        target = (skill_dir / filename).resolve()
        if not str(target).startswith(str(skill_dir.resolve())):
            raise ValueError(
                f"Reference {filename!r} is outside skill {skill_name!r}"
            )
        if not target.exists() or not target.is_file():
            raise SkillNotFoundError(
                f"Reference {filename!r} not found for skill {skill_name!r}"
            )
        if target.name == "SKILL.md":
            raise ValueError(
                "Use load() for SKILL.md, not read_reference()"
            )
        return target.read_text()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve(self, name: str) -> Path:
        if name not in KNOWN_SKILLS:
            raise SkillNotFoundError(
                f"Unknown skill {name!r}. Known: {', '.join(KNOWN_SKILLS)}"
            )
        skill_dir = self.dir / name
        if not (skill_dir / "SKILL.md").exists():
            raise SkillNotFoundError(
                f"Skill {name!r} has no SKILL.md at {skill_dir / 'SKILL.md'}"
            )
        return skill_dir


# ---------------------------------------------------------------------------
# Tool-shaped helpers for the Anthropic SDK
# ---------------------------------------------------------------------------


READ_SKILL_REFERENCE_TOOL_DEF = {
    "name": "read_skill_reference",
    "description": (
        "Load a deeper reference document for the active skill (e.g., REFERENCES.md, "
        "GAP_ANALYSIS.md). Only call when the SKILL.md instructions explicitly point "
        "to a reference file OR when you need methodology depth not in SKILL.md."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": (
                    "Name of the skill (e.g., 'learn', 'research', "
                    "'intelligent_research')"
                ),
            },
            "filename": {
                "type": "string",
                "description": "Reference filename (e.g., 'REFERENCES.md', 'GAP_ANALYSIS.md')",
            },
        },
        "required": ["skill_name", "filename"],
    },
}


def render_skills_catalogue(loader: SkillLoader) -> str:
    """Render a compact catalogue of skill metadata for system-prompt injection.

    Used so the model knows which skills exist and what reference files
    are available, without paying the token cost of loading every body.
    """
    lines = ["## Available skills"]
    for name in loader.list_skills():
        meta = loader.load_meta(name)
        lines.append(f"- **{meta.name}** — {meta.description}")
        if meta.references:
            refs = ", ".join(meta.references)
            lines.append(f"  References (load via read_skill_reference): {refs}")
    return "\n".join(lines)
