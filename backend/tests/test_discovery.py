"""Discovery and import of tests a repository already ships with."""

from __future__ import annotations

from pathlib import Path

from qa_engine.discovery import extract_tests, find_config, project_for, relative_to_config
from qa_engine.execution import grep_for, parse_report
from qa_engine.repositories import is_test_file, is_test_material

CONFIG = """
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  projects: [
    { name: "bouchonne", testDir: "e2e", use: { ...devices["Desktop Chrome"] } },
    { name: "reel", testDir: "e2e-reel", dependencies: ["connexion"] },
    { name: "connexion", testDir: "e2e-reel", testMatch: ["**/connexion.setup.ts"] },
  ],
});
"""


class TestClassification:
    def test_a_spec_is_a_test_file(self):
        assert is_test_file("e2e/acces.spec.ts")
        assert is_test_file("src/Widget.test.tsx")
        assert not is_test_file("src/App.tsx")

    def test_a_name_merely_containing_spec_is_not(self):
        """`specs.ts` and `latest.ts` are application files, not suites."""
        assert not is_test_file("src/specs.ts")
        assert not is_test_file("src/manifest.ts")

    def test_helpers_beside_a_suite_are_test_material(self):
        """A stub is not runnable, but reading it as product code describes the stubs."""
        assert is_test_material("e2e/bouchons.ts")
        assert is_test_material("e2e/fixtures/portefeuille.ts")
        assert not is_test_file("e2e/bouchons.ts")

    def test_application_code_is_neither(self):
        assert not is_test_material("frontend/src/components/Chart.tsx")


class TestExtraction:
    def test_a_test_keeps_the_describes_that_enclose_it(self):
        source = """
        test.describe("Portefeuille", () => {
          test.describe("Dividendes", () => {
            test("le badge apparaît", async ({ page }) => {});
          });
          test("la ligne se supprime", async ({ page }) => {});
        });
        """
        found = extract_tests(source, "e2e/p.spec.ts")
        assert [item.full_title for item in found] == [
            "Portefeuille > Dividendes > le badge apparaît",
            "Portefeuille > la ligne se supprime",
        ]

    def test_steps_are_not_tests(self):
        """The engine's own specs are built entirely from `test.step`."""
        source = """
        test.describe("Projets", () => {
          test("Lancer l'analyse", async ({ page }) => {
            await test.step("Étant donné je suis sur la page", async () => {});
            await test.step("Quand je clique", async () => {});
          });
        });
        """
        found = extract_tests(source, "tests/us-001.spec.ts")
        assert [item.title for item in found] == ["Lancer l'analyse"]

    def test_skipped_tests_are_marked_not_dropped(self):
        source = """
        test("actif", async () => {});
        test.skip("mis de côté", async () => {});
        test.fixme("à traiter", async () => {});
        """
        found = extract_tests(source, "e2e/a.spec.ts")
        assert [(item.title, item.skipped) for item in found] == [
            ("actif", False),
            ("mis de côté", True),
            ("à traiter", True),
        ]

    def test_a_commented_out_test_is_not_counted(self):
        source = """
        // test("désactivé", async () => {});
        /* test("aussi désactivé", async () => {}); */
        test("réel", async () => {});
        """
        assert [item.title for item in extract_tests(source, "a.spec.ts")] == ["réel"]

    def test_line_numbers_survive_comment_stripping(self):
        source = "// en-tête\n\ntest(\"premier\", async () => {});\n"
        assert extract_tests(source, "a.spec.ts")[0].line == 3


class TestConfigResolution:
    def test_the_nearest_config_above_the_spec_wins(self, tmp_path: Path):
        (tmp_path / "frontend/e2e").mkdir(parents=True)
        (tmp_path / "playwright.config.ts").write_text("export default {}", encoding="utf-8")
        (tmp_path / "frontend/playwright.config.ts").write_text(CONFIG, encoding="utf-8")
        (tmp_path / "frontend/e2e/a.spec.ts").write_text("test('x', () => {})", encoding="utf-8")

        found = find_config(tmp_path, "frontend/e2e/a.spec.ts")
        assert found == tmp_path / "frontend/playwright.config.ts"

    def test_a_spec_runs_under_the_project_owning_its_directory(self, tmp_path: Path):
        (tmp_path / "e2e").mkdir()
        spec = tmp_path / "e2e/acces.spec.ts"
        spec.write_text("test('x', () => {})", encoding="utf-8")
        assert project_for(CONFIG, tmp_path, spec) == "bouchonne"

    def test_a_suite_needing_a_backend_is_not_dragged_in(self, tmp_path: Path):
        """`reel` and `connexion` share a testDir, so neither can be chosen alone."""
        (tmp_path / "e2e-reel").mkdir()
        spec = tmp_path / "e2e-reel/portefeuille.spec.ts"
        spec.write_text("test('x', () => {})", encoding="utf-8")
        assert project_for(CONFIG, tmp_path, spec) is None

    def test_a_config_without_projects_selects_none(self, tmp_path: Path):
        spec = tmp_path / "a.spec.ts"
        spec.write_text("test('x', () => {})", encoding="utf-8")
        assert project_for("export default { testDir: 'tests' }", tmp_path, spec) is None

    def test_the_spec_argument_is_relative_to_the_config(self, tmp_path: Path):
        (tmp_path / "frontend/e2e").mkdir(parents=True)
        spec = tmp_path / "frontend/e2e/a.spec.ts"
        spec.write_text("", encoding="utf-8")
        assert relative_to_config(tmp_path / "frontend", spec) == "e2e/a.spec.ts"


def _report(*tests: tuple[str, str]) -> dict:
    return {
        "suites": [
            {
                "specs": [
                    {"title": title, "tests": [{"results": [{"status": status, "duration": 10}]}]}
                    for title, status in tests
                ]
            }
        ]
    }


class TestAggregation:
    def test_one_failure_among_many_makes_the_file_red(self, tmp_path: Path):
        outcome = parse_report(
            _report(("a", "passed"), ("b", "failed"), ("c", "passed")), tmp_path
        )
        assert outcome.status == "failed"
        assert (outcome.total, outcome.passed, outcome.failed) == (3, 2, 1)

    def test_a_late_pass_no_longer_hides_an_early_failure(self, tmp_path: Path):
        """The previous reader took the last result, so this reported green."""
        assert parse_report(_report(("a", "failed"), ("b", "passed")), tmp_path).status == "failed"

    def test_durations_are_summed_over_the_file(self, tmp_path: Path):
        assert parse_report(_report(("a", "passed"), ("b", "passed")), tmp_path).duration_ms == 20

    def test_a_retried_test_counts_once(self, tmp_path: Path):
        report = {
            "suites": [
                {
                    "specs": [
                        {
                            "title": "instable",
                            "tests": [
                                {
                                    "results": [
                                        {"status": "failed", "duration": 10},
                                        {"status": "passed", "duration": 10},
                                    ]
                                }
                            ],
                        }
                    ]
                }
            ]
        }
        outcome = parse_report(report, tmp_path)
        assert (outcome.status, outcome.total, outcome.passed) == ("passed", 1, 1)

    def test_an_error_message_names_the_failing_test(self, tmp_path: Path):
        report = {
            "suites": [
                {
                    "specs": [
                        {"title": "ok", "tests": [{"results": [{"status": "passed"}]}]},
                        {
                            "title": "la vente enregistre la plus-value",
                            "tests": [
                                {
                                    "results": [
                                        {"status": "failed", "error": {"message": "attendu 12"}}
                                    ]
                                }
                            ],
                        },
                    ]
                }
            ]
        }
        message = parse_report(report, tmp_path).error_message
        assert "la vente enregistre la plus-value" in message
        assert "attendu 12" in message

    def test_a_single_test_file_keeps_a_bare_message(self, tmp_path: Path):
        report = _report(("seul", "failed"))
        report["suites"][0]["specs"][0]["tests"][0]["results"][0]["error"] = {"message": "boum"}
        assert parse_report(report, tmp_path).error_message == "boum"

    def test_an_all_skipped_file_is_skipped(self, tmp_path: Path):
        assert parse_report(_report(("a", "skipped"), ("b", "skipped")), tmp_path).status == "skipped"

    def test_an_empty_report_is_not_a_pass(self, tmp_path: Path):
        assert parse_report({"suites": []}, tmp_path).status == "not_run"


class TestSelector:
    def test_a_title_with_regex_characters_selects_only_itself(self):
        assert grep_for("coût (net) + frais") == r"^coût\ \(net\)\ \+\ frais$"
