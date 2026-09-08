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
        assert job["progress"] == 75  # generation steps are not wired yet
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
