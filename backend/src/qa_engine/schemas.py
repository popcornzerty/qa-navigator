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
    coverage: float | None = 0


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
    # What a generated test may read from the environment, as {label: VARIABLE}. A spec
    # that has to sign in needs a credential, and the engine forbids `process.` outright
    # so that generated code cannot reach for whatever it likes. Naming the variables here
    # keeps the ban and opens exactly the door the project chose to open; the values
    # themselves stay in the environment and never enter the database.
    credentials: dict[str, str] = {}


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


class TestRunRead(Wire):
    """One execution in the history."""

    id: str
    test_id: str
    project_id: str
    scenario: str
    file: str
    origin: TestOrigin
    status: TestStatus
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int
    error_message: str | None
    screenshot: str | None
    trace: str | None
    total: int
    passed: int
    failed: int
    skipped: int


class TestRunDetailRead(TestRunRead):
    """One execution with its output.

    The log is served from an offset so a client watching a run in progress asks only for
    what it has not seen. Sending the whole thing on every poll would resend the same
    kilobytes several times a second for the length of the run.
    """

    log: str = ""
    # Number of lines before the first one in `log`; echo it back as `since` to continue.
    offset: int = 0
    # Total lines produced so far, so a client can tell it is behind.
    line_count: int = 0


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
    # Criteria of requirements a person owns — imported from Jira, or generated and then
    # approved. This is the only ratio worth reporting as coverage: measured against
    # unreviewed drafts instead, the figure moved from 30.8% to 11.4% on an unchanged
    # product, purely because the model wrote more criteria that run.
    coverage: float | None
    # What the drafts would give, kept apart and never presented as coverage.
    draft_coverage: float | None
    baseline: Literal["owned", "none"]
    # Passing tests written against the product directly. They prove a behaviour holds
    # without tracing to any stated requirement, and counting them as coverage would be
    # as wrong as ignoring what they establish.
    verified_behaviours: int
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
    # None when no requirement has been claimed yet — which is not the same as
    # nothing being tested, and must not be shown as 0%.
    coverage: float | None
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
