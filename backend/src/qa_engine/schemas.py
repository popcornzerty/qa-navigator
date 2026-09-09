"""Wire DTOs.

Field names stay snake_case in Python and are serialised as camelCase, which is exactly
the shape declared in the frontend's ``src/types/models.ts``. Keeping the two in sync is
what lets the UI switch from the mock API to this service without any change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

SymbolKind = Literal["route", "component", "hook", "api_call", "form", "testid"]
AnalysisStatus = Literal["queued", "running", "completed", "failed"]
StepStatus = Literal["pending", "running", "completed", "failed"]
StoryStatus = Literal["draft", "needs_review", "approved", "created", "out_of_sync"]
GherkinStatus = Literal["draft", "valid", "invalid", "automated"]
# `running` is what lets the UI tell a run in flight from a stale result: without it a
# test keeps its previous verdict while executing, and nothing on screen moves.
TestStatus = Literal["passed", "failed", "skipped", "not_run", "running"]
JiraConnection = Literal["not_connected", "connected"]


class Wire(BaseModel):
    """Base DTO: snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# --- Projects ------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    repository_path: str = Field(
        min_length=1, validation_alias=AliasChoices("repository_path", "repository")
    )
    branch: str = "local"
    repository_source: str = Field(
        default="local", validation_alias=AliasChoices("repository_source", "repositorySource")
    )
    jira_connection: JiraConnection = Field(
        default="not_connected",
        validation_alias=AliasChoices("jira_connection", "jiraConnection"),
    )
    jira_project: str | None = Field(
        default=None, validation_alias=AliasChoices("jira_project", "jiraProject")
    )
    ai_provider: str = Field(
        default="ollama", validation_alias=AliasChoices("ai_provider", "aiProvider")
    )


class ProjectRead(Wire):
    id: str
    name: str
    repository: str
    repository_source: str
    branch: str
    jira_project: str | None
    jira_connection: str
    ai_provider: str
    status: str
    last_analysis: str | None
    story_count: int = 0
    automated_test_count: int = 0


class ProjectStatsRead(Wire):
    features: int = 0
    user_stories: int = 0
    gherkin_scenarios: int = 0
    playwright_tests: int = 0
    coverage: float = 0


class GithubSettings(Wire):
    status: Literal["connected", "disconnected"]
    account: str | None


class JiraSettings(Wire):
    status: JiraConnection
    project_key: str | None


class AiSettings(Wire):
    provider: str
    model: str
    status: Literal["connected", "disconnected"]


class PlaywrightSettings(Wire):
    test_directory: str = "tests"
    base_url: str = "http://localhost:8080"
    browsers: list[str] = ["chromium"]
    headless: bool = True


class ProjectSettingsRead(Wire):
    project_id: str
    name: str
    repository: str
    branch: str
    github: GithubSettings
    jira: JiraSettings
    ai: AiSettings
    playwright: PlaywrightSettings


class ProjectSettingsPatch(Wire):
    name: str | None = None
    repository: str | None = None
    branch: str | None = None
    jira: JiraSettings | None = None
    playwright: PlaywrightSettings | None = None


# --- Analyses ------------------------------------------------------------------------


class AnalysisCreate(BaseModel):
    force: bool = False


class AnalysisStart(BaseModel):
    project_id: str = Field(validation_alias=AliasChoices("project_id", "projectId"))


class AnalysisStepRead(Wire):
    key: str
    label: str
    status: StepStatus
    detail: str | None = None


class AnalysisRead(Wire):
    job_id: str
    project_id: str
    status: AnalysisStatus
    progress: int
    started_at: datetime
    steps: list[AnalysisStepRead] = []
    error: str | None = None
    summary: dict[str, Any] | None = None
    completed_at: datetime | None = None


# --- Features ------------------------------------------------------------------------


class FeatureRead(Wire):
    id: str
    project_id: str
    name: str
    description: str
    confidence: float
    source_files: list[str]
    status: str


# --- Stories -------------------------------------------------------------------------


class AcceptanceCriterionRead(Wire):
    id: str
    user_story_id: str
    text: str
    covered: bool


class AcceptanceCriterionPatch(Wire):
    text: str | None = None
    covered: bool | None = None


class GherkinScenarioRead(Wire):
    id: str
    user_story_id: str
    feature: str
    scenario: str
    given: list[str]
    when: list[str]
    then: list[str]
    status: GherkinStatus


class GherkinScenarioPatch(Wire):
    feature: str | None = None
    scenario: str | None = None
    given: list[str] | None = None
    when: list[str] | None = None
    then: list[str] | None = None
    status: GherkinStatus | None = None


class UserStoryRead(Wire):
    id: str
    project_id: str
    feature_id: str | None
    feature_name: str
    epic: str
    title: str
    description: str
    confidence: float
    source_files: list[str]
    acceptance_criteria: list[AcceptanceCriterionRead]
    gherkin_scenarios: list[GherkinScenarioRead]
    jira_key: str | None
    status: StoryStatus


class UserStoryPatch(Wire):
    title: str | None = None
    description: str | None = None
    status: StoryStatus | None = None


class UserStoryCreate(Wire):
    project_id: str
    title: str
    description: str = ""
    epic: str = ""
    feature_name: str = ""
    jira_key: str | None = None
    acceptance_criteria: list[str] = []


# --- Tests ---------------------------------------------------------------------------


class TestResultRead(Wire):
    status: TestStatus
    executed_at: datetime | None
    duration_ms: int
    error_message: str | None = None
    screenshot: str | None = None
    trace: str | None = None
    console_output: list[str] | None = None


# Where a test came from, which is what tells the reader how much it proves.
# `code` and `jira` both mean the engine wrote it, and differ by what it was written
# from; `discovered` means the repository already had it.
TestOrigin = Literal["code", "jira", "manual", "discovered"]


class PlaywrightTestRead(Wire):
    id: str
    project_id: str
    user_story_id: str | None
    user_story_key: str | None
    gherkin_scenario_id: str | None
    scenario: str
    file: str
    origin: TestOrigin
    status: TestStatus
    last_run: datetime | None
    duration_ms: int
    result: TestResultRead


class PlaywrightTestDetailRead(PlaywrightTestRead):
    """One test, with the code that defines it.

    The source is kept out of the list response on purpose: a suite of a hundred imported
    tests would otherwise ship every spec file, repeatedly, on every poll.
    """

    source: str = ""
    line: int | None = None
    source_error: str | None = None


class JobRead(Wire):
    job_id: str
    status: str
    progress: int = 0


# --- Coverage & dashboard ------------------------------------------------------------


class CoverageGapRead(Wire):
    id: str
    reference: str
    label: str
    reason: str
    severity: Literal["warning", "critical"]


class StoryCoverage(Wire):
    total: int
    with_gherkin: int
    automated: int


class CriteriaCoverage(Wire):
    total: int
    covered: int


class GherkinCoverage(Wire):
    total: int
    valid: int


class AutomationCoverage(Wire):
    total: int
    passing: int


class CoverageReportRead(Wire):
    project_id: str
    user_stories: StoryCoverage
    acceptance_criteria: CriteriaCoverage
    gherkin: GherkinCoverage
    automation: AutomationCoverage
    coverage: float
    gaps: list[CoverageGapRead]


class ActivityEventRead(Wire):
    id: str
    kind: Literal["success", "info", "warning", "error"]
    message: str
    at: datetime


class DashboardSummaryRead(Wire):
    projects: int
    active_projects: int
    user_stories: int
    approved_stories: int
    gherkin_scenarios: int
    valid_gherkin: int
    automated_tests: int
    failing_tests: int
    coverage: float
    activity: list[ActivityEventRead]


# --- Jira ----------------------------------------------------------------------------


class JiraImportRequest(Wire):
    jql: str | None = None
    max_results: int = 50


class JiraImportResult(Wire):
    imported: int
    updated: int
    story_ids: list[str]
    jql: str
