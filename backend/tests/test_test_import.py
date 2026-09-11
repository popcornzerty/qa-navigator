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


def _story(db, project_id: str, story_id: str, status: str = "approved"):
    from qa_engine.models import AcceptanceCriterion, UserStory

    story = UserStory(
        id=story_id, project_id=project_id, title="Une exigence", story_status=status
    )
    db.add(story)
    db.flush()
    db.add(
        AcceptanceCriterion(
            id=f"{story_id}-AC-01", user_story_id=story_id, text="un critère", covered=False
        )
    )
    db.commit()
    return story


def test_an_imported_test_can_be_attached_to_a_requirement(tmp_path: Path):
    """Imported tests prove real behaviour and counted nowhere. The link is the statement
    that one of them verifies a given requirement — a person's to make, never inferred."""
    from qa_engine.database import SessionLocal
    from qa_engine.models import AcceptanceCriterion, PlaywrightTest

    repo = _repository(tmp_path, "linking")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Linking")
        test_id = client.get(f"{PREFIX}/tests?project_id={project_id}").json()[0]["id"]

        db = SessionLocal()
        try:
            _story(db, project_id, "US-LINK")
        finally:
            db.close()

        # Before the link, the requirement claims nothing.
        report = client.get(f"{PREFIX}/coverage?project_id={project_id}").json()
        assert report["coverage"] == 0.0

        linked = client.patch(f"{PREFIX}/tests/{test_id}/story", json={"storyId": "US-LINK"})
        assert linked.status_code == 200
        assert linked.json()["userStoryId"] == "US-LINK"

        # Attached but never run: still nothing proven.
        assert client.get(f"{PREFIX}/coverage?project_id={project_id}").json()["coverage"] == 0.0

        db = SessionLocal()
        try:
            db.get(PlaywrightTest, test_id).test_status = "passed"
            db.commit()
            from qa_engine.services import link_test_to_story

            link_test_to_story(db, db.get(PlaywrightTest, test_id), "US-LINK")
            assert db.get(AcceptanceCriterion, "US-LINK-AC-01").covered is True
        finally:
            db.close()

        assert client.get(f"{PREFIX}/coverage?project_id={project_id}").json()["coverage"] == 100.0


def test_detaching_a_test_takes_the_coverage_with_it(tmp_path: Path):
    from qa_engine.database import SessionLocal
    from qa_engine.models import AcceptanceCriterion, PlaywrightTest
    from qa_engine.services import link_test_to_story

    repo = _repository(tmp_path, "detach")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Detach")
        test_id = client.get(f"{PREFIX}/tests?project_id={project_id}").json()[0]["id"]

        db = SessionLocal()
        try:
            _story(db, project_id, "US-DETACH")
            db.get(PlaywrightTest, test_id).test_status = "passed"
            db.commit()
            link_test_to_story(db, db.get(PlaywrightTest, test_id), "US-DETACH")
            assert db.get(AcceptanceCriterion, "US-DETACH-AC-01").covered is True
        finally:
            db.close()

        client.patch(f"{PREFIX}/tests/{test_id}/story", json={"storyId": None})
        assert client.get(f"{PREFIX}/coverage?project_id={project_id}").json()["coverage"] == 0.0


def test_a_test_cannot_be_attached_across_projects(tmp_path: Path):
    from qa_engine.database import SessionLocal

    repo = _repository(tmp_path, "cross-a")
    other = _repository(tmp_path, "cross-b")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Cross A")
        other_id = _create_and_analyse(client, other, "Cross B")
        test_id = client.get(f"{PREFIX}/tests?project_id={project_id}").json()[0]["id"]

        db = SessionLocal()
        try:
            _story(db, other_id, "US-OTHER")
        finally:
            db.close()

        response = client.patch(f"{PREFIX}/tests/{test_id}/story", json={"storyId": "US-OTHER"})
        assert response.status_code == 422


def test_a_generated_test_stops_claiming_a_scenario_that_changed_meaning(tmp_path: Path):
    """Story ids are handed out in order, so a backlog that changes shape renumbers it.

    A spec generated from "US-006-SC-1 — Ouvrir le formulaire de connexion" kept that id
    after the next analysis gave it to a different scenario: the file tested one thing and
    reported against another.
    """
    from qa_engine.database import SessionLocal
    from qa_engine.models import GherkinScenario, PlaywrightTest, UserStory
    from qa_engine.services import _detach_stale_generated_tests

    repo = _repository(tmp_path, "renumbered")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Renumbered")

        db = SessionLocal()
        try:
            db.add(UserStory(id="US-020", project_id=project_id, title="Une exigence"))
            db.add(
                GherkinScenario(
                    id="US-020-SC-1",
                    user_story_id="US-020",
                    project_id=project_id,
                    feature="Domaine",
                    scenario="Accéder aux conditions générales",
                )
            )
            # Written from what that id used to mean.
            db.add(
                PlaywrightTest(
                    id="gen-1",
                    project_id=project_id,
                    user_story_id="US-020",
                    gherkin_scenario_id="US-020-SC-1",
                    scenario="Ouvrir le formulaire de connexion",
                    file="e2e/generated/us-020.spec.ts",
                    origin="code",
                )
            )
            # And one whose scenario was deleted outright.
            db.add(
                PlaywrightTest(
                    id="gen-2",
                    project_id=project_id,
                    user_story_id="US-020",
                    gherkin_scenario_id="US-999-SC-1",
                    scenario="Se connecter avec succès",
                    file="e2e/generated/us-999.spec.ts",
                    origin="code",
                )
            )
            db.commit()

            assert _detach_stale_generated_tests(db, project_id) == 2
            for test_id in ("gen-1", "gen-2"):
                detached = db.get(PlaywrightTest, test_id)
                assert detached.user_story_id is None
                assert detached.gherkin_scenario_id is None
        finally:
            db.close()


def test_a_generated_test_that_still_matches_its_scenario_is_left_alone(tmp_path: Path):
    from qa_engine.database import SessionLocal
    from qa_engine.models import GherkinScenario, PlaywrightTest, UserStory
    from qa_engine.services import _detach_stale_generated_tests

    repo = _repository(tmp_path, "unchanged")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Unchanged")

        db = SessionLocal()
        try:
            db.add(UserStory(id="US-021", project_id=project_id, title="Une exigence"))
            db.add(
                GherkinScenario(
                    id="US-021-SC-1",
                    user_story_id="US-021",
                    project_id=project_id,
                    feature="Domaine",
                    scenario="Ouvrir le formulaire de connexion",
                )
            )
            db.add(
                PlaywrightTest(
                    id="gen-3",
                    project_id=project_id,
                    user_story_id="US-021",
                    gherkin_scenario_id="US-021-SC-1",
                    scenario="Ouvrir le formulaire de connexion",
                    file="e2e/generated/us-021.spec.ts",
                    origin="code",
                )
            )
            db.commit()

            assert _detach_stale_generated_tests(db, project_id) == 0
            assert db.get(PlaywrightTest, "gen-3").user_story_id == "US-021"
        finally:
            db.close()


def test_an_imported_test_is_never_detached_by_the_renumbering(tmp_path: Path):
    """A discovered test records the title its own file gives it, which has nothing to do
    with a scenario. Comparing the two would detach every hand-made link."""
    from qa_engine.database import SessionLocal
    from qa_engine.models import PlaywrightTest
    from qa_engine.services import _detach_stale_generated_tests, link_test_to_story

    repo = _repository(tmp_path, "spared")
    with TestClient(app) as client:
        project_id = _create_and_analyse(client, repo, "Spared")
        test_id = client.get(f"{PREFIX}/tests?project_id={project_id}").json()[0]["id"]

        db = SessionLocal()
        try:
            _story(db, project_id, "US-022")
            link_test_to_story(db, db.get(PlaywrightTest, test_id), "US-022")
            assert _detach_stale_generated_tests(db, project_id) == 0
            assert db.get(PlaywrightTest, test_id).user_story_id == "US-022"
        finally:
            db.close()

def test_a_renamed_scenario_does_not_leave_its_old_spec_running(tmp_path: Path):
    """The file name comes from the scenario title, so renaming one makes the engine write
    a new file and abandon the old. The abandoned copy kept running and kept failing, with
    nothing to tell it apart from a real regression."""
    from qa_engine.playwright_gen import GENERATED_MARKER
    from qa_engine.services import _discard_superseded_spec

    repo = tmp_path / "repo"
    (repo / "e2e").mkdir(parents=True)
    old = repo / "e2e" / "us-006-ouvrir-le-formulaire.spec.ts"
    old.write_text(f"{GENERATED_MARKER}\ntest('x', async () => {{}});\n", encoding="utf-8")

    _discard_superseded_spec(repo, "e2e/us-006-ouvrir-le-formulaire.spec.ts", "e2e/us-006-cgu.spec.ts")
    assert not old.exists()


def test_a_spec_the_engine_did_not_write_is_left_alone(tmp_path: Path):
    """The marker in the first line is what proves ownership. A file someone wrote by hand
    stays, even when the database points at it."""
    from qa_engine.services import _discard_superseded_spec

    repo = tmp_path / "repo"
    (repo / "e2e").mkdir(parents=True)
    handwritten = repo / "e2e" / "portefeuille.spec.ts"
    handwritten.write_text("import { test } from '@playwright/test';\n", encoding="utf-8")

    _discard_superseded_spec(repo, "e2e/portefeuille.spec.ts", "e2e/autre.spec.ts")
    assert handwritten.exists()


def test_rewriting_the_same_file_keeps_it(tmp_path: Path):
    from qa_engine.playwright_gen import GENERATED_MARKER
    from qa_engine.services import _discard_superseded_spec

    repo = tmp_path / "repo"
    (repo / "e2e").mkdir(parents=True)
    same = repo / "e2e" / "us-006.spec.ts"
    same.write_text(f"{GENERATED_MARKER}\n", encoding="utf-8")

    _discard_superseded_spec(repo, "e2e/us-006.spec.ts", "e2e/us-006.spec.ts")
    assert same.exists()


def test_a_missing_previous_file_is_not_an_error(tmp_path: Path):
    from qa_engine.services import _discard_superseded_spec

    _discard_superseded_spec(tmp_path, "e2e/parti.spec.ts", "e2e/nouveau.spec.ts")
    _discard_superseded_spec(tmp_path, None, "e2e/nouveau.spec.ts")
