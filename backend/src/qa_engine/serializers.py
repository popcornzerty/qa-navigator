"""ORM to DTO conversion.

Kept out of the route handlers so the HTTP layer stays a thin adapter and the response
shapes have a single definition point.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qa_engine import models, ollama, schemas
from qa_engine.config import settings


def project(db: Session, row: models.Project) -> schemas.ProjectRead:
    story_count = (
        db.scalar(
            select(func.count())
            .select_from(models.UserStory)
            .where(models.UserStory.project_id == row.id)
        )
        or 0
    )
    test_count = (
        db.scalar(
            select(func.count())
            .select_from(models.PlaywrightTest)
            .where(models.PlaywrightTest.project_id == row.id)
        )
        or 0
    )
    return schemas.ProjectRead(
        id=row.id,
        name=row.name,
        # Git projects are identified by their remote; local ones by their path.
        repository=row.repository_url or row.repository_path,
        repository_source=row.provider,
        branch=row.branch,
        jira_project=row.jira_project,
        jira_connection=row.jira_connection,
        ai_provider=row.ai_provider,
        status=row.project_status,
        last_analysis=row.last_analysis.isoformat() if row.last_analysis else None,
        story_count=story_count,
        automated_test_count=test_count,
    )


def project_settings(row: models.Project) -> schemas.ProjectSettingsRead:
    playwright = schemas.PlaywrightSettings(**(row.playwright_config or {}))
    return schemas.ProjectSettingsRead(
        project_id=row.id,
        name=row.name,
        repository=row.repository_url or row.repository_path,
        branch=row.branch,
        github=schemas.GithubSettings(
            status="connected" if row.provider == "github" else "disconnected",
            account=None,
        ),
        jira=schemas.JiraSettings(status=row.jira_connection, project_key=row.jira_project),
        ai=schemas.AiSettings(
            provider=row.ai_provider,
            model=settings.ollama_model,
            status="connected" if ollama.is_available() else "disconnected",
        ),
        playwright=playwright,
    )


def analysis(row: models.Analysis) -> schemas.AnalysisRead:
    return schemas.AnalysisRead(
        job_id=row.id,
        project_id=row.project_id,
        status=row.status,
        progress=row.progress,
        started_at=row.created_at,
        steps=[schemas.AnalysisStepRead(**step) for step in (row.steps or [])],
        error=row.error,
        summary=row.summary,
        completed_at=row.completed_at,
    )


def feature(row: models.Feature) -> schemas.FeatureRead:
    return schemas.FeatureRead(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        description=row.description,
        confidence=row.confidence,
        source_files=row.source_files or [],
        status=row.feature_status,
    )


def criterion(row: models.AcceptanceCriterion) -> schemas.AcceptanceCriterionRead:
    return schemas.AcceptanceCriterionRead(
        id=row.id,
        user_story_id=row.user_story_id,
        text=row.text,
        covered=row.covered,
    )


def scenario(row: models.GherkinScenario) -> schemas.GherkinScenarioRead:
    return schemas.GherkinScenarioRead(
        id=row.id,
        user_story_id=row.user_story_id,
        feature=row.feature,
        scenario=row.scenario,
        given=row.given or [],
        when=row.when or [],
        then=row.then or [],
        status=row.scenario_status,
    )


def story(row: models.UserStory) -> schemas.UserStoryRead:
    return schemas.UserStoryRead(
        id=row.id,
        project_id=row.project_id,
        feature_id=row.feature_id,
        feature_name=row.feature_name,
        epic=row.epic,
        title=row.title,
        description=row.description,
        confidence=row.confidence,
        source_files=row.source_files or [],
        acceptance_criteria=[criterion(item) for item in row.acceptance_criteria],
        gherkin_scenarios=[scenario(item) for item in row.gherkin_scenarios],
        jira_key=row.jira_key,
        status=row.story_status,
    )


def test_origin(row: models.PlaywrightTest, story_row: models.UserStory | None) -> str:
    """How a test came to exist, as the UI labels it.

    A generated test inherits the provenance of the story it was written from, because
    that is the distinction that matters to the reader: a spec derived from a Jira story
    traces to a stated requirement, one derived from code traces only to code.
    """
    if row.origin == "discovered":
        return "discovered"
    if story_row is not None and story_row.origin in {"jira", "manual"}:
        return story_row.origin
    return "code"


def test(row: models.PlaywrightTest, story_row: models.UserStory | None) -> schemas.PlaywrightTestRead:
    payload = dict(row.result or {})
    payload.setdefault("status", row.test_status)
    payload.setdefault("executed_at", row.last_run.isoformat() if row.last_run else None)
    payload.setdefault("duration_ms", row.duration_ms)
    return schemas.PlaywrightTestRead(
        id=row.id,
        project_id=row.project_id,
        user_story_id=row.user_story_id,
        user_story_key=(story_row.jira_key if story_row and story_row.jira_key else row.user_story_id),
        gherkin_scenario_id=row.gherkin_scenario_id,
        scenario=row.scenario,
        file=row.file,
        origin=test_origin(row, story_row),
        status=row.test_status,
        last_run=row.last_run,
        duration_ms=row.duration_ms,
        result=schemas.TestResultRead(**payload),
    )
