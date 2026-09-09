"""HTTP adapter.

Route order matters: literal paths such as ``/analyses/current`` must be declared before
``/analyses/{analysis_id}``, otherwise Starlette matches the literal as a path parameter.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from qa_engine import jira, models, reporting, schemas, serializers
from qa_engine.config import settings
from qa_engine.database import get_db
from qa_engine.repositories import (
    GitUrlError,
    LocalRepositoryProvider,
    repository_slug,
    validate_git_url,
)
from qa_engine.services import (
    default_jira_jql,
    generate_playwright_for_scenario,
    import_jira_stories,
    queue_run,
    regenerate_gherkin_for_story,
    run_analysis,
    run_playwright_test,
)

router = APIRouter(prefix=settings.api_v1_prefix)


# --- helpers -------------------------------------------------------------------------


def project_or_404(project_id: str, db: Session) -> models.Project:
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def story_or_404(story_id: str, db: Session) -> models.UserStory:
    statement = (
        select(models.UserStory)
        .where(models.UserStory.id == story_id)
        .options(
            selectinload(models.UserStory.acceptance_criteria),
            selectinload(models.UserStory.gherkin_scenarios),
        )
    )
    story = db.scalar(statement)
    if not story:
        raise HTTPException(status_code=404, detail="User story not found")
    return story


# --- projects ------------------------------------------------------------------------


@router.post("/projects", response_model=schemas.ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: schemas.ProjectCreate, db: Session = Depends(get_db)):
    repository_url: str | None = None

    if payload.repository_source == "github":
        # The clone itself happens in the analysis pipeline's `repository` step, where
        # progress is already reported. Creation only validates and reserves the path.
        try:
            repository_url = validate_git_url(payload.repository_path)
        except GitUrlError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        working_copy = settings.clone_root / repository_slug(repository_url)
    else:
        try:
            working_copy = LocalRepositoryProvider(payload.repository_path).root
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if settings.allowed_roots and not any(
            working_copy.is_relative_to(root) for root in settings.allowed_roots
        ):
            raise HTTPException(
                status_code=403, detail="Repository path is outside ALLOWED_REPOSITORY_ROOTS"
            )

    existing = db.scalar(
        select(models.Project).where(models.Project.repository_path == str(working_copy))
    )
    if existing:
        raise HTTPException(status_code=409, detail="A project already uses this repository")

    project = models.Project(
        name=payload.name,
        repository_path=str(working_copy),
        repository_url=repository_url,
        provider=payload.repository_source,
        branch=payload.branch,
        jira_connection=payload.jira_connection,
        jira_project=payload.jira_project,
        ai_provider=payload.ai_provider,
        playwright_config=schemas.PlaywrightSettings().model_dump(),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return serializers.project(db, project)


@router.get("/projects", response_model=list[schemas.ProjectRead])
def list_projects(db: Session = Depends(get_db)):
    rows = db.scalars(select(models.Project).order_by(models.Project.created_at.desc()))
    return [serializers.project(db, row) for row in rows]


@router.get("/projects/{project_id}", response_model=schemas.ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db)):
    return serializers.project(db, project_or_404(project_id, db))


@router.get("/projects/{project_id}/stats", response_model=schemas.ProjectStatsRead)
def get_project_stats(project_id: str, db: Session = Depends(get_db)):
    project_or_404(project_id, db)
    report = reporting.coverage_report(db, project_id)
    features = (
        db.scalar(
            select(func.count())
            .select_from(models.Feature)
            .where(models.Feature.project_id == project_id)
        )
        or 0
    )
    return schemas.ProjectStatsRead(
        features=features,
        user_stories=report.user_stories.total,
        gherkin_scenarios=report.gherkin.total,
        playwright_tests=report.automation.total,
        coverage=report.coverage,
    )


@router.get("/projects/{project_id}/settings", response_model=schemas.ProjectSettingsRead)
def get_project_settings(project_id: str, db: Session = Depends(get_db)):
    return serializers.project_settings(project_or_404(project_id, db))


@router.patch("/projects/{project_id}/settings", response_model=schemas.ProjectSettingsRead)
def update_project_settings(
    project_id: str, payload: schemas.ProjectSettingsPatch, db: Session = Depends(get_db)
):
    project = project_or_404(project_id, db)
    if payload.name is not None:
        project.name = payload.name
    if payload.branch is not None:
        project.branch = payload.branch
    if payload.repository is not None:
        project.repository_path = payload.repository
    if payload.jira is not None:
        project.jira_connection = payload.jira.status
        project.jira_project = payload.jira.project_key
    if payload.playwright is not None:
        project.playwright_config = payload.playwright.model_dump()
    db.commit()
    db.refresh(project)
    return serializers.project_settings(project)


# --- analyses ------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/analyses",
    response_model=schemas.AnalysisRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis(
    project_id: str,
    payload: schemas.AnalysisCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    project_or_404(project_id, db)
    if not payload.force:
        active = db.scalar(
            select(models.Analysis).where(
                models.Analysis.project_id == project_id,
                models.Analysis.status.in_(["queued", "running"]),
            )
        )
        if active:
            return serializers.analysis(active)
    return serializers.analysis(_queue_analysis(project_id, background_tasks, db))


@router.post("/analyses", response_model=schemas.AnalysisRead, status_code=status.HTTP_202_ACCEPTED)
def start_analysis(
    payload: schemas.AnalysisStart,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Compatibility endpoint used by the frontend analysisApi client."""
    project_or_404(payload.project_id, db)
    return serializers.analysis(_queue_analysis(payload.project_id, background_tasks, db))


def _queue_analysis(
    project_id: str, background_tasks: BackgroundTasks, db: Session
) -> models.Analysis:
    from qa_engine.services import initial_steps

    analysis = models.Analysis(
        project_id=project_id, status="queued", progress=0, steps=initial_steps()
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    background_tasks.add_task(run_analysis, analysis.id)
    return analysis


@router.get("/projects/{project_id}/analyses", response_model=list[schemas.AnalysisRead])
def list_analyses(project_id: str, db: Session = Depends(get_db)):
    project_or_404(project_id, db)
    rows = db.scalars(
        select(models.Analysis)
        .where(models.Analysis.project_id == project_id)
        .order_by(models.Analysis.created_at.desc())
    )
    return [serializers.analysis(row) for row in rows]


@router.get("/analyses/current", response_model=schemas.AnalysisRead)
def current_analysis(project_id: str, db: Session = Depends(get_db)):
    project_or_404(project_id, db)
    analysis = db.scalar(
        select(models.Analysis)
        .where(models.Analysis.project_id == project_id)
        .order_by(models.Analysis.created_at.desc())
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis found for this project")
    return serializers.analysis(analysis)


@router.get("/analyses/{analysis_id}", response_model=schemas.AnalysisRead)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    analysis = db.get(models.Analysis, analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return serializers.analysis(analysis)


@router.get("/jobs/{job_id}", response_model=schemas.AnalysisRead)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return get_analysis(job_id, db)


# --- features ------------------------------------------------------------------------


@router.get("/features", response_model=list[schemas.FeatureRead])
def list_features(project_id: str = Query(...), db: Session = Depends(get_db)):
    project_or_404(project_id, db)
    rows = db.scalars(
        select(models.Feature)
        .where(models.Feature.project_id == project_id)
        .order_by(models.Feature.confidence.desc(), models.Feature.name)
    )
    return [serializers.feature(row) for row in rows]


@router.get("/projects/{project_id}/features", response_model=list[schemas.FeatureRead])
def list_project_features(project_id: str, db: Session = Depends(get_db)):
    return list_features(project_id=project_id, db=db)


# --- stories -------------------------------------------------------------------------


@router.get("/stories", response_model=list[schemas.UserStoryRead])
def list_stories(
    project_id: str | None = None,
    feature_id: str | None = None,
    story_status: str | None = Query(default=None, alias="status"),
    search: str | None = None,
    db: Session = Depends(get_db),
):
    statement = select(models.UserStory).options(
        selectinload(models.UserStory.acceptance_criteria),
        selectinload(models.UserStory.gherkin_scenarios),
    )
    if project_id:
        statement = statement.where(models.UserStory.project_id == project_id)
    if feature_id:
        statement = statement.where(models.UserStory.feature_id == feature_id)
    if story_status and story_status != "all":
        statement = statement.where(models.UserStory.story_status == story_status)
    if search:
        pattern = f"%{search.lower()}%"
        statement = statement.where(
            func.lower(models.UserStory.title).like(pattern)
            | func.lower(models.UserStory.id).like(pattern)
            | func.lower(models.UserStory.feature_name).like(pattern)
        )
    return [serializers.story(row) for row in db.scalars(statement.order_by(models.UserStory.id))]


@router.get("/stories/{story_id}", response_model=schemas.UserStoryRead)
def get_story(story_id: str, db: Session = Depends(get_db)):
    return serializers.story(story_or_404(story_id, db))


@router.patch("/stories/{story_id}", response_model=schemas.UserStoryRead)
def update_story(story_id: str, payload: schemas.UserStoryPatch, db: Session = Depends(get_db)):
    story = story_or_404(story_id, db)
    if payload.title is not None:
        story.title = payload.title
    if payload.description is not None:
        story.description = payload.description
    if payload.status is not None:
        story.story_status = payload.status
    db.commit()
    db.refresh(story)
    return serializers.story(story)


@router.patch(
    "/stories/{story_id}/acceptance-criteria/{criterion_id}",
    response_model=schemas.UserStoryRead,
)
def update_criterion(
    story_id: str,
    criterion_id: str,
    payload: schemas.AcceptanceCriterionPatch,
    db: Session = Depends(get_db),
):
    story = story_or_404(story_id, db)
    criterion = db.get(models.AcceptanceCriterion, criterion_id)
    if not criterion or criterion.user_story_id != story.id:
        raise HTTPException(status_code=404, detail="Acceptance criterion not found")
    if payload.text is not None:
        criterion.text = payload.text
    if payload.covered is not None:
        criterion.covered = payload.covered
    db.commit()
    db.refresh(story)
    return serializers.story(story)


@router.post(
    "/stories/{story_id}/gherkin",
    response_model=schemas.JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_gherkin(
    story_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Rebuild this story's Gherkin from the current analysis and prompts.

    Replaces the existing scenarios, and removes the Playwright tests derived from them:
    a test asserting a scenario that no longer exists still runs, and still reports green.
    """
    story = story_or_404(story_id, db)
    if story.feature_id is None:
        raise HTTPException(
            status_code=409,
            detail="This story is not attached to an analysed feature, so its scenarios "
            "cannot be grounded in real code. Re-run an analysis first.",
        )
    background_tasks.add_task(regenerate_gherkin_for_story, story_id)
    return schemas.JobRead(job_id=story_id, status="queued", progress=0)


@router.post("/stories/{story_id}/jira-sync", response_model=schemas.UserStoryRead)
def sync_story_to_jira(story_id: str, db: Session = Depends(get_db)):
    story = story_or_404(story_id, db)
    project = db.get(models.Project, story.project_id)
    if not project or project.jira_connection != "connected":
        raise HTTPException(
            status_code=409,
            detail="Jira is not connected for this project. Configure it in the project settings.",
        )
    raise HTTPException(
        status_code=501,
        detail="Pushing a story to Jira writes to an external system and is not "
        "implemented. Importing from Jira is available at "
        "POST /projects/{project_id}/jira-import.",
    )


@router.post("/projects/{project_id}/jira-import", response_model=schemas.JiraImportResult)
def import_from_jira(
    project_id: str, payload: schemas.JiraImportRequest, db: Session = Depends(get_db)
):
    """Import Jira issues as User Stories. Read-only: nothing is written back to Jira."""
    project = project_or_404(project_id, db)
    try:
        jql = payload.jql or default_jira_jql(project)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        created, updated = import_jira_stories(db, project, jql, payload.max_results)
    except jira.JiraNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except jira.JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if created or updated:
        project.jira_connection = "connected"
        db.commit()

    return schemas.JiraImportResult(
        imported=len(created), updated=len(updated), story_ids=created + updated, jql=jql
    )


# --- gherkin -------------------------------------------------------------------------


@router.get("/gherkin", response_model=list[schemas.GherkinScenarioRead])
def list_gherkin(
    project_id: str | None = None,
    story_id: str | None = None,
    feature: str | None = None,
    scenario_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    statement = select(models.GherkinScenario)
    if project_id:
        statement = statement.where(models.GherkinScenario.project_id == project_id)
    if story_id:
        statement = statement.where(models.GherkinScenario.user_story_id == story_id)
    if feature:
        statement = statement.where(models.GherkinScenario.feature == feature)
    if scenario_status and scenario_status != "all":
        statement = statement.where(models.GherkinScenario.scenario_status == scenario_status)
    rows = db.scalars(statement.order_by(models.GherkinScenario.id))
    return [serializers.scenario(row) for row in rows]


def scenario_or_404(scenario_id: str, db: Session) -> models.GherkinScenario:
    scenario = db.get(models.GherkinScenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Gherkin scenario not found")
    return scenario


@router.patch("/gherkin/{scenario_id}", response_model=schemas.GherkinScenarioRead)
def update_gherkin(
    scenario_id: str, payload: schemas.GherkinScenarioPatch, db: Session = Depends(get_db)
):
    scenario = scenario_or_404(scenario_id, db)
    for field in ("feature", "scenario", "given", "when", "then"):
        value = getattr(payload, field)
        if value is not None:
            setattr(scenario, field, value)
    if payload.status is not None:
        scenario.scenario_status = payload.status
    db.commit()
    db.refresh(scenario)
    return serializers.scenario(scenario)


@router.post("/gherkin/{scenario_id}/validate", response_model=schemas.GherkinScenarioRead)
def validate_gherkin(scenario_id: str, db: Session = Depends(get_db)):
    """Structural validation: a scenario needs at least one Given, When and Then."""
    scenario = scenario_or_404(scenario_id, db)
    complete = bool(scenario.given) and bool(scenario.when) and bool(scenario.then)
    if scenario.scenario_status != "automated":
        scenario.scenario_status = "valid" if complete else "invalid"
    db.commit()
    db.refresh(scenario)
    return serializers.scenario(scenario)


@router.post(
    "/gherkin/{scenario_id}/playwright",
    response_model=schemas.JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_playwright(
    scenario_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Queue spec generation. On CPU inference this takes tens of seconds per scenario."""
    scenario = scenario_or_404(scenario_id, db)
    story = db.get(models.UserStory, scenario.user_story_id)
    if story is None or story.feature_id is None:
        raise HTTPException(
            status_code=409,
            detail="This scenario is not attached to an analysed feature, so selectors "
            "cannot be grounded in real code. Re-run an analysis first.",
        )
    background_tasks.add_task(generate_playwright_for_scenario, scenario_id)
    return schemas.JobRead(job_id=scenario_id, status="queued", progress=0)


# --- tests ---------------------------------------------------------------------------


@router.get("/tests", response_model=list[schemas.PlaywrightTestRead])
def list_tests(
    project_id: str | None = None,
    story_id: str | None = None,
    test_status: str | None = Query(default=None, alias="status"),
    origin: str | None = None,
    db: Session = Depends(get_db),
):
    statement = select(models.PlaywrightTest)
    if project_id:
        statement = statement.where(models.PlaywrightTest.project_id == project_id)
    if story_id:
        statement = statement.where(models.PlaywrightTest.user_story_id == story_id)
    if test_status and test_status != "all":
        statement = statement.where(models.PlaywrightTest.test_status == test_status)
    rows = list(db.scalars(statement.order_by(models.PlaywrightTest.id)))
    stories = {
        row.user_story_id: db.get(models.UserStory, row.user_story_id)
        for row in rows
        if row.user_story_id
    }
    serialised = [serializers.test(row, stories.get(row.user_story_id)) for row in rows]
    # Filtered after serialisation: "code" versus "jira" is a property of the story a
    # test was generated from, not a column on the test itself.
    if origin and origin != "all":
        serialised = [item for item in serialised if item.origin == origin]
    return serialised


@router.get("/tests/{test_id}", response_model=schemas.PlaywrightTestDetailRead)
def get_test(test_id: str, db: Session = Depends(get_db)):
    test = db.get(models.PlaywrightTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Playwright test not found")
    story = db.get(models.UserStory, test.user_story_id) if test.user_story_id else None
    project = db.get(models.Project, test.project_id)
    return serializers.test_detail(test, story, project.repository_path if project else None)


@router.post(
    "/tests/{test_id}/run",
    response_model=schemas.JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_test(test_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Queue a real `npx playwright test` run of this spec, in the analysed repository."""
    test = db.get(models.PlaywrightTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Playwright test not found")
    if test.test_status == "running":
        raise HTTPException(status_code=409, detail="Ce test est déjà en cours d'exécution.")
    # Opened before the task is queued, so this response can name the run to watch and a
    # client polling straight after sees `running` rather than the previous verdict.
    run = queue_run(db, test)
    background_tasks.add_task(run_playwright_test, run.id)
    return schemas.JobRead(job_id=run.id, status="running", progress=0)


@router.post(
    "/tests/{test_id}/regenerate",
    response_model=schemas.JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_test(
    test_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    test = db.get(models.PlaywrightTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Playwright test not found")
    # Regeneration writes the spec file. A discovered test is its author's work, not the
    # engine's, and there is no scenario to regenerate it from: refuse rather than
    # overwrite. The UI disables the button, but the file's safety cannot depend on that.
    if test.origin == "discovered" or not test.gherkin_scenario_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Ce test existait déjà dans le dépôt : il n'a pas été généré à partir d'un "
                "scénario Gherkin et le régénérer écraserait le fichier de son auteur."
            ),
        )
    background_tasks.add_task(generate_playwright_for_scenario, test.gherkin_scenario_id)
    return schemas.JobRead(job_id=test.gherkin_scenario_id, status="queued", progress=0)


# --- runs ----------------------------------------------------------------------------


@router.get("/runs", response_model=list[schemas.TestRunRead])
def list_runs(
    project_id: str | None = None,
    test_id: str | None = None,
    run_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Recent executions, newest first — the history behind each test's latest verdict."""
    statement = select(models.TestRun)
    if project_id:
        statement = statement.where(models.TestRun.project_id == project_id)
    if test_id:
        statement = statement.where(models.TestRun.test_id == test_id)
    if run_status and run_status != "all":
        statement = statement.where(models.TestRun.run_status == run_status)
    rows = db.scalars(statement.order_by(models.TestRun.started_at.desc()).limit(limit))
    return [serializers.run(row) for row in rows]


@router.get("/runs/{run_id}", response_model=schemas.TestRunDetailRead)
def get_run(run_id: str, since: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    """One execution, with the output produced after line `since`.

    A client watching a run in progress passes back the `lineCount` it already holds, so
    each poll carries only what is new rather than the whole log again.
    """
    row = db.get(models.TestRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Test run not found")
    return serializers.run_detail(row, since)


# --- coverage & dashboard ------------------------------------------------------------


@router.get("/coverage", response_model=schemas.CoverageReportRead)
def get_coverage(project_id: str | None = None, db: Session = Depends(get_db)):
    if project_id:
        project_or_404(project_id, db)
    return reporting.coverage_report(db, project_id)


@router.get("/dashboard", response_model=schemas.DashboardSummaryRead)
def get_dashboard(project_id: str | None = None, db: Session = Depends(get_db)):
    if project_id:
        project_or_404(project_id, db)
    return reporting.dashboard_summary(db, project_id)
