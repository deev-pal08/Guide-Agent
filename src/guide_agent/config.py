"""Configuration loading and validation for the Guide Agent."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """Three models — cheap conversation, mid-tier daily planning, top-tier research."""

    conversation_model: str = "claude-haiku-4-5"
    planner_model: str = "claude-sonnet-4-6"
    research_model: str = "claude-opus-4-8"
    max_tokens: int = 16384
    api_key_env: str = "ANTHROPIC_API_KEY"

    @property
    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ValueError(f"Environment variable {self.api_key_env} is not set")
        return key


class EmailConfig(BaseModel):
    enabled: bool = True
    from_address: str = "guide@yourdomain.com"
    to_addresses: list[str] = Field(default_factory=list)
    api_key_env: str = "RESEND_API_KEY"

    @property
    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ValueError(f"Environment variable {self.api_key_env} is not set")
        return key


class IMAPConfig(BaseModel):
    enabled: bool = True
    server: str = "imap.gmail.com"
    port: int = 993
    mailbox: str = "INBOX"
    email_env: str = "IMAP_EMAIL"
    password_env: str = "IMAP_PASSWORD"

    @property
    def email(self) -> str:
        return os.environ.get(self.email_env, "")

    @property
    def password(self) -> str:
        return os.environ.get(self.password_env, "")


class NewsletterConfig(BaseModel):
    """Read-only access to the Newsletter Agent's SQLite DB."""

    enabled: bool = False
    project_dir: str = ""
    stale_threshold_days: int = 7


class ProviderConfig(BaseModel):
    enabled: bool = True
    api_key_env: str

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")


class SearchConfig(BaseModel):
    enabled: bool = True
    max_results: int = 5
    brave: ProviderConfig = ProviderConfig(api_key_env="BRAVE_API_KEY")
    tavily: ProviderConfig = ProviderConfig(api_key_env="TAVILY_API_KEY")
    exa: ProviderConfig = ProviderConfig(api_key_env="EXA_API_KEY")


class SourceConfig(BaseModel):
    """A single hardcoded source the agent can mine for a bug class."""

    name: str
    base_url: str


class SourcesConfig(BaseModel):
    """Hardcoded source pool per phase.

    learn/examples/practice/execute get curated pools. research is
    discovery-only (web search + arxiv) — no hardcoded pool.

    `deep_urls` is an optional per-(phase, bug_class) override — when the
    active bug class has entries, the agent goes straight to those URLs
    in addition to running base-URL-scoped search on the pool above.
    Results are deduplicated by URL before assignment.
    """

    learn: list[SourceConfig] = Field(default_factory=list)
    examples: list[SourceConfig] = Field(default_factory=list)
    practice: list[SourceConfig] = Field(default_factory=list)
    execute: list[SourceConfig] = Field(default_factory=list)

    # Shape: {phase: {bug_class: [url, url, ...]}}
    # e.g. deep_urls.learn.postmessage = ["https://...", "https://..."]
    deep_urls: dict[str, dict[str, list[str]]] = Field(default_factory=dict)

    def get_deep_urls(self, phase: str, bug_class: str) -> list[str]:
        """Return any predeclared deep URLs for (phase, bug_class). Case-insensitive
        on bug_class — normalises to lowercase to match BugClass.name storage."""
        phase_map = self.deep_urls.get(phase, {})
        return list(phase_map.get(bug_class.lower(), []))


class AppConfig(BaseModel):
    about_me: str = "AboutMe.md"
    state_dir: str = "data"
    skills_dir: str = "src/guide_agent/skills"

    llm: LLMConfig = LLMConfig()
    email: EmailConfig = EmailConfig()
    imap: IMAPConfig = IMAPConfig()
    newsletter: NewsletterConfig = NewsletterConfig()
    search: SearchConfig = SearchConfig()
    sources: SourcesConfig = SourcesConfig()


def load_config(path: str | Path) -> AppConfig:
    """Load config from YAML — returns defaults if file is missing."""
    p = Path(path)
    if not p.exists():
        return AppConfig()
    with open(p) as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig.model_validate(raw)


def load_about_me(path: str | Path) -> str:
    """Load AboutMe.md content (empty string if missing)."""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text().strip()
