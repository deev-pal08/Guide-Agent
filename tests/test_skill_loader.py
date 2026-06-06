"""Tests for the SKILL.md file-based skill loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from guide_agent.skills.loader import (
    SkillLoader,
    SkillNotFoundError,
    SkillParseError,
    _parse_frontmatter,
    render_skills_catalogue,
)

# Path to the actual skills directory in the project — these tests verify the
# real skill bundles parse cleanly, not just synthetic ones.
SKILLS_DIR = Path(__file__).resolve().parents[1] / "src" / "guide_agent" / "skills"


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------


def test_parse_frontmatter_extracts_keys_and_body():
    text = """---
name: foo
description: A test skill
---
Body line 1
Body line 2
"""
    fm, body = _parse_frontmatter(text)
    assert fm == {"name": "foo", "description": "A test skill"}
    assert body == "Body line 1\nBody line 2"


def test_parse_frontmatter_strips_quoted_values():
    text = """---
name: "quoted"
description: 'single-quoted'
---
body
"""
    fm, _ = _parse_frontmatter(text)
    assert fm["name"] == "quoted"
    assert fm["description"] == "single-quoted"


def test_parse_frontmatter_handles_no_frontmatter():
    fm, body = _parse_frontmatter("just a body, no fm")
    assert fm == {}
    assert body == "just a body, no fm"


def test_parse_frontmatter_unterminated_raises():
    text = "---\nname: foo\nno closing"
    with pytest.raises(SkillParseError):
        _parse_frontmatter(text)


# ---------------------------------------------------------------------------
# SkillLoader against the real skills directory
# ---------------------------------------------------------------------------


@pytest.fixture
def loader():
    return SkillLoader(SKILLS_DIR)


def test_loader_lists_all_known_skills(loader):
    skills = loader.list_skills()
    assert set(skills) == {
        "learn", "examples", "practice", "execute",
        "research", "intelligent_research",
    }


def test_loader_load_meta_returns_description(loader):
    meta = loader.load_meta("learn")
    assert meta.name == "learn"
    assert len(meta.description) > 0
    # learn ships with REFERENCES.md
    assert "REFERENCES.md" in meta.references


def test_loader_load_returns_body(loader):
    bundle = loader.load("learn")
    assert bundle.meta.name == "learn"
    assert bundle.body  # non-empty


def test_research_skill_lists_all_three_modes(loader):
    meta = loader.load_meta("research")
    assert "GAP_ANALYSIS.md" in meta.references
    assert "BYPASS_HUNTING.md" in meta.references
    assert "DRAFT_GENERATION.md" in meta.references


def test_read_reference_returns_file_content(loader):
    content = loader.read_reference("research", "GAP_ANALYSIS.md")
    assert "Gap Analysis" in content or "gap" in content.lower()


def test_read_reference_unknown_skill_raises(loader):
    with pytest.raises(SkillNotFoundError):
        loader.read_reference("bogus", "x.md")


def test_read_reference_unknown_file_raises(loader):
    with pytest.raises(SkillNotFoundError):
        loader.read_reference("learn", "NONEXISTENT.md")


def test_read_reference_rejects_skill_md_itself(loader):
    with pytest.raises(ValueError):
        loader.read_reference("learn", "SKILL.md")


def test_read_reference_rejects_path_traversal(loader):
    with pytest.raises((ValueError, SkillNotFoundError)):
        loader.read_reference("learn", "../execute/SKILL.md")


def test_render_skills_catalogue_includes_all_skills(loader):
    catalogue = render_skills_catalogue(loader)
    for name in ("learn", "examples", "practice", "execute", "research", "intelligent_research"):
        assert name in catalogue
    # References section should appear at least once
    assert "References" in catalogue


# ---------------------------------------------------------------------------
# SkillLoader with synthetic temp directory
# ---------------------------------------------------------------------------


def test_loader_raises_if_skills_dir_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        SkillLoader(tmp_path / "nonexistent")


def test_load_meta_missing_description_raises(tmp_path):
    skill = tmp_path / "learn"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: learn\n---\nbody\n")
    loader = SkillLoader(tmp_path)
    with pytest.raises(SkillParseError):
        loader.load_meta("learn")


def test_load_unknown_skill_raises(tmp_path):
    (tmp_path / "learn").mkdir()
    (tmp_path / "learn" / "SKILL.md").write_text(
        "---\nname: learn\ndescription: ok\n---\nbody\n"
    )
    loader = SkillLoader(tmp_path)
    with pytest.raises(SkillNotFoundError):
        loader.load("not_a_known_skill")
