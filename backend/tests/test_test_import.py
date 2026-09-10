"""Importing a repository's own test suite into the backlog of runnable tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from qa_engine.main import app

PREFIX = "/api/v1"

CONFIG = """
import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "e2e",
  projects: [
    { name: "bouchonne", testDir: "e2e" },
    { name: "reel", testDir: "e2e-reel" },
  ],
});
"""

SUITE = """
import { expect, test } from "@playwright/test";

test.describe("Portefeuille", () => {
  test("la valorisation totale s'affiche", async ({ page }) => {
    await page.goto("/");
  });
  test("une ligne se supprime", async ({ page }) => {
    await page.goto("/");
  });
});
"""


def _repository(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    (repo / "frontend" / "src").mkdir(parents=True)
    (repo / "frontend" / "e2e").mkdir(parents=True)
    (repo / "frontend" / "src" / "Portfolio.tsx").write_text(
        'export const PortfolioPage = () => <Route path="/portfolio" />;\n'
        'export const Line = () => <li data-testid="line" />;\n',
        encoding="utf-8",
    )
    (repo / "frontend" / "playwright.config.ts").write_text(CONFIG, encoding="utf-8")
    (repo / "frontend" / "e2e" / "portefeuille.spec.ts").write_text(SUITE, encoding="utf-8")
    return repo


def _create_and_analyse(client: TestClient, repo: Path, name: str) -> str:
    response = client.post(
        f"{PREFIX}/projects",
        json={"name": name, "repository": str(repo), "repositorySource": "local"},
    )
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    assert client.post(f"{PREFIX}/analyses", json={"project_id": project_id}).status_code == 202
    return project_id


def test_an_existing_suite_is_imported_as_runnable_tests(tmp_path: Path):
    repo = _repository(tmp_path, "pea")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "PEA")

        tests = client.get(f"{PREFIX}/tests?project_id={project_id}").json()
        assert [item["scenario"] for item in tests] == [
            "Portefeuille › la valorisation totale s'affiche",
            "Portefeuille › une ligne se supprime",
        ]
        assert {item["origin"] for item in tests} == {"discovered"}
        # No story is invented to satisfy the schema.
        assert all(item["userStoryId"] is None for item in tests)


def test_a_test_file_is_never_read_as_a_functional_domain(tmp_path: Path):
    """The spec describes the product's tests, not the product."""
    repo = _repository(tmp_path, "domains")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Domains")

        features = client.get(f"{PREFIX}/features?project_id={project_id}").json()
        sources = [path for feature in features for path in feature["sourceFiles"]]
        assert sources, "the application code should still produce a domain"
        assert not any("e2e" in path or ".spec." in path for path in sources)


def test_reanalysis_keeps_the_history_of_a_test_that_is_still_there(tmp_path: Path):
    repo = _repository(tmp_path, "history")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "History")
        tests = client.get(f"{PREFIX}/tests?project_id={project_id}").json()
        kept_id = tests[0]["id"]

        from qa_engine.database import SessionLocal
        from qa_engine.models import PlaywrightTest

        db = SessionLocal()
        try:
            row = db.get(PlaywrightTest, kept_id)
            row.test_status = "passed"
            row.duration_ms = 1234
            db.commit()
        finally:
            db.close()

        assert client.post(f"{PREFIX}/analyses", json={"project_id": project_id}).status_code == 202

        after = client.get(f"{PREFIX}/tests?project_id={project_id}").json()
        survivor = next(item for item in after if item["id"] == kept_id)
        assert survivor["status"] == "passed"
        assert survivor["durationMs"] == 1234


def test_a_deleted_test_stops_being_listed(tmp_path: Path):
    repo = _repository(tmp_path, "removal")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Removal")
        assert len(client.get(f"{PREFIX}/tests?project_id={project_id}").json()) == 2

        (repo / "frontend" / "e2e" / "portefeuille.spec.ts").write_text(
            'import { test } from "@playwright/test";\n'
            'test("la valorisation totale s\'affiche", async ({ page }) => {});\n',
            encoding="utf-8",
        )
        assert client.post(f"{PREFIX}/analyses", json={"project_id": project_id}).status_code == 202

        remaining = client.get(f"{PREFIX}/tests?project_id={project_id}").json()
        assert [item["scenario"] for item in remaining] == ["la valorisation totale s'affiche"]


def test_a_generated_spec_is_not_imported_as_an_existing_one(tmp_path: Path):
    """The engine writes its specs into the analysed repository; it must not re-read them."""
    from qa_engine.playwright_gen import GENERATED_MARKER

    repo = _repository(tmp_path, "generated")
    body = 'test("Lancer l\'analyse", async ({ page }) => {});\n'
    spec = repo / "frontend" / "e2e" / "us-001-lancer.spec.ts"
    spec.write_text(f"{GENERATED_MARKER}\n{body}", encoding="utf-8")

    # Guard against a vacuous pass: without the marker this very file is imported.
    from qa_engine.discovery import extract_tests

    assert [item.title for item in extract_tests(body, "x.spec.ts")] == ["Lancer l'analyse"]

    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Generated")
        scenarios = [
            item["scenario"] for item in client.get(f"{PREFIX}/tests?project_id={project_id}").json()
        ]
        assert "Lancer l'analyse" not in scenarios


def test_tests_can_be_filtered_by_origin(tmp_path: Path):
    repo = _repository(tmp_path, "origins")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Origins")

        discovered = client.get(f"{PREFIX}/tests?project_id={project_id}&origin=discovered").json()
        assert len(discovered) == 2
        assert client.get(f"{PREFIX}/tests?project_id={project_id}&origin=code").json() == []


def test_discovered_tests_do_not_inflate_story_coverage(tmp_path: Path):
    repo = _repository(tmp_path, "coverage")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Coverage")

        report = client.get(f"{PREFIX}/coverage?project_id={project_id}").json()
        # They are real automation and are counted as such...
        assert report["automation"]["total"] == 2
        # ...but they prove nothing about a stated requirement.
        assert report["userStories"]["automated"] == 0
        # And with no owned requirement, there is no ratio to report at all.
        assert report["coverage"] is None
        assert report["baseline"] == "none"


def test_regenerating_a_hand_written_test_is_refused(tmp_path: Path):
    """The spec file belongs to its author; the engine must not overwrite it."""
    repo = _repository(tmp_path, "protect")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Protect")
        test_id = client.get(f"{PREFIX}/tests?project_id={project_id}").json()[0]["id"]

        response = client.post(f"{PREFIX}/tests/{test_id}/regenerate")
        assert response.status_code == 409
        assert "écraserait" in response.json()["detail"]

        # And the file is untouched.
        spec = repo / "frontend" / "e2e" / "portefeuille.spec.ts"
        assert spec.read_text(encoding="utf-8") == SUITE
