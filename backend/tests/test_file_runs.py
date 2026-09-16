"""Running every test of one spec file, and giving each its own verdict."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from qa_engine import execution
from qa_engine.main import app

PREFIX = "/api/v1"

CONFIG = """
import { defineConfig } from "@playwright/test";
export default defineConfig({ testDir: "e2e" });
"""

SUITE = """
import { expect, test } from "@playwright/test";
test.describe("Portefeuille", () => {
  test("la valorisation totale s'affiche", async ({ page }) => { await page.goto("/"); });
  test("une ligne se supprime", async ({ page }) => { await page.goto("/"); });
  test("un export se télécharge", async ({ page }) => { await page.goto("/"); });
});
"""


def _project(client: TestClient, tmp_path: Path, name: str) -> str:
    repo = tmp_path / name
    (repo / "src").mkdir(parents=True)
    (repo / "e2e").mkdir()
    (repo / "src" / "App.tsx").write_text("export const App = () => <main />;", encoding="utf-8")
    (repo / "playwright.config.ts").write_text(CONFIG, encoding="utf-8")
    (repo / "e2e" / "portefeuille.spec.ts").write_text(SUITE, encoding="utf-8")
    project_id = client.post(
        f"{PREFIX}/projects",
        json={"name": name, "repository": str(repo), "repositorySource": "local"},
    ).json()["id"]
    client.post(f"{PREFIX}/analyses", json={"project_id": project_id})
    return project_id


def test_the_describe_chain_is_read_from_a_playwright_report(tmp_path: Path):
    """The report nests file → describe → spec; the verdict title must be the selector
    discovery stored, `Portefeuille › …`, not the file name."""
    report = {
        "suites": [
            {
                "title": "portefeuille.spec.ts",
                "specs": [],
                "suites": [
                    {
                        "title": "Portefeuille",
                        "suites": [],
                        "specs": [
                            {
                                "title": "une ligne se supprime",
                                "file": "portefeuille.spec.ts",
                                "tests": [{"results": [{"status": "failed", "duration": 12,
                                                        "error": {"message": "boom"}}]}],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    outcome = execution.parse_report(report, tmp_path)
    assert [(v.title, v.status, v.error_message) for v in outcome.tests] == [
        ("Portefeuille › une ligne se supprime", "failed", "boom")
    ]


def test_a_file_run_gives_each_test_its_own_verdict(tmp_path: Path, monkeypatch):
    """After fixing a feature a QA engineer reruns its file, not its tests one by one. The
    run belongs to the file, and each test takes the verdict the report gives it."""
    calls = []

    def fake_run_spec(repository_path, spec_file, **kwargs):
        calls.append((spec_file, kwargs.get("grep")))
        return execution.ExecutionOutcome(
            status="failed",
            total=2,
            passed=1,
            failed=1,
            tests=[
                execution.TestVerdict("Portefeuille › la valorisation totale s'affiche",
                                      spec_file, "passed", 40),
                execution.TestVerdict("Portefeuille › une ligne se supprime",
                                      spec_file, "failed", 55, "attendu 3 lignes"),
            ],
        )

    monkeypatch.setattr(execution, "run_spec", fake_run_spec)

    with TestClient(app) as client:
        project_id = _project(client, tmp_path, "filerun")
        response = client.post(
            f"{PREFIX}/projects/{project_id}/file-runs", json={"file": "e2e/portefeuille.spec.ts"}
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["jobId"]

        # One Playwright process for the whole file, with no test selected.
        assert calls == [("e2e/portefeuille.spec.ts", None)]

        by_title = {
            t["scenario"]: t
            for t in client.get(f"{PREFIX}/tests?project_id={project_id}").json()
        }
        assert by_title["Portefeuille › la valorisation totale s'affiche"]["status"] == "passed"
        failed = by_title["Portefeuille › une ligne se supprime"]
        assert failed["status"] == "failed"
        assert failed["result"]["errorMessage"] == "attendu 3 lignes"
        # Absent from the report: its previous verdict is kept, not guessed.
        assert by_title["Portefeuille › un export se télécharge"]["status"] == "not_run"

        run = client.get(f"{PREFIX}/runs/{run_id}").json()
        assert run["testId"] is None
        assert run["file"] == "e2e/portefeuille.spec.ts"
        assert (run["status"], run["passed"], run["failed"]) == ("failed", 1, 1)


def test_an_unknown_file_is_refused(tmp_path: Path):
    with TestClient(app) as client:
        project_id = _project(client, tmp_path, "unknown")
        response = client.post(
            f"{PREFIX}/projects/{project_id}/file-runs", json={"file": "e2e/absent.spec.ts"}
        )
        assert response.status_code == 404


def test_a_file_already_running_is_not_started_twice(tmp_path: Path):
    from qa_engine.database import SessionLocal
    from qa_engine.models import PlaywrightTest

    with TestClient(app) as client:
        project_id = _project(client, tmp_path, "twice")
        db = SessionLocal()
        try:
            row = db.query(PlaywrightTest).filter_by(project_id=project_id).first()
            row.test_status = "running"
            db.commit()
        finally:
            db.close()
        response = client.post(
            f"{PREFIX}/projects/{project_id}/file-runs", json={"file": "e2e/portefeuille.spec.ts"}
        )
        assert response.status_code == 409
