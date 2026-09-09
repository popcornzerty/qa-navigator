"""Coverage and dashboard aggregation.

QA coverage is defined here once, so the number shown on the dashboard, on the project
overview and on the coverage screen can never disagree.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from qa_engine import models, schemas

MAX_GAPS = 25


def _stories(db: Session, project_id: str | None) -> list[models.UserStory]:
    statement = select(models.UserStory).options(
        selectinload(models.UserStory.acceptance_criteria),
        selectinload(models.UserStory.gherkin_scenarios),
    )
    if project_id:
        statement = statement.where(models.UserStory.project_id == project_id)
    return list(db.scalars(statement))


def _tests(db: Session, project_id: str | None) -> list[models.PlaywrightTest]:
    statement = select(models.PlaywrightTest)
    if project_id:
        statement = statement.where(models.PlaywrightTest.project_id == project_id)
    return list(db.scalars(statement))


def coverage_report(db: Session, project_id: str | None) -> schemas.CoverageReportRead:
    stories = _stories(db, project_id)
    tests = _tests(db, project_id)

    scenarios = [scenario for story in stories for scenario in story.gherkin_scenarios]
    criteria = [item for story in stories for item in story.acceptance_criteria]
    covered = [item for item in criteria if item.covered]
    # Discovered tests carry no story, so they automate none. Their `None` would sit in
    # this set harmlessly, but leaving it there invites a later reader to assume the set
    # is a story index. `automation` below still counts them: they are real automation.
    automated_story_ids = {test.user_story_id for test in tests if test.user_story_id}

    gaps: list[schemas.CoverageGapRead] = []
    for story in stories:
        for item in story.acceptance_criteria:
            if item.covered:
                continue
            automated = story.id in automated_story_ids
            gaps.append(
                schemas.CoverageGapRead(
                    id=item.id,
                    reference=item.id,
                    label=item.text,
                    reason=(
                        f"{story.id} est automatisée mais ce critère n'est couvert par aucun scénario."
                        if automated
                        else f"{story.id} n'a encore aucune automatisation Playwright."
                    ),
                    severity=(
                        "critical"
                        if story.story_status in {"approved", "created"}
                        else "warning"
                    ),
                )
            )

    return schemas.CoverageReportRead(
        project_id=project_id or "all",
        user_stories=schemas.StoryCoverage(
            total=len(stories),
            with_gherkin=sum(1 for story in stories if story.gherkin_scenarios),
            automated=sum(1 for story in stories if story.id in automated_story_ids),
        ),
        acceptance_criteria=schemas.CriteriaCoverage(
            total=len(criteria), covered=len(covered)
        ),
        gherkin=schemas.GherkinCoverage(
            total=len(scenarios),
            valid=sum(
                1 for item in scenarios if item.scenario_status in {"valid", "automated"}
            ),
        ),
        automation=schemas.AutomationCoverage(
            total=len(tests),
            passing=sum(1 for test in tests if test.test_status == "passed"),
        ),
        coverage=(
            0.0 if not criteria else round(len(covered) / len(criteria) * 100, 1)
        ),
        gaps=gaps[:MAX_GAPS],
    )


def dashboard_summary(db: Session, project_id: str | None) -> schemas.DashboardSummaryRead:
    report = coverage_report(db, project_id)
    stories = _stories(db, project_id)
    tests = _tests(db, project_id)
    projects = list(db.scalars(select(models.Project)))

    activity: list[schemas.ActivityEventRead] = []
    analyses = list(
        db.scalars(
            select(models.Analysis).order_by(models.Analysis.created_at.desc()).limit(6)
        )
    )
    for item in analyses:
        kind = {"completed": "success", "failed": "error"}.get(item.status, "info")
        label = {
            "completed": "Analyse terminée",
            "failed": "Analyse en échec",
            "running": "Analyse en cours",
            "queued": "Analyse en file d'attente",
        }.get(item.status, "Analyse")
        project = db.get(models.Project, item.project_id)
        activity.append(
            schemas.ActivityEventRead(
                id=item.id,
                kind=kind,
                message=f"{label} — {project.name if project else item.project_id}",
                at=item.completed_at or item.created_at,
            )
        )

    return schemas.DashboardSummaryRead(
        projects=len(projects),
        active_projects=sum(
            1 for project in projects if project.project_status in {"ready", "analyzing"}
        ),
        user_stories=len(stories),
        approved_stories=sum(
            1 for story in stories if story.story_status in {"approved", "created"}
        ),
        gherkin_scenarios=report.gherkin.total,
        valid_gherkin=report.gherkin.valid,
        automated_tests=len(tests),
        failing_tests=sum(1 for test in tests if test.test_status == "failed"),
        coverage=report.coverage,
        activity=activity,
    )
