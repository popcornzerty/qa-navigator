from pathlib import Path

from fastapi.testclient import TestClient

from qa_engine.main import app

PREFIX = "/api/v1"


def _repository(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Cart.tsx").write_text(
        'export const CartPage = () => <Route path="/cart" />;\n'
        'export const CartLine = () => <li data-testid="cart-line" />;\n'
        'const total = fetch("/api/cart");\n',
        encoding="utf-8",
    )
    return repo


def _create_project(client: TestClient, repo: Path, name: str) -> str:
    response = client.post(
        f"{PREFIX}/projects",
        json={"name": name, "repository": str(repo), "repositorySource": "local"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_project_analysis_and_features(tmp_path: Path):
    repo = _repository(tmp_path, "frontend")

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert f"{PREFIX}/projects" in client.get("/openapi.json").json()["paths"]

        project_id = _create_project(client, repo, "Frontend")
        project = client.get(f"{PREFIX}/projects/{project_id}").json()
        assert project["repository"] == str(repo.resolve())
        assert project["branch"] == "local"
        assert project["status"] == "never_analyzed"

        analysis = client.post(f"{PREFIX}/analyses", json={"project_id": project_id})
        assert analysis.status_code == 202
        job_id = analysis.json()["jobId"]

        job = client.get(f"{PREFIX}/jobs/{job_id}").json()
        assert job["status"] == "completed"
        # Generation steps are not wired in this fixture, so the pipeline stops before
        # them. Derived rather than hard-coded: adding a step should not fail this test.
        keys = [step["key"] for step in job["steps"]]
        analysed = keys.index("stories")
        assert job["progress"] == round(analysed / len(keys) * 100)
        assert [step["key"] for step in job["steps"]][:3] == [
            "repository",
            "architecture",
            "routes",
        ]

        features = client.get(f"{PREFIX}/features?project_id={project_id}").json()
        assert features, "the analysis should produce at least one functional domain"
        assert {"id", "projectId", "name", "description", "confidence", "sourceFiles", "status"} <= set(
            features[0]
        )
        assert "Panier" in {feature["name"] for feature in features}


def test_analyses_current_is_not_matched_as_an_analysis_id(tmp_path: Path):
    """Regression: /analyses/current was shadowed by /analyses/{analysis_id}."""
    repo = _repository(tmp_path, "ordering")

    with TestClient(app) as client:
        project_id = _create_project(client, repo, "Ordering")
        assert (
            client.get(f"{PREFIX}/analyses/current?project_id={project_id}").status_code == 404
        )  # no analysis yet, but the route resolved

        client.post(f"{PREFIX}/analyses", json={"project_id": project_id})
        current = client.get(f"{PREFIX}/analyses/current?project_id={project_id}")
        assert current.status_code == 200
        assert current.json()["projectId"] == project_id


def test_settings_round_trip(tmp_path: Path):
    repo = _repository(tmp_path, "settings")

    with TestClient(app) as client:
        project_id = _create_project(client, repo, "Settings")

        settings = client.get(f"{PREFIX}/projects/{project_id}/settings").json()
        assert settings["playwright"]["testDirectory"] == "tests"
        assert settings["jira"]["status"] == "not_connected"

        updated = client.patch(
            f"{PREFIX}/projects/{project_id}/settings",
            json={
                "branch": "develop",
                "jira": {"status": "connected", "projectKey": "ATL"},
                "playwright": {
                    "testDirectory": "e2e",
                    "baseUrl": "http://localhost:3000",
                    "browsers": ["chromium", "firefox"],
                    "headless": False,
                },
            },
        )
        assert updated.status_code == 200
        payload = updated.json()
        assert payload["branch"] == "develop"
        assert payload["jira"]["projectKey"] == "ATL"
        assert payload["playwright"]["browsers"] == ["chromium", "firefox"]


def test_empty_collections_match_the_frontend_contract(tmp_path: Path):
    repo = _repository(tmp_path, "contract")

    with TestClient(app) as client:
        project_id = _create_project(client, repo, "Contract")

        assert client.get(f"{PREFIX}/stories?project_id={project_id}").json() == []
        assert client.get(f"{PREFIX}/gherkin?project_id={project_id}").json() == []
        assert client.get(f"{PREFIX}/tests?project_id={project_id}").json() == []

        coverage = client.get(f"{PREFIX}/coverage?project_id={project_id}").json()
        assert coverage["userStories"] == {"total": 0, "withGherkin": 0, "automated": 0}
        assert coverage["coverage"] == 0

        dashboard = client.get(f"{PREFIX}/dashboard?project_id={project_id}").json()
        assert dashboard["userStories"] == 0
        assert isinstance(dashboard["activity"], list)

        stats = client.get(f"{PREFIX}/projects/{project_id}/stats").json()
        assert set(stats) == {
            "features",
            "userStories",
            "gherkinScenarios",
            "playwrightTests",
            "coverage",
        }


def test_unimplemented_actions_report_501(tmp_path: Path):
    """Actions the UI exposes but the engine cannot honour yet must say so explicitly."""
    repo = _repository(tmp_path, "unimplemented")

    with TestClient(app) as client:
        _create_project(client, repo, "Unimplemented")
        assert client.post(f"{PREFIX}/tests/pw-001/run").status_code == 404
        assert client.get(f"{PREFIX}/stories/US-404").status_code == 404


def test_reanalysis_keeps_stories_attached_to_their_feature(tmp_path: Path):
    """Features are rebuilt on every analysis; stories must not be left orphaned.

    A dangling feature_id breaks nothing visibly — the feature name is denormalised — but
    Playwright generation stops working, since it reads its selector anchors there.
    """
    from sqlalchemy import select

    from qa_engine.database import SessionLocal
    from qa_engine.models import Feature, UserStory

    repo = _repository(tmp_path, "relink")

    with TestClient(app) as client:
        project_id = _create_project(client, repo, "Relink")
        client.post(f"{PREFIX}/analyses", json={"project_id": project_id})

        db = SessionLocal()
        try:
            feature = db.scalar(select(Feature).where(Feature.project_id == project_id))
            assert feature is not None
            db.add(
                UserStory(
                    id="US-900",
                    project_id=project_id,
                    feature_id=feature.id,
                    feature_name=feature.name,
                    title="Story attachée",
                )
            )
            db.commit()
        finally:
            db.close()

        client.post(f"{PREFIX}/analyses", json={"project_id": project_id, "force": True})

        db = SessionLocal()
        try:
            story = db.get(UserStory, "US-900")
            live = {row.id for row in db.scalars(select(Feature).where(Feature.project_id == project_id))}
            assert story.feature_id in live, "the story lost its feature after re-analysis"
        finally:
            db.close()


def test_an_analysis_interrupted_by_a_restart_is_not_left_running(tmp_path: Path):
    """In-process jobs die with the process; their row does not, and nothing resumes them."""
    from qa_engine.database import SessionLocal
    from qa_engine.models import Analysis, Project
    from qa_engine.services import initial_steps, recover_interrupted_analyses

    repo = _repository(tmp_path, "interrupted")

    with TestClient(app) as client:
        project_id = _create_project(client, repo, "Interrupted")

    db = SessionLocal()
    try:
        steps = initial_steps()
        stories_step = next(i for i, step in enumerate(steps) if step["key"] == "stories")
        steps[stories_step]["status"] = "running"
        analysis = Analysis(
            project_id=project_id, status="running", progress=75, steps=steps
        )
        db.add(analysis)
        project = db.get(Project, project_id)
        project.project_status = "analyzing"
        db.commit()
        analysis_id = analysis.id

        assert recover_interrupted_analyses(db) == 1

        db.expire_all()
        recovered = db.get(Analysis, analysis_id)
        assert recovered.status == "failed"
        assert "interrompue" in recovered.error.lower()
        assert recovered.completed_at is not None
        # The step that was mid-flight says so, instead of spinning for ever.
        assert [s for s in recovered.steps if s["key"] == "stories"][0]["status"] == "failed"
        # And the project is no longer stuck showing an analysis in progress.
        assert db.get(Project, project_id).project_status != "analyzing"
    finally:
        db.close()


def test_recovery_leaves_finished_analyses_alone(tmp_path: Path):
    from qa_engine.database import SessionLocal
    from qa_engine.models import Analysis
    from qa_engine.services import recover_interrupted_analyses

    repo = _repository(tmp_path, "finished")

    with TestClient(app) as client:
        project_id = _create_project(client, repo, "Finished")

    db = SessionLocal()
    try:
        analysis = Analysis(project_id=project_id, status="completed", progress=100, steps=[])
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id

        recover_interrupted_analyses(db)

        db.expire_all()
        assert db.get(Analysis, analysis_id).status == "completed"
    finally:
        db.close()


def test_a_run_is_kept_after_the_next_one_replaces_it(tmp_path: Path):
    """Only the latest verdict was stored, so a flaky test looked like whatever it did last."""
    from qa_engine.database import SessionLocal
    from qa_engine.models import PlaywrightTest, TestRun
    from qa_engine.services import queue_run

    repo = _repository(tmp_path, "history-runs")
    with TestClient(app) as client:
        project_id = _create_project(client, repo, "History runs")

        db = SessionLocal()
        try:
            test = PlaywrightTest(
                id="pw-hist",
                project_id=project_id,
                file="tests/a.spec.ts",
                scenario="un test",
                origin="discovered",
            )
            db.add(test)
            db.commit()
            first = queue_run(db, test)
            first.run_status, first.duration_ms = "failed", 120
            db.commit()
            test.test_status = "not_run"
            db.commit()
            second = queue_run(db, test)
            second.run_status, second.duration_ms = "passed", 90
            db.commit()
            ids = [first.id, second.id]
        finally:
            db.close()

        runs = client.get(f"{PREFIX}/runs?test_id=pw-hist").json()
        assert {item["id"] for item in runs} == set(ids)
        # Newest first, so the list reads as a history.
        assert runs[0]["id"] == ids[1]
        assert {item["status"] for item in runs} == {"failed", "passed"}

        failed_only = client.get(f"{PREFIX}/runs?test_id=pw-hist&status=failed").json()
        assert [item["id"] for item in failed_only] == [ids[0]]


def test_a_run_log_is_served_from_an_offset(tmp_path: Path):
    """A client watching a run asks only for what it has not seen."""
    from qa_engine.database import SessionLocal
    from qa_engine.models import PlaywrightTest, TestRun

    repo = _repository(tmp_path, "run-log")
    with TestClient(app) as client:
        project_id = _create_project(client, repo, "Run log")

        db = SessionLocal()
        try:
            test = PlaywrightTest(
                id="pw-log", project_id=project_id, file="tests/a.spec.ts", scenario="un test"
            )
            db.add(test)
            run = TestRun(
                test_id="pw-log",
                project_id=project_id,
                run_status="running",
                log="ligne 1\nligne 2\nligne 3",
            )
            db.add(run)
            db.commit()
            run_id = run.id
        finally:
            db.close()

        whole = client.get(f"{PREFIX}/runs/{run_id}").json()
        assert whole["log"].splitlines() == ["ligne 1", "ligne 2", "ligne 3"]
        assert whole["lineCount"] == 3

        rest = client.get(f"{PREFIX}/runs/{run_id}?since=2").json()
        assert rest["log"].splitlines() == ["ligne 3"]
        assert rest["offset"] == 2
        assert rest["lineCount"] == 3

        # Asking from the end returns nothing new rather than repeating the log.
        assert client.get(f"{PREFIX}/runs/{run_id}?since=3").json()["log"] == ""


def test_a_run_interrupted_by_a_restart_is_released(tmp_path: Path):
    """Otherwise the UI polls a subprocess that died with the previous process."""
    from qa_engine.database import SessionLocal
    from qa_engine.models import PlaywrightTest, TestRun
    from qa_engine.services import recover_interrupted_runs

    repo = _repository(tmp_path, "run-recovery")
    with TestClient(app) as client:
        project_id = _create_project(client, repo, "Run recovery")

    db = SessionLocal()
    try:
        test = PlaywrightTest(
            id="pw-stuck",
            project_id=project_id,
            file="tests/a.spec.ts",
            scenario="un test",
            test_status="running",
        )
        db.add(test)
        run = TestRun(test_id="pw-stuck", project_id=project_id, run_status="running")
        db.add(run)
        db.commit()
        run_id = run.id

        assert recover_interrupted_runs(db) == 1

        db.expire_all()
        assert db.get(TestRun, run_id).run_status == "not_run"
        assert db.get(TestRun, run_id).finished_at is not None
        assert "interrompue" in db.get(TestRun, run_id).error_message.lower()
        assert db.get(PlaywrightTest, "pw-stuck").test_status == "not_run"
    finally:
        db.close()
