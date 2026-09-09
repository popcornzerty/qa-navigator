"""Playwright execution.

The engine shells out to the project's own ``npx playwright test``, so a run here behaves
exactly like a run on a developer machine or in CI — same config, same browsers, same
reporters. Nothing about the test is reinterpreted: the JSON reporter is the source of
truth for status, duration, error and artifacts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 600

# Playwright statuses that are failures for QA purposes.
FAILED_STATUSES = {"failed", "timedOut", "interrupted"}

# Playwright colourises its assertion messages; the UI renders plain text.
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(value: str | None) -> str | None:
    return ANSI_ESCAPE.sub("", value) if value else value


class ExecutionError(RuntimeError):
    """Raised when the runner could not be started at all."""


@dataclass
class ExecutionOutcome:
    status: str  # passed | failed | skipped | not_run
    duration_ms: int = 0
    error_message: str | None = None
    screenshot: str | None = None
    trace: str | None = None
    console_output: list[str] = field(default_factory=list)
    # Per-test tally. A generated spec holds one test, so these are all 0 or 1; an
    # imported file can hold dozens, and reporting only the aggregate status would hide
    # how much of it actually passed.
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0


def _find_npx() -> str:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise ExecutionError(
            "npx introuvable. Node.js doit être installé et disponible dans le PATH du service."
        )
    return npx


def _walk_specs(node: dict):
    """Yield every spec in a Playwright JSON report, whatever the suite nesting."""
    for suite in node.get("suites", []) or []:
        yield from _walk_specs(suite)
    for spec in node.get("specs", []) or []:
        yield spec


def _status_of(raw_status: str) -> str:
    if raw_status in FAILED_STATUSES:
        return "failed"
    if raw_status in {"passed", "skipped"}:
        return raw_status
    return "not_run"


def parse_report(report: dict, repository_root: Path) -> ExecutionOutcome:
    """Turn a Playwright JSON report into the outcome the UI displays.

    One report can cover many tests: a file written by hand holds as many as its author
    wanted. Each test contributes its own verdict — retries aside, where the last attempt
    is the one that counts — and the file is red as soon as one of them is red. Reading
    only the last result, as this did when every spec held exactly one scenario, reported
    a suite of twelve on the strength of its twelfth test.
    """

    def relative(path: str | None) -> str | None:
        if not path:
            return None
        try:
            return Path(path).resolve().relative_to(repository_root.resolve()).as_posix()
        except (ValueError, OSError):
            return path

    tally = {"passed": 0, "failed": 0, "skipped": 0, "not_run": 0}
    duration = 0
    console: list[str] = []
    first_failure: tuple[str, dict] | None = None

    for spec in _walk_specs(report):
        title = spec.get("title") or ""
        for test in spec.get("tests", []) or []:
            attempts = test.get("results", []) or []
            if not attempts:
                continue
            # Retries: only the final attempt decides. Counting each one would report a
            # flaky test as several failures plus a pass.
            result = attempts[-1]
            status = _status_of(result.get("status", ""))
            tally[status] += 1
            duration += int(result.get("duration") or 0)

            if status == "failed" and first_failure is None:
                first_failure = (title, result)

            for stream, prefix in (("stdout", "[out]"), ("stderr", "[err]")):
                for entry in result.get(stream, []) or []:
                    text = entry.get("text") if isinstance(entry, dict) else str(entry)
                    if text:
                        console.append(f"{prefix} {strip_ansi(text).rstrip()}")

    total = sum(tally.values())
    if total == 0:
        return ExecutionOutcome(status="not_run", error_message="Aucun test exécuté.")

    if tally["failed"]:
        status = "failed"
    elif tally["passed"]:
        status = "passed"
    elif tally["skipped"]:
        status = "skipped"
    else:
        status = "not_run"

    message = screenshot = trace = None
    if first_failure is not None:
        failing_title, result = first_failure
        error = result.get("error") or {}
        message = strip_ansi(error.get("message") or error.get("value"))
        if result.get("status") == "timedOut" and not message:
            message = "Le test a dépassé le délai maximum d'exécution."
        # With several tests in one file, an error message means nothing without the name
        # of the test that produced it.
        if message and tally["failed"] + tally["passed"] + tally["skipped"] > 1:
            others = tally["failed"] - 1
            header = f"« {failing_title} »"
            if others > 0:
                header += f" (et {others} autre{'s' if others > 1 else ''} en échec)"
            message = f"{header}\n{message}"

        for attachment in result.get("attachments", []) or []:
            name = attachment.get("name")
            if name == "screenshot" and not screenshot:
                screenshot = relative(attachment.get("path"))
            elif name == "trace" and not trace:
                trace = relative(attachment.get("path"))

    return ExecutionOutcome(
        status=status,
        duration_ms=duration,
        error_message=message,
        screenshot=screenshot,
        trace=trace,
        console_output=console,
        total=total,
        passed=tally["passed"],
        failed=tally["failed"],
        skipped=tally["skipped"],
    )


def grep_for(title: str) -> str:
    """An anchored regex selecting exactly one test title.

    Playwright matches `--grep` against the full title, describe blocks included, so an
    unescaped title containing brackets or a dot would select the wrong tests — or none.
    """
    return f"^{re.escape(title)}$"


def run_spec(
    repository_path: str,
    spec_file: str,
    *,
    base_url: str | None = None,
    working_directory: str = "",
    playwright_project: str | None = None,
    grep: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ExecutionOutcome:
    """Run one spec file — or one test inside it — and return its outcome.

    A non-zero exit code is expected when a test fails, so the report — not the exit
    code — decides the outcome.

    `working_directory` is where Playwright is invoked from, since its config, `testDir`,
    `webServer` and `baseURL` are all resolved relative to that directory. In a monorepo
    the config sits beside the application it tests, not at the repository root.
    """
    root = Path(repository_path)
    if not (root / spec_file).is_file():
        raise ExecutionError(f"Fichier de test introuvable : {spec_file}")

    cwd = (root / working_directory).resolve() if working_directory else root
    if not cwd.is_dir():
        raise ExecutionError(f"Répertoire d'exécution introuvable : {working_directory}")
    try:
        target = (root / spec_file).resolve().relative_to(cwd).as_posix()
    except ValueError:
        target = spec_file

    npx = _find_npx()
    # `CI` is deliberately not forced here: it would switch the project config to two
    # retries, tripling the duration of every failing run. The HTML reporter is already
    # configured with `open: "never"`, so nothing tries to open a browser either way.
    environment = {**os.environ}
    # Only set for specs the engine generated, which read it. A repository's own config
    # decides its base URL, and overriding it would point its suite at the wrong app.
    if base_url:
        environment["PLAYWRIGHT_BASE_URL"] = base_url

    with tempfile.TemporaryDirectory() as workspace:
        report_path = Path(workspace) / "report.json"
        environment["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(report_path)
        command = [npx, "playwright", "test", target, "--reporter=json"]
        if playwright_project:
            # Without this, a suite needing a live backend and a session can be dragged
            # into a run that required neither, and report red for nothing.
            command += [f"--project={playwright_project}"]
        if grep:
            command += ["--grep", grep]

        logger.info("Running %s in %s", target, cwd)
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExecutionError(
                f"L'exécution a dépassé {timeout_seconds}s et a été interrompue."
            ) from exc
        except OSError as exc:
            raise ExecutionError(f"Impossible de lancer Playwright : {exc}") from exc

        raw = report_path.read_text(encoding="utf-8") if report_path.is_file() else completed.stdout

    try:
        report = json.loads(raw)
    except (ValueError, TypeError) as exc:
        detail = (completed.stderr or completed.stdout or "")[-600:]
        raise ExecutionError(
            f"Playwright n'a pas produit de rapport JSON exploitable. Sortie : {detail}"
        ) from exc

    return parse_report(report, root)
