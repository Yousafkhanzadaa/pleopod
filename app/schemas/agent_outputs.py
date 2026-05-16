from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentOutputModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ResearchSource(AgentOutputModel):
    url: str = Field(min_length=1)
    title: str | None = None
    publisher: str | None = None
    author: str | None = None
    published_at: str | None = None
    source_tier: Literal["A", "B", "C"] = "B"
    credibility_score: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: str | None = None


class ResearchClaim(AgentOutputModel):
    claim_text: str = Field(min_length=1)
    source_urls: list[str] = Field(default_factory=list)
    verification_status: Literal[
        "unverified",
        "supported",
        "unsupported",
        "misleading",
        "needs_context",
    ] = "supported"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: str | None = None
    used_in_script: bool = False


class ResearchDossier(AgentOutputModel):
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    claims: list[ResearchClaim] = Field(default_factory=list)


class TopicScoutCandidate(AgentOutputModel):
    topic: str = Field(min_length=3)
    title: str = Field(min_length=3)
    rationale: str = ""
    source_urls: list[str] = Field(default_factory=list)
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class TopicScoutDecision(AgentOutputModel):
    topic: str = Field(min_length=3)
    title: str = Field(min_length=3)
    rationale: str = ""
    source_urls: list[str] = Field(default_factory=list)
    candidates: list[TopicScoutCandidate] = Field(default_factory=list)
    rejected_topics: list[str] = Field(default_factory=list)


class ScriptSpeaker(AgentOutputModel):
    name: str = Field(min_length=1)
    role: str | None = None
    voice_name: str = Field(min_length=1)
    style: str | None = None


class PodcastScript(AgentOutputModel):
    title: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    summary: str = ""
    description: str = ""
    speakers: list[ScriptSpeaker] = Field(min_length=2, max_length=2)
    transcript: str = Field(min_length=1)
    used_claims: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class VerificationLineCheck(AgentOutputModel):
    line: str = ""
    claim: str | None = None
    verdict: Literal["supported", "unsupported", "misleading", "needs_context", "non_factual"]
    source_urls: list[str] = Field(default_factory=list)
    fix: str | None = None


class VerificationReport(AgentOutputModel):
    verdict: Literal["approved", "fixed", "rejected"]
    score: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
    fixed_transcript: str | None = None
    line_checks: list[VerificationLineCheck] = Field(default_factory=list)
