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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from qa_engine.discovery import TITLE_SEPARATOR

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 600

NEWLINE = "\n"

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
    r"""A regex selecting one test out of a file, given its ``describe › test`` path.

    Two things about `--grep` are easy to get wrong, and both make it match nothing:

    * It runs against ``<file path> <describe> <test>`` joined by **plain spaces**. The
      ``›`` separator only ever appears in what `--list` prints, so a pattern built from
      the displayed title never matches.
    * That string starts with the file path, so anchoring at the start never matches
      either. Only the end is anchored.

    Escaping matters too: a title containing brackets or a dot would otherwise select the
    wrong tests. Spaces are put back verbatim, since ``\ `` is a syntax error in a
    Unicode-mode JavaScript regex.

    This selects one test whenever no other title in the file *ends with* the same words:
    "celui-ci passe" is correctly told apart from "celui-ci passe aussi", but a bare
    "passe" would also select "celui-ci passe". The spec file is passed to Playwright as
    well, so any over-selection stays inside one file, and the outcome reports the tally
    of what actually ran rather than assuming a single test.
    """
    escaped = re.escape(title.replace(TITLE_SEPARATOR, " ")).replace(r"\ ", " ")
    return f" {escaped}$"


def _stream(
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
    on_output: Callable[[str], None] | None,
) -> list[str]:
    """Run the command, forwarding each line as it arrives. Returns everything printed.

    stderr is merged into stdout so the two stay in the order they were written: read
    separately, a warning and the test it concerns end up in different places.
    """
    printed: list[str] = []
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise ExecutionError(f"Impossible de lancer Playwright : {exc}") from exc

    deadline = time.monotonic() + timeout_seconds
    try:
        assert process.stdout is not None
        for line in process.stdout:
            text = strip_ansi(line.rstrip()) or ""
            printed.append(text)
            if on_output is not None:
                try:
                    on_output(text)
                except Exception:  # a failing observer must not abort the run
                    logger.exception("Output observer failed")
            if time.monotonic() > deadline:
                raise TimeoutError
        process.wait(timeout=max(1, int(deadline - time.monotonic())))
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        process.kill()
        process.wait()
        raise ExecutionError(
            f"L'exécution a dépassé {timeout_seconds}s et a été interrompue."
        ) from exc
    finally:
        if process.stdout is not None:
            process.stdout.close()
    return printed


def run_spec(
    repository_path: str,
    spec_file: str,
    *,
    base_url: str | None = None,
    working_directory: str = "",
    playwright_project: str | None = None,
    grep: str | None = None,
    on_output: Callable[[str], None] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ExecutionOutcome:
    """Run one spec file — or one test inside it — and return its outcome.

    A non-zero exit code is expected when a test fails, so the report — not the exit
    code — decides the outcome.

    `working_directory` is where Playwright is invoked from, since its config, `testDir`,
    `webServer` and `baseURL` are all resolved relative to that directory. In a monorepo
    the config sits beside the application it tests, not at the repository root.

    `on_output` receives each line as Playwright prints it. The JSON reporter only writes
    once everything has finished, so a caller holding only the report has nothing to show
    for however long the run takes — which for a suite starting its own dev server is
    minutes. The `list` reporter is added alongside it purely to have something to
    forward; the JSON file remains the sole source of the verdict.
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
        command = [npx, "playwright", "test", target, "--reporter=list,json"]
        if playwright_project:
            # Without this, a suite needing a live backend and a session can be dragged
            # into a run that required neither, and report red for nothing.
            command += [f"--project={playwright_project}"]
        if grep:
            command += ["--grep", grep]

        logger.info("Running %s in %s", target, cwd)
        printed = _stream(command, cwd, environment, timeout_seconds, on_output)

        if not report_path.is_file():
            raise ExecutionError(
                "Playwright n'a produit aucun rapport JSON. Sortie : "
                + NEWLINE.join(printed[-12:])[-600:]
            )
        raw = report_path.read_text(encoding="utf-8")

    try:
        report = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ExecutionError(
            "Playwright n'a pas produit de rapport JSON exploitable. Sortie : "
            + NEWLINE.join(printed[-12:])[-600:]
        ) from exc

    return parse_report(report, root)
