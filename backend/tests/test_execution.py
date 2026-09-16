"""Execution tests.

Playwright itself is not launched here: these cover the translation of its JSON report
into the outcome the UI shows, which is where the interpretation risk actually lives.
"""

from pathlib import Path

import pytest

from qa_engine import execution


def _report(status: str, **result) -> dict:
    return {
        "suites": [
            {
                "title": "chromium",
                "suites": [
                    {
                        "title": "Panier",
                        "specs": [
                            {
                                "title": "Augmenter la quantité",
                                "tests": [{"results": [{"status": status, **result}]}],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_passed_report(tmp_path: Path):
    outcome = execution.parse_report(_report("passed", duration=1234), tmp_path)
    assert outcome.status == "passed"
    assert outcome.duration_ms == 1234
    assert outcome.error_message is None


def test_failed_report_keeps_error_and_artifacts(tmp_path: Path):
    report = _report(
        "failed",
        duration=4120,
        error={"message": "expect(received).toBeVisible()"},
        attachments=[
            {"name": "screenshot", "path": str(tmp_path / "test-results" / "shot.png")},
            {"name": "trace", "path": str(tmp_path / "test-results" / "trace.zip")},
        ],
        stdout=[{"text": "navigated\n"}],
        stderr=[{"text": "warning\n"}],
    )
    outcome = execution.parse_report(report, tmp_path)

    assert outcome.status == "failed"
    assert "toBeVisible" in outcome.error_message
    # Artifact paths are stored relative to the repository, not as absolute paths.
    assert outcome.screenshot == "test-results/shot.png"
    assert outcome.trace == "test-results/trace.zip"
    assert outcome.console_output == ["[out] navigated", "[err] warning"]


def test_timed_out_is_reported_as_failed(tmp_path: Path):
    outcome = execution.parse_report(_report("timedOut", duration=30000), tmp_path)
    assert outcome.status == "failed"
    assert "délai" in outcome.error_message


def test_interrupted_is_reported_as_failed(tmp_path: Path):
    outcome = execution.parse_report(_report("interrupted"), tmp_path)
    assert outcome.status == "failed"


def test_fixme_shows_up_as_skipped(tmp_path: Path):
    """`test.fixme()` — what an ungrounded generated spec emits — reports as skipped."""
    outcome = execution.parse_report(_report("skipped"), tmp_path)
    assert outcome.status == "skipped"


def test_empty_report_is_not_a_pass(tmp_path: Path):
    outcome = execution.parse_report({"suites": []}, tmp_path)
    assert outcome.status == "not_run"
    assert outcome.error_message


def test_last_retry_wins(tmp_path: Path):
    report = {
        "suites": [
            {
                "specs": [
                    {
                        "title": "flaky",
                        "tests": [
                            {
                                "results": [
                                    {"status": "failed", "duration": 100},
                                    {"status": "passed", "duration": 200},
                                ]
                            }
                        ],
                    }
                ]
            }
        ]
    }
    outcome = execution.parse_report(report, tmp_path)
    assert outcome.status == "passed"
    assert outcome.duration_ms == 200


def test_missing_spec_file_is_reported(tmp_path: Path):
    with pytest.raises(execution.ExecutionError, match="introuvable"):
        execution.run_spec(str(tmp_path), "tests/absent.spec.ts", base_url="http://localhost:8080")


def test_ansi_colour_codes_are_stripped(tmp_path: Path):
    coloured = "\x1b[2mexpect(\x1b[22m\x1b[31mlocator\x1b[39m).toBeVisible() failed"
    report = _report(
        "failed",
        duration=10,
        error={"message": coloured},
        stdout=[{"text": "\x1b[32mok\x1b[39m\n"}],
    )
    outcome = execution.parse_report(report, tmp_path)

    assert outcome.error_message == "expect(locator).toBeVisible() failed"
    assert outcome.console_output == ["[out] ok"]


def test_the_child_does_not_inherit_no_color(tmp_path: Path, monkeypatch):
    """Node warns on every run when NO_COLOR meets the FORCE_COLOR Playwright sets itself.

    The variable describes the terminal of whoever started the engine, which has nothing
    to do with a subprocess whose output is captured and re-rendered.
    """
    captured: dict[str, dict[str, str]] = {}

    class _Fake:
        stdout = iter(())
        returncode = 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(command, **kwargs):
        captured["env"] = kwargs["env"]
        raise OSError("stopped before running")

    spec = tmp_path / "tests"
    spec.mkdir()
    (spec / "a.spec.ts").write_text("test('x', () => {})", encoding="utf-8")

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(execution.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(execution, "_find_npx", lambda: "npx")

    with pytest.raises(execution.ExecutionError):
        execution.run_spec(str(tmp_path), "tests/a.spec.ts")

    assert "NO_COLOR" not in captured["env"]

REFUSED_OUTPUT = [
    "Running 2 tests using 1 worker",
    "[WebServer] 11:31:45 [vite] http proxy error: /api/auth/login",
    "[WebServer] Error: connect ECONNREFUSED 127.0.0.1:8801",
    "  x  1 [connexion] › e2e-reel\\connexion.setup.ts:16:1 › ouvre une session",
]


def test_a_refused_backend_is_named_before_the_symptom():
    """With the application's API down, the login never completes and Playwright reports
    `getByRole('button', { name: 'Portefeuille' })` not visible — which reads as a broken
    selector. The real cause sat forty lines up the console."""
    outcome = execution.ExecutionOutcome(
        status="failed", error_message="Error: expect(locator).toBeVisible() failed"
    )
    explained = execution.explain_unreachable_backend(outcome, REFUSED_OUTPUT)
    assert explained.error_message.startswith("L'application testée ne répond pas sur 127.0.0.1:8801")
    # The original failure is kept, below the explanation.
    assert "toBeVisible() failed" in explained.error_message


def test_a_passing_run_is_never_annotated():
    outcome = execution.ExecutionOutcome(status="passed")
    assert execution.explain_unreachable_backend(outcome, REFUSED_OUTPUT).error_message is None


def test_a_failure_with_the_backend_up_is_left_as_it_is():
    outcome = execution.ExecutionOutcome(status="failed", error_message="assert 1 == 2")
    explained = execution.explain_unreachable_backend(outcome, ["Running 1 test", "  x  1 test"])
    assert explained.error_message == "assert 1 == 2"

THROTTLED_SNAPSHOT = """# Error details

```yaml
- img "Terminal PEA"
- paragraph: Actions européennes éligibles au PEA. Accès réservé aux comptes de test.
- alert: Trop de tentatives de connexion. Réessayez dans quelques minutes.
- text: Identifiant
- button "Se connecter"
```
"""


def test_the_alert_a_page_showed_is_read_from_its_snapshot():
    assert execution.page_alerts(THROTTLED_SNAPSHOT) == [
        "Trop de tentatives de connexion. Réessayez dans quelques minutes."
    ]


def test_an_alert_whose_text_sits_in_its_children_is_read_too():
    snapshot = "- main:\n  - alert:\n    - paragraph: Le mot de passe est incorrect.\n  - button \"OK\"\n"
    assert execution.page_alerts(snapshot) == ["Le mot de passe est incorrect."]


def test_a_page_without_an_alert_says_nothing():
    assert execution.page_alerts('- button "Se connecter"\n- text: Identifiant\n') == []


def test_the_alert_is_quoted_above_the_symptom(tmp_path):
    """A login refused by the anti-brute-force limit surfaced as a button not found. The
    page said why, in a snapshot Playwright had written to disk that nobody opened."""
    context = tmp_path / "test-results" / "connexion-setup" / "error-context.md"
    context.parent.mkdir(parents=True)
    context.write_text(THROTTLED_SNAPSHOT, encoding="utf-8")
    printed = [
        "  x  1 [connexion] › e2e-reel\\connexion.setup.ts:16:1 › ouvre une session",
        "    Error Context: test-results\\connexion-setup\\error-context.md",
    ]
    outcome = execution.ExecutionOutcome(
        status="failed",
        error_message="Locator: getByRole('button', { name: 'Portefeuille' })",
    )

    explained = execution.explain_page_alert(outcome, printed, tmp_path)

    assert explained.error_message.startswith("Au moment de l'échec, la page affichait :")
    assert "« Trop de tentatives de connexion" in explained.error_message
    assert explained.error_message.endswith("{ name: 'Portefeuille' })")


def test_a_missing_snapshot_leaves_the_failure_as_it_is(tmp_path):
    outcome = execution.ExecutionOutcome(status="failed", error_message="assert 1 == 2")
    printed = ["    Error Context: test-results\\absent\\error-context.md"]
    assert execution.explain_page_alert(outcome, printed, tmp_path).error_message == "assert 1 == 2"


def test_a_passing_run_is_not_given_an_alert(tmp_path):
    outcome = execution.ExecutionOutcome(status="passed")
    assert execution.explain_page_alert(outcome, [], tmp_path).error_message is None
