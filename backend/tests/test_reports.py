"""Reading a test report a project's own tooling produced."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qa_engine import reports
from qa_engine.main import app

PREFIX = "/api/v1"

PYTEST_REPORT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="4" failures="1" errors="0" skipped="1" time="12.5">
    <testcase classname="tests.test_accounts.TestLogin" name="test_ouverture_de_session" time="0.019"/>
    <testcase classname="tests.test_accounts.TestLogin" name="test_mot_de_passe_errone" time="0.004"/>
    <testcase classname="tests.test_portefeuille" name="test_valorisation" time="1.2">
      <failure message="assert 10 == 11">Traceback…</failure>
    </testcase>
    <testcase classname="tests.test_portefeuille" name="test_export_csv" time="0">
      <skipped message="pas de données"/>
    </testcase>
  </testsuite>
</testsuites>
"""

PLAYWRIGHT_REPORT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="2" failures="0" time="4.3">
  <testsuite name="portefeuille.spec.ts">
    <testcase name="Portefeuille › la valorisation totale s'affiche" classname="portefeuille.spec.ts" time="1.1"/>
    <testcase name="Portefeuille › une ligne se supprime" classname="portefeuille.spec.ts" time="0.9"/>
  </testsuite>
</testsuites>
"""


class TestParsing:
    def test_a_pytest_report_is_read(self):
        report = reports.parse(PYTEST_REPORT)
        assert len(report.tests) == 4
        assert report.counts == {"passed": 2, "failed": 1, "skipped": 1}
        assert report.duration_ms == 12_500

    def test_a_class_is_not_read_as_a_directory(self):
        """`tests.test_accounts.TestLogin` is a class inside a module, not a directory
        above it. Reading it as one turned 43 files into 196 and made a grouped inventory
        useless."""
        report = reports.parse(PYTEST_REPORT)
        assert {test.file for test in report.tests} == {
            "tests/test_accounts",
            "tests/test_portefeuille",
        }

    def test_a_windows_path_is_still_a_path(self):
        """A Windows runner writes `..\\e2e-reel\\x.setup.ts`, which holds no forward
        slash: the "is it a path" test failed and the dotted-module branch shredded it."""
        xml = (
            '<testsuite name="s" tests="1">'
            '<testcase classname="..\\e2e-reel\\connexion.setup.ts" name="ouvre une session"/>'
            "</testsuite>"
        )
        assert reports.parse(xml).tests[0].file == "../e2e-reel/connexion.setup.ts"

    def test_a_failure_carries_its_message(self):
        failed = next(t for t in reports.parse(PYTEST_REPORT).tests if t.status == "failed")
        assert failed.message is not None and "assert 10 == 11" in failed.message

    def test_a_bare_testsuite_is_accepted(self):
        xml = '<testsuite name="s" tests="1"><testcase classname="a" name="b" time="0.5"/></testsuite>'
        assert len(reports.parse(xml).tests) == 1

    def test_the_kind_is_decided_by_the_files(self):
        assert reports.kind_of(reports.parse(PYTEST_REPORT).tests) == "backend"
        assert reports.kind_of(reports.parse(PLAYWRIGHT_REPORT).tests) == "e2e"
        assert reports.framework_of(reports.parse(PYTEST_REPORT).tests) == "pytest"
        assert reports.framework_of(reports.parse(PLAYWRIGHT_REPORT).tests) == "playwright"

    def test_something_that_is_not_a_report_is_refused(self):
        for payload in ("<html><body>oops</body></html>", "not xml at all", "<testsuite/>"):
            with pytest.raises(reports.ReportError):
                reports.parse(payload)


CONFIG = """
import { defineConfig } from "@playwright/test";
export default defineConfig({ testDir: "e2e" });
"""

SUITE = """
import { expect, test } from "@playwright/test";
test.describe("Portefeuille", () => {
  test("la valorisation totale s'affiche", async ({ page }) => { await page.goto("/"); });
  test("une ligne se supprime", async ({ page }) => { await page.goto("/"); });
});
"""


def _repository(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    (repo / "frontend" / "src").mkdir(parents=True)
    (repo / "frontend" / "e2e").mkdir(parents=True)
    (repo / "frontend" / "src" / "Portfolio.tsx").write_text(
        'export const PortfolioPage = () => <Route path="/portfolio" />;\n', encoding="utf-8"
    )
    (repo / "frontend" / "playwright.config.ts").write_text(CONFIG, encoding="utf-8")
    (repo / "frontend" / "e2e" / "portefeuille.spec.ts").write_text(SUITE, encoding="utf-8")
    return repo


def _analysed(client: TestClient, repo: Path, name: str) -> str:
    response = client.post(
        f"{PREFIX}/projects",
        json={"name": name, "repository": str(repo), "repositorySource": "local"},
    )
    project_id = response.json()["id"]
    client.post(f"{PREFIX}/analyses", json={"project_id": project_id})
    return project_id


class TestIngestion:
    def test_a_report_updates_the_tests_discovery_already_found(self, tmp_path: Path):
        """The runner reports the path it was invoked with — `portefeuille.spec.ts` — for a
        file the engine recorded as `frontend/e2e/portefeuille.spec.ts`. Matching on the
        tail is what stops a report duplicating every row."""
        repo = _repository(tmp_path, "match")
        with TestClient(app) as client:
            project_id = _analysed(client, repo, "Match")
            before = client.get(f"{PREFIX}/tests?project_id={project_id}").json()
            assert len(before) == 2
            assert {t["status"] for t in before} == {"not_run"}

            posted = client.post(f"{PREFIX}/projects/{project_id}/reports", content=PLAYWRIGHT_REPORT)
            assert posted.status_code == 201, posted.text
            assert posted.json()["matched"] == 2
            assert posted.json()["created"] == 0

            after = client.get(f"{PREFIX}/tests?project_id={project_id}").json()
            assert len(after) == 2
            assert {t["status"] for t in after} == {"passed"}

    def test_a_backend_suite_the_repository_never_showed_is_recorded(self, tmp_path: Path):
        """A pytest suite is not something static discovery reads. Refusing to record it
        would leave the inventory quietly short of a thousand tests."""
        repo = _repository(tmp_path, "backend")
        with TestClient(app) as client:
            project_id = _analysed(client, repo, "Backend")

            posted = client.post(f"{PREFIX}/projects/{project_id}/reports", content=PYTEST_REPORT)
            assert posted.status_code == 201
            body = posted.json()
            assert body["created"] == 4
            assert body["kind"] == "backend"
            assert body["framework"] == "pytest"
            assert (body["passed"], body["failed"], body["skipped"]) == (2, 1, 1)

            backend = [
                t
                for t in client.get(f"{PREFIX}/tests?project_id={project_id}").json()
                if t["kind"] == "backend"
            ]
            assert len(backend) == 4

    def test_ingesting_the_same_report_twice_creates_nothing_new(self, tmp_path: Path):
        repo = _repository(tmp_path, "twice")
        with TestClient(app) as client:
            project_id = _analysed(client, repo, "Twice")
            client.post(f"{PREFIX}/projects/{project_id}/reports", content=PYTEST_REPORT)
            second = client.post(f"{PREFIX}/projects/{project_id}/reports", content=PYTEST_REPORT)
            assert second.json()["created"] == 0
            assert second.json()["matched"] == 4

    def test_a_file_that_is_not_a_report_is_refused(self, tmp_path: Path):
        repo = _repository(tmp_path, "junk")
        with TestClient(app) as client:
            project_id = _analysed(client, repo, "Junk")
            response = client.post(
                f"{PREFIX}/projects/{project_id}/reports", content="<html>nope</html>"
            )
            assert response.status_code == 422


class TestInventory:
    def test_the_inventory_groups_by_file_and_separates_the_families(self, tmp_path: Path):
        repo = _repository(tmp_path, "inventory")
        with TestClient(app) as client:
            project_id = _analysed(client, repo, "Inventory")
            client.post(f"{PREFIX}/projects/{project_id}/reports", content=PYTEST_REPORT)
            client.post(f"{PREFIX}/projects/{project_id}/reports", content=PLAYWRIGHT_REPORT)

            body = client.get(f"{PREFIX}/inventory?project_id={project_id}").json()
            assert body["totals"]["tests"] == 6
            assert body["totals"]["passed"] == 4
            assert body["totals"]["failed"] == 1
            assert body["totals"]["skipped"] == 1
            assert {suite["kind"] for suite in body["suites"]} == {"backend", "e2e"}
            # Red first: a standup reads the top of a list.
            assert body["suites"][0]["failed"] == 1

    def test_a_suite_nobody_has_run_is_not_a_failing_suite(self, tmp_path: Path):
        """Reporting "not run" as a problem pushes a team to run everything before every
        standup; reporting it as a pass is a lie."""
        repo = _repository(tmp_path, "neverrun")
        with TestClient(app) as client:
            project_id = _analysed(client, repo, "Never run")
            body = client.get(f"{PREFIX}/inventory?project_id={project_id}").json()
            assert body["totals"]["tests"] == 2
            assert body["totals"]["notRun"] == 2
            assert body["totals"]["failed"] == 0
            # Nothing ran, so there is no rate to report.
            assert body["totals"]["passRate"] is None

    def test_the_pass_rate_counts_only_what_ran(self, tmp_path: Path):
        repo = _repository(tmp_path, "rate")
        with TestClient(app) as client:
            project_id = _analysed(client, repo, "Rate")
            client.post(f"{PREFIX}/projects/{project_id}/reports", content=PYTEST_REPORT)
            body = client.get(f"{PREFIX}/inventory?project_id={project_id}").json()
            # 2 passed, 1 failed, 1 skipped, plus 2 Playwright tests never run.
            assert body["totals"]["passRate"] == pytest.approx(2 / 3 * 100)

SAME_NAME_TWICE = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="2" time="1">
  <testcase classname="tests.test_comptes" name="test_validation" time="0.1"/>
  <testcase classname="tests.test_portefeuille" name="test_validation" time="0.1"/>
</testsuite>
"""


def test_two_tests_sharing_a_name_in_different_files_stay_two_tests(tmp_path: Path):
    """Matching on the title alone looked like a kindness — a suite that moved directory
    keeps its tests — and merged 17 of a thousand pytest tests into unrelated rows,
    because a function name like `test_validation` occurs in as many modules as you care
    to write."""
    repo = _repository(tmp_path, "collide")
    with TestClient(app) as client:
        project_id = _analysed(client, repo, "Collide")
        posted = client.post(f"{PREFIX}/projects/{project_id}/reports", content=SAME_NAME_TWICE)
        assert posted.json()["created"] == 2

        backend = [
            t
            for t in client.get(f"{PREFIX}/tests?project_id={project_id}").json()
            if t["kind"] == "backend"
        ]
        assert len(backend) == 2
        assert {t["file"] for t in backend} == {"tests/test_comptes", "tests/test_portefeuille"}

TWO_CLASSES = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="2" time="1">
  <testcase classname="tests.test_dividends.TestCroissance" name="test_sans_historique" time="0.1"/>
  <testcase classname="tests.test_dividends.TestEcheance" name="test_sans_historique" time="0.1"/>
</testsuite>
"""


def test_two_classes_of_one_module_are_two_tests():
    """`test_dividends` declares `test_sans_historique` in two classes. Dropping the class
    from the address made them collide and quietly lost half of each pair."""
    parsed = reports.parse(TWO_CLASSES)
    assert {test.name for test in parsed.tests} == {
        "TestCroissance::test_sans_historique",
        "TestEcheance::test_sans_historique",
    }
    # Grouping is still by file: the class is part of the name, not of the path.
    assert {test.file for test in parsed.tests} == {"tests/test_dividends"}
    assert len({test.key for test in parsed.tests}) == 2


def test_a_playwright_title_keeps_its_own_shape():
    """Only a dotted module path carries a class. A spec file's title is already whole."""
    parsed = reports.parse(PLAYWRIGHT_REPORT)
    assert parsed.tests[0].name.startswith("Portefeuille › ")
    assert "::" not in parsed.tests[0].name
