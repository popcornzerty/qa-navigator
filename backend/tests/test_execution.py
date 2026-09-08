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
