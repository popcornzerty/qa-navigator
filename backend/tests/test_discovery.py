"""Discovery and import of tests a repository already ships with."""

from __future__ import annotations

from pathlib import Path

from qa_engine.discovery import (
    TITLE_SEPARATOR,
    extract_tests,
    find_config,
    project_for,
    relative_to_config,
)
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
            f"Portefeuille{TITLE_SEPARATOR}Dividendes{TITLE_SEPARATOR}le badge apparaît",
            f"Portefeuille{TITLE_SEPARATOR}la ligne se supprime",
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

    def test_line_numbers_survive_a_line_comment(self):
        source = '// en-tête\n\ntest("premier", async () => {});\n'
        assert extract_tests(source, "a.spec.ts")[0].line == 3

    def test_line_numbers_survive_a_block_comment(self):
        """Removing a block comment outright renumbered everything after it.

        These files open with a long explanatory header, so the reported line landed deep
        inside the next comment instead of on the test it was meant to point at.
        """
        source = (
            'import { test } from "@playwright/test";\n'
            "/**\n * Une explication\n * sur plusieurs lignes\n */\n"
            'test("premier", async () => {});\n'
        )
        found = extract_tests(source, "a.spec.ts")
        assert found[0].line == 6
        assert source.split("\n")[found[0].line - 1].startswith("test(")

    def test_a_test_after_several_block_comments_keeps_its_line(self):
        source = "/* un */\n/* deux\n   suite */\n\n" + 'test("cible", async () => {});\n'
        found = extract_tests(source, "a.spec.ts")
        assert source.split("\n")[found[0].line - 1].startswith("test(")


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

    def test_a_project_restricted_by_testmatch_does_not_claim_the_directory(self, tmp_path: Path):
        """`connexion` shares e2e-reel with `reel` but only owns its setup file."""
        (tmp_path / "e2e-reel").mkdir()
        spec = tmp_path / "e2e-reel/mur.spec.ts"
        spec.write_text("test('x', () => {})", encoding="utf-8")
        assert project_for(CONFIG, tmp_path, spec) == "reel"

    def test_a_genuinely_shared_directory_stays_undecided(self, tmp_path: Path):
        """Two unrestricted projects on one testDir: guessing would risk the wrong one."""
        config = """
        export default { projects: [
          { name: "chrome", testDir: "e2e" },
          { name: "firefox", testDir: "e2e" },
        ] };
        """
        (tmp_path / "e2e").mkdir()
        spec = tmp_path / "e2e/a.spec.ts"
        spec.write_text("test('x', () => {})", encoding="utf-8")
        assert project_for(config, tmp_path, spec) is None

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
    def test_regex_characters_in_a_title_are_neutralised(self):
        """Unescaped, "coût (net)" would be read as a capture group and match nothing."""
        assert grep_for("coût (net) + frais") == r" coût \(net\) \+ frais$"

    def test_spaces_are_not_backslash_escaped(self):
        r"""`\ ` is a syntax error in a Unicode-mode JavaScript regex."""
        assert r"\ " not in grep_for("deux mots")

    def test_the_display_separator_becomes_a_plain_space(self):
        """Playwright greps against `<file> <describe> <test>`, joined by spaces.

        The `›` only ever appears in what `--list` prints; building a pattern from the
        displayed title matches nothing at all.
        """
        assert grep_for(f"Portefeuille{TITLE_SEPARATOR}la ligne se supprime") == (
            " Portefeuille la ligne se supprime$"
        )

    def test_the_start_is_not_anchored(self):
        """The grepped string begins with the file path, so `^` never matches."""
        assert not grep_for("un test").startswith("^")

    def test_a_longer_title_is_not_swept_in(self):
        """The common case: one title extending another must not be selected too."""
        import re as _re

        pattern = _re.compile(grep_for("celui-ci passe"))
        assert pattern.search("a.spec.ts:4:3 Suite celui-ci passe")
        assert not pattern.search("a.spec.ts:4:3 Suite celui-ci passe aussi")

    def test_a_title_that_is_a_suffix_of_another_over_selects(self):
        """Documented limit, not an aspiration: end-anchoring cannot separate these.

        Over-selection is confined to the one file being run, and the outcome reports
        how many tests actually ran, so it is visible rather than silent.
        """
        import re as _re

        assert _re.compile(grep_for("passe")).search("a.spec.ts:4:3 Suite celui-ci passe")


class TestRepositoryConfig:
    """Choosing where a generated spec is written, which decides whether it can run."""

    def _monorepo(self, tmp_path: Path) -> Path:
        (tmp_path / "frontend" / "node_modules").mkdir(parents=True)
        (tmp_path / "frontend" / "playwright.config.ts").write_text(
            'export default { use: { baseURL: "http://localhost:5180" } };', encoding="utf-8"
        )
        return tmp_path

    def test_the_installation_decides_not_the_root(self, tmp_path: Path):
        """A spec written at the root is run by an npx download that cannot resolve
        `@playwright/test`, and the run dies on the import line."""
        from qa_engine.discovery import find_repository_config

        root = self._monorepo(tmp_path)
        assert find_repository_config(root) == root / "frontend" / "playwright.config.ts"

    def test_a_config_with_an_installation_beats_a_shallower_one(self, tmp_path: Path):
        from qa_engine.discovery import find_repository_config

        root = self._monorepo(tmp_path)
        (root / "playwright.config.ts").write_text("export default {};", encoding="utf-8")
        assert find_repository_config(root).parent.name == "frontend"

    def test_a_repository_without_any_config_has_none(self, tmp_path: Path):
        from qa_engine.discovery import find_repository_config

        assert find_repository_config(tmp_path) is None

    def test_the_declared_base_url_is_read(self, tmp_path: Path):
        from qa_engine.discovery import base_url_of, find_repository_config

        root = self._monorepo(tmp_path)
        config = find_repository_config(root)
        assert base_url_of(config.read_text(encoding="utf-8")) == "http://localhost:5180"


class TestStringsAreNotComments:
    """`//` only starts a comment outside a string."""

    def test_a_url_in_a_config_survives(self):
        from qa_engine.discovery import base_url_of

        # Cut at `"http:` before this, so a generated spec was aimed at nothing.
        assert base_url_of('use: { baseURL: "http://localhost:5180" }') == "http://localhost:5180"

    def test_a_url_in_a_test_title_survives(self):
        source = 'test("ouvre https://exemple.fr/page", async () => {});'
        assert [item.title for item in extract_tests(source, "a.spec.ts")] == [
            "ouvre https://exemple.fr/page"
        ]

    def test_a_real_comment_is_still_neutralised(self):
        assert extract_tests('// test("faux", () => {});', "a.spec.ts") == []

    def test_a_brace_after_a_url_still_counts(self):
        """Blanking the rest of the line past a false comment shifted describe nesting."""
        source = (
            'const base = "https://exemple.fr"; test.describe("Suite", () => {\n'
            '  test("dedans", async () => {});\n});\n'
        )
        found = extract_tests(source, "a.spec.ts")
        assert [item.full_title for item in found] == [f"Suite{TITLE_SEPARATOR}dedans"]
