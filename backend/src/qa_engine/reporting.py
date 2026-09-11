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


# A requirement someone owns: imported from a tracker, written by hand, or generated and
# then approved by a person. An untouched draft is a proposal, not a requirement.
OWNED_ORIGINS = {"jira", "manual"}
OWNED_STATUSES = {"approved", "created", "out_of_sync"}


def is_owned(story: models.UserStory) -> bool:
    """Whether a story is a requirement a person stands behind.

    Coverage measured against unreviewed drafts is not a measure of the product: it moved
    from 30.8% to 11.4% on an unchanged product with unchanged tests, because a generation
    run wrote more criteria. The denominator has to be something the team owns, or the
    number tracks the model's verbosity instead of the risk.
    """
    return story.origin in OWNED_ORIGINS or story.story_status in OWNED_STATUSES


def _ratio(covered: int, total: int) -> float | None:
    """A percentage, or None when there is nothing to divide by.

    Reporting 0% for an empty baseline reads as "nothing is tested" when the truth is
    "nothing has been claimed yet" — the opposite of a useful signal.
    """
    return round(covered / total * 100, 1) if total else None


def coverage_report(db: Session, project_id: str | None) -> schemas.CoverageReportRead:
    stories = _stories(db, project_id)
    tests = _tests(db, project_id)

    scenarios = [scenario for story in stories for scenario in story.gherkin_scenarios]
    criteria = [item for story in stories for item in story.acceptance_criteria]
    covered = [item for item in criteria if item.covered]

    owned = [story for story in stories if is_owned(story)]
    owned_criteria = [item for story in owned for item in story.acceptance_criteria]
    owned_covered = [item for item in owned_criteria if item.covered]

    drafts = [story for story in stories if not is_owned(story)]
    draft_criteria = [item for story in drafts for item in story.acceptance_criteria]
    draft_covered = [item for item in draft_criteria if item.covered]
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
        coverage=_ratio(len(owned_covered), len(owned_criteria)),
        draft_coverage=_ratio(len(draft_covered), len(draft_criteria)),
        baseline="owned" if owned_criteria else "none",
        # A discovered test proves a behaviour without tracing to a stated requirement.
        verified_behaviours=sum(
            1 for test in tests if test.origin == "discovered" and test.test_status == "passed"
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


def _suite_of(row: models.PlaywrightTest) -> str:
    """The file a test belongs to, which is the unit anyone reads a suite in.

    Grouping by anything finer produces a wall of a thousand rows; by anything coarser,
    a number nobody can act on. "Which file is red" is the question a standup asks.
    """
    return (row.file or "—").replace("\\", "/")


def test_inventory(db: Session, project_id: str | None) -> schemas.TestInventoryRead:
    """Every test the engine knows about, grouped so it can be read at a glance.

    The point of this is to be presentable: what exists, what passes, what has never run,
    split into the two families a team actually talks about — the browser tests and
    everything else. It aggregates what is stored and runs nothing, so it answers in
    milliseconds whether or not the suites are currently runnable.

    A suite whose tests have never run is not a failing suite, and the two are kept
    apart. Reporting "not run" as a problem would push a team to run everything before
    every standup; reporting it as a pass would be a lie.
    """
    rows = _tests(db, project_id)

    groups: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row.kind or "e2e", row.framework or "playwright", _suite_of(row))
        entry = groups.setdefault(
            key,
            {
                "kind": key[0],
                "framework": key[1],
                "suite": key[2],
                "tests": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "not_run": 0,
                "duration_ms": 0,
                "last_run": None,
                "origins": set(),
            },
        )
        entry["tests"] += 1
        status = row.test_status if row.test_status in _COUNTED else "not_run"
        entry[status] += 1
        entry["duration_ms"] += row.duration_ms or 0
        entry["origins"].add(row.origin or "discovered")
        if row.last_run and (entry["last_run"] is None or row.last_run > entry["last_run"]):
            entry["last_run"] = row.last_run

    suites = [
        schemas.TestSuiteRead(
            kind=entry["kind"],
            framework=entry["framework"],
            suite=entry["suite"],
            tests=entry["tests"],
            passed=entry["passed"],
            failed=entry["failed"],
            skipped=entry["skipped"],
            not_run=entry["not_run"],
            duration_ms=entry["duration_ms"],
            last_run=entry["last_run"],
            origins=sorted(entry["origins"]),
        )
        # Red first, then never-run, then the rest: a standup reads the top of a list.
        for entry in sorted(
            groups.values(),
            key=lambda item: (-item["failed"], -item["not_run"], item["suite"]),
        )
    ]

    return schemas.TestInventoryRead(
        project_id=project_id or "",
        totals=_totals(suites),
        suites=suites,
    )


_COUNTED = {"passed", "failed", "skipped", "not_run"}


def _totals(suites: list[schemas.TestSuiteRead]) -> schemas.TestTotalsRead:
    def add(field: str) -> int:
        return sum(getattr(suite, field) for suite in suites)

    executed = add("passed") + add("failed")
    return schemas.TestTotalsRead(
        suites=len(suites),
        tests=add("tests"),
        passed=add("passed"),
        failed=add("failed"),
        skipped=add("skipped"),
        not_run=add("not_run"),
        duration_ms=add("duration_ms"),
        # Of the tests that actually ran, how many hold. A suite nobody has run yet is
        # absent from this ratio rather than counted as a failure, which is why it is
        # reported next to `not_run` and never on its own.
        pass_rate=(add("passed") / executed * 100) if executed else None,
    )
