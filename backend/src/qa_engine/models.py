import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from qa_engine.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    repository_path: Mapped[str] = mapped_column(Text, unique=True)
    # Set for git projects: the remote the working copy is cloned from.
    repository_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(30), default="local")

    # Configuration surfaced by the frontend Settings screen.
    branch: Mapped[str] = mapped_column(String(200), default="local")
    jira_project: Mapped[str | None] = mapped_column(String(50), nullable=True)
    jira_connection: Mapped[str] = mapped_column(String(30), default="not_connected")
    ai_provider: Mapped[str] = mapped_column(String(30), default="ollama")
    project_status: Mapped[str] = mapped_column(String(30), default="never_analyzed")
    last_analysis: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    playwright_config: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Feature(Base):
    """A functional domain, produced by grouping raw symbols (see features.py)."""

    __tablename__ = "features"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_files: Mapped[list] = mapped_column(JSON, default=list)
    # Raw evidence: routes, components, api calls, test ids, forms.
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    feature_status: Mapped[str] = mapped_column(String(30), default="detected")


class UserStory(Base):
    __tablename__ = "user_stories"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    feature_id: Mapped[str | None] = mapped_column(ForeignKey("features.id"), nullable=True)
    feature_name: Mapped[str] = mapped_column(String(200), default="")
    epic: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_files: Mapped[list] = mapped_column(JSON, default=list)
    jira_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="generated")  # generated | jira | manual
    story_status: Mapped[str] = mapped_column(String(30), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    acceptance_criteria: Mapped[list["AcceptanceCriterion"]] = relationship(
        back_populates="user_story", cascade="all, delete-orphan", order_by="AcceptanceCriterion.id"
    )
    gherkin_scenarios: Mapped[list["GherkinScenario"]] = relationship(
        back_populates="user_story", cascade="all, delete-orphan"
    )


class AcceptanceCriterion(Base):
    __tablename__ = "acceptance_criteria"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_story_id: Mapped[str] = mapped_column(ForeignKey("user_stories.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    covered: Mapped[bool] = mapped_column(Boolean, default=False)

    user_story: Mapped[UserStory] = relationship(back_populates="acceptance_criteria")


class GherkinScenario(Base):
    __tablename__ = "gherkin_scenarios"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_story_id: Mapped[str] = mapped_column(ForeignKey("user_stories.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    feature: Mapped[str] = mapped_column(String(200))
    scenario: Mapped[str] = mapped_column(String(500))
    given: Mapped[list] = mapped_column(JSON, default=list)
    when: Mapped[list] = mapped_column(JSON, default=list)
    then: Mapped[list] = mapped_column(JSON, default=list)
    scenario_status: Mapped[str] = mapped_column(String(30), default="draft")

    user_story: Mapped[UserStory] = relationship(back_populates="gherkin_scenarios")


class PlaywrightTest(Base):
    __tablename__ = "playwright_tests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_story_id: Mapped[str] = mapped_column(ForeignKey("user_stories.id"), index=True)
    gherkin_scenario_id: Mapped[str] = mapped_column(
        ForeignKey("gherkin_scenarios.id"), index=True
    )
    scenario: Mapped[str] = mapped_column(String(500), default="")
    file: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="")
    test_status: Mapped[str] = mapped_column(String(20), default="not_run")
    last_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
