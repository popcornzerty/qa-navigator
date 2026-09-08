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


def parse_report(report: dict, repository_root: Path) -> ExecutionOutcome:
    """Turn a Playwright JSON report into the outcome the UI displays."""
    results = [
        result
        for spec in _walk_specs(report)
        for test in spec.get("tests", []) or []
        for result in test.get("results", []) or []
    ]
    if not results:
        return ExecutionOutcome(status="not_run", error_message="Aucun test exécuté.")

    # A spec file holds one scenario, but retries produce several results: the last one wins.
    result = results[-1]
    raw_status = result.get("status", "")
    if raw_status in FAILED_STATUSES:
        status = "failed"
    elif raw_status == "passed":
        status = "passed"
    elif raw_status == "skipped":
        status = "skipped"
    else:
        status = "not_run"

    error = result.get("error") or {}
    message = strip_ansi(error.get("message") or error.get("value"))
    if raw_status == "timedOut" and not message:
        message = "Le test a dépassé le délai maximum d'exécution."

    console: list[str] = []
    for stream, prefix in (("stdout", "[out]"), ("stderr", "[err]")):
        for entry in result.get(stream, []) or []:
            text = entry.get("text") if isinstance(entry, dict) else str(entry)
            if text:
                console.append(f"{prefix} {strip_ansi(text).rstrip()}")

    def relative(path: str | None) -> str | None:
        if not path:
            return None
        try:
            return Path(path).resolve().relative_to(repository_root.resolve()).as_posix()
        except (ValueError, OSError):
            return path

    screenshot = trace = None
    for attachment in result.get("attachments", []) or []:
        name = attachment.get("name")
        if name == "screenshot" and not screenshot:
            screenshot = relative(attachment.get("path"))
        elif name == "trace" and not trace:
            trace = relative(attachment.get("path"))

    return ExecutionOutcome(
        status=status,
        duration_ms=int(result.get("duration") or 0),
        error_message=message,
        screenshot=screenshot,
        trace=trace,
        console_output=console,
    )


def run_spec(
    repository_path: str,
    spec_file: str,
    *,
    base_url: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ExecutionOutcome:
    """Run one spec file and return its outcome.

    A non-zero exit code is expected when a test fails, so the report — not the exit
    code — decides the outcome.
    """
    root = Path(repository_path)
    if not (root / spec_file).is_file():
        raise ExecutionError(f"Fichier de test introuvable : {spec_file}")

    npx = _find_npx()
    # `CI` is deliberately not forced here: it would switch the project config to two
    # retries, tripling the duration of every failing run. The HTML reporter is already
    # configured with `open: "never"`, so nothing tries to open a browser either way.
    environment = {**os.environ, "PLAYWRIGHT_BASE_URL": base_url}

    with tempfile.TemporaryDirectory() as workspace:
        report_path = Path(workspace) / "report.json"
        environment["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(report_path)
        command = [npx, "playwright", "test", spec_file, "--reporter=json"]

        logger.info("Running %s in %s", spec_file, root)
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
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
